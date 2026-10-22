"""LLM layer. One interface, two clients.

- GrokClient: xAI API through the OpenAI-compatible endpoint https://api.x.ai/v1.
  Structured output via JSON schema, validated with Pydantic, and a self-correction
  loop that feeds validation errors back to the model (max 3 attempts).
- OfflineClient: no network. Reports itself unavailable so callers fall back to
  deterministic code. This is the default when XAI_API_KEY is not set.

Deterministic code is the source of truth for arithmetic. The LLM only extracts and reasons.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

XAI_BASE_URL = "https://api.x.ai/v1"
DEFAULT_MODEL = "grok-4.7"


class LLMUnavailable(RuntimeError):
    pass


class LLMOutputError(RuntimeError):
    def __init__(self, msg: str, attempts: list[dict]):
        super().__init__(msg)
        self.attempts = attempts


@dataclass
class LLMResult:
    value: BaseModel
    attempts: list[dict] = field(default_factory=list)   # one entry per try: errors, latency, tokens
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMClient(Protocol):
    name: str
    available: bool

    def complete_structured(self, schema: type[T], messages: list[dict], max_attempts: int = 3) -> LLMResult: ...


class OfflineClient:
    name = "offline"
    available = False

    def complete_structured(self, schema, messages, max_attempts=3):
        raise LLMUnavailable("Offline mode: no LLM calls. Deterministic parsers and rules only.")


class GrokClient:
    name = "grok"
    available = True

    def __init__(self, api_key: str | None = None, model: str | None = None, timeout: float = 60.0,
                 api_retries: int = 3):
        from openai import OpenAI

        key = api_key or os.environ.get("XAI_API_KEY")
        if not key:
            raise LLMUnavailable("XAI_API_KEY is not set")
        self.model = model or os.environ.get("XAI_MODEL") or DEFAULT_MODEL
        self.api_retries = api_retries
        self._client = OpenAI(api_key=key, base_url=XAI_BASE_URL, timeout=timeout)

    def _call(self, schema: type[BaseModel], messages: list[dict]):
        last = None
        for i in range(self.api_retries):
            try:
                return self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0,
                    response_format={"type": "json_schema", "json_schema": {
                        "name": schema.__name__, "schema": schema.model_json_schema()}},
                )
            except Exception as e:  # network, rate limit, 5xx
                last = e
                time.sleep(min(2 ** i, 8))
        raise LLMUnavailable(f"xAI API failed after {self.api_retries} tries: {last}")

    def complete_structured(self, schema, messages, max_attempts=3):
        msgs = list(messages)
        attempts: list[dict] = []
        result = LLMResult(value=None, model=self.model)  # type: ignore[arg-type]
        for n in range(1, max_attempts + 1):
            t0 = time.monotonic()
            resp = self._call(schema, msgs)
            content = resp.choices[0].message.content or ""
            usage = getattr(resp, "usage", None)
            result.prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
            result.completion_tokens += getattr(usage, "completion_tokens", 0) or 0
            entry = {"attempt": n, "latency_s": round(time.monotonic() - t0, 2)}
            try:
                value = schema.model_validate(json.loads(content))
                attempts.append(entry | {"ok": True})
                result.value, result.attempts = value, attempts
                return result
            except (json.JSONDecodeError, ValidationError) as e:
                err = str(e)[:1500]
                attempts.append(entry | {"ok": False, "error": err})
                msgs = msgs + [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": f"That output failed validation:\n{err}\nReturn corrected JSON only."},
                ]
        raise LLMOutputError(f"No valid {schema.__name__} after {max_attempts} attempts", attempts)


def get_client(mode: str = "auto") -> LLMClient:
    """mode: auto (Grok if XAI_API_KEY is set), offline, live."""
    if mode == "offline":
        return OfflineClient()
    if mode == "live":
        return GrokClient()
    try:
        return GrokClient()
    except LLMUnavailable:
        return OfflineClient()
