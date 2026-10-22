"""LLM layer. One interface, two clients.

- GrokClient: xAI API through the OpenAI-compatible endpoint https://api.x.ai/v1.
  Structured output via JSON schema, validated with Pydantic, and a self-correction
  loop that feeds validation errors back to the model (max 3 attempts).
  Tool use: run_tools() lets the model call local functions (vendor master, inventory,
  invoice history) through OpenAI-style function calling before it answers.
- OfflineClient: no network. Reports itself unavailable so callers fall back to
  deterministic code. This is the default when XAI_API_KEY is not set.

Deterministic code is the source of truth for arithmetic. The LLM only extracts and reasons.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, TypeVar

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


@dataclass
class Tool:
    """A local function the model may call. parameters is a JSON schema object."""
    name: str
    description: str
    parameters: dict
    fn: Callable[..., Any]

    def spec(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.parameters}}


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
                 api_retries: int = 3, client: Any = None, sleep: Callable[[float], None] = time.sleep):
        self.model = model or os.environ.get("XAI_MODEL") or DEFAULT_MODEL
        self.api_retries = api_retries
        self._sleep = sleep
        if client is not None:          # tests inject a fake OpenAI-compatible client
            self._client = client
            return
        from openai import OpenAI

        key = api_key or os.environ.get("XAI_API_KEY")
        if not key:
            raise LLMUnavailable("XAI_API_KEY is not set")
        self._client = OpenAI(api_key=key, base_url=XAI_BASE_URL, timeout=timeout)

    def _create(self, **kw):
        last = None
        for i in range(self.api_retries):
            try:
                return self._client.chat.completions.create(model=self.model, temperature=0, **kw)
            except Exception as e:  # network, rate limit, 5xx
                last = e
                self._sleep(min(2 ** i, 8))
        raise LLMUnavailable(f"xAI API failed after {self.api_retries} tries: {last}")

    def _call(self, schema: type[BaseModel], messages: list[dict]):
        return self._create(messages=messages, response_format={"type": "json_schema", "json_schema": {
            "name": schema.__name__, "schema": schema.model_json_schema()}})

    def run_tools(self, messages: list[dict], tools: list[Tool], max_rounds: int = 4) -> tuple[list[dict], list[dict]]:
        """Let the model call local tools until it stops asking (or max_rounds).
        Returns the extended message list and a log of every call for the trace."""
        msgs = list(messages)
        by_name = {t.name: t for t in tools}
        calls: list[dict] = []
        for _ in range(max_rounds):
            resp = self._create(messages=msgs, tools=[t.spec() for t in tools], tool_choice="auto")
            msg = resp.choices[0].message
            tcs = getattr(msg, "tool_calls", None) or []
            if not tcs:
                break
            msgs.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name,
                                                                "arguments": tc.function.arguments}} for tc in tcs]})
            for tc in tcs:
                tool = by_name.get(tc.function.name)
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    out = tool.fn(**args) if tool else {"error": f"unknown tool {tc.function.name}"}
                except Exception as e:  # bad arguments from the model: report back, do not crash
                    args, out = tc.function.arguments, {"error": f"{type(e).__name__}: {e}"}
                calls.append({"tool": tc.function.name, "args": args, "result": out})
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(out, default=str)})
        return msgs, calls

    def complete_structured(self, schema, messages, max_attempts=3):
        msgs = list(messages)
        attempts: list[dict] = []
        result = LLMResult(value=None, model=self.model)  # type: ignore[arg-type]
        for n in range(1, max_attempts + 1):
            t0 = time.monotonic()
            resp = self._call(schema, msgs)
            result.model = getattr(resp, "model", None) or self.model   # the model id the API reports
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
