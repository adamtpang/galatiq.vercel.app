"""Decision cache and model pin for live mode (repeatability).

CachedLLM wraps GrokClient. Every Grok output for one invoice (the risk review's tool rounds, the risk
review, the VP and critic opinions, a Grok repair) is stored in SQLite under one key:

    sha256(normalized file content | policy version | model id | prompt version)

- normalized file content: the file bytes; for text formats line endings and trailing spaces are
  normalized, so a re-saved copy of the same invoice gets the same key
- policy version: sha256 of config/policy.yaml
- model id: the configured model (XAI_MODEL, default grok-4.7)
- prompt version: sha256 of the code that builds the prompts (agents/*.py, llm.py), so a prompt change
  never reuses an old answer

On a repeated invoice the stored outputs are reused in the same order, so a re-run gives the same
decision. Deterministic code (parsing, validation, hard rules, hard holds, payment idempotency) runs
fresh every time; only Grok's answers are reused. --no-cache turns reading and writing off.

Model pin: the model id the API returns is recorded for every call (and stored with cached outputs).
If it differs from the configured model, the invoice gets a MODEL_MISMATCH warning and is held for a
human (see graph.pin_check).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from . import ROOT
from .llm import LLMResult

TEXT_SUFFIXES = {".txt", ".json", ".csv", ".xml", ".md", ".eml"}
SCHEMA = ("CREATE TABLE IF NOT EXISTS llm_cache (cache_key TEXT NOT NULL, slot TEXT NOT NULL, output TEXT NOT NULL, "
          "model TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY (cache_key, slot))")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def normalized_content(path: str | Path) -> bytes:
    p = Path(path)
    data = p.read_bytes()
    if p.suffix.lower() in TEXT_SUFFIXES:
        text = data.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
        data = "\n".join(line.rstrip() for line in text.split("\n")).strip().encode()
    return data


def policy_version() -> str:
    return _sha((ROOT / "config" / "policy.yaml").read_bytes())[:16]


def prompt_version() -> str:
    files = sorted((ROOT / "invoice_agents" / "agents").glob("*.py")) + [ROOT / "invoice_agents" / "llm.py"]
    return _sha(b"".join(f.read_bytes() for f in files))[:16]


def cache_key(path: str | Path, model: str) -> str:
    parts = [_sha(normalized_content(path)), policy_version(), model, prompt_version()]
    return _sha("|".join(parts).encode())[:32]


class CachedLLM:
    """Same interface as GrokClient (complete_structured, run_tools, usage_log, name, model, available)."""

    available = True

    def __init__(self, inner: Any, conn: sqlite3.Connection | None, enabled: bool = True):
        self.inner, self.conn, self.enabled = inner, conn, enabled and conn is not None
        self.name, self.model = inner.name, inner.model
        if self.enabled:
            self.conn.execute(SCHEMA)
            self.conn.commit()
        self.key: str | None = None
        self._n: dict[str, int] = {}
        self.hits = self.misses = 0
        self.returned_models: list[str] = []   # model ids the API reported for this invoice

    @property
    def usage_log(self) -> list[dict]:
        return getattr(self.inner, "usage_log", [])

    def start(self, path: str | Path) -> None:
        """Called once per invoice before any Grok call."""
        try:
            self.key = cache_key(path, self.model)
        except OSError:
            self.key = None
        self._n, self.hits, self.misses, self.returned_models = {}, 0, 0, []

    def info(self) -> dict:
        return {"enabled": self.enabled, "key": self.key, "hits": self.hits, "misses": self.misses,
                "configured_model": self.model, "returned_models": sorted(set(self.returned_models))}

    def _slot(self, kind: str) -> str:
        self._n[kind] = self._n.get(kind, 0) + 1
        return f"{kind}#{self._n[kind]}"

    def _get(self, slot: str):
        if not (self.enabled and self.key):
            return None
        return self.conn.execute("SELECT output, model FROM llm_cache WHERE cache_key=? AND slot=?",
                                 (self.key, slot)).fetchone()

    def _put(self, slot: str, output: Any, model: str | None) -> None:
        if self.enabled and self.key:
            self.conn.execute("INSERT OR REPLACE INTO llm_cache (cache_key, slot, output, model) VALUES (?,?,?,?)",
                              (self.key, slot, json.dumps(output, default=str), model))
            self.conn.commit()

    def complete_structured(self, schema, messages, max_attempts=3, slot_tag: str | None = None):
        """slot_tag: stored answers are reused only for the same tag (the memo passes a digest of the decision,
        so a memo is never reused for a different outcome)."""
        slot = self._slot(schema.__name__ + (f":{slot_tag}" if slot_tag else ""))
        row = self._get(slot)
        if row is not None:
            self.hits += 1
            model = row[1] or self.model
            self.returned_models.append(model)
            return LLMResult(value=schema.model_validate(json.loads(row[0])), model=model,
                             attempts=[{"attempt": 1, "ok": True, "cached": True}])
        res = self.inner.complete_structured(schema, messages, max_attempts)
        self.misses += 1
        self.returned_models.append(res.model)
        self._put(slot, res.value.model_dump(mode="json"), res.model)
        return res

    def run_tools(self, messages, tools, max_rounds=4):
        if not hasattr(self.inner, "run_tools"):   # a client without tool use (test doubles)
            return list(messages), []
        slot = self._slot("tools")
        row = self._get(slot)
        if row is not None:
            self.hits += 1
            out = json.loads(row[0])
            self.returned_models.extend(out.get("models") or [])
            return list(messages) + out["added"], out["calls"]
        n0 = len(self.usage_log)
        msgs, calls = self.inner.run_tools(messages, tools, max_rounds)
        self.misses += 1
        models = [r.get("model") or self.model for r in self.usage_log[n0:]]
        self.returned_models.extend(models)
        self._put(slot, {"added": msgs[len(messages):], "calls": calls, "models": models}, models[-1] if models else None)
        return msgs, calls
