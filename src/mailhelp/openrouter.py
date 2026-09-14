"""Begrenzter OpenRouter-Client mit Timeouts, Wiederholung und Rate-Limit."""
from __future__ import annotations
import json, time, uuid
from datetime import datetime, timezone
from typing import Any, Callable
import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError


from .adapter import RetryPolicy


class RateLimitExceeded(RuntimeError):
    def __init__(self, next_allowed_at: float):
        self.next_allowed_at = next_allowed_at
        super().__init__(f"OpenRouter-Aufruflimit erreicht; naechster Aufruf {datetime.fromtimestamp(next_allowed_at, timezone.utc).isoformat()}")


class OpenRouterMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    content: str = Field(min_length=1)


class OpenRouterChoice(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    message: OpenRouterMessage


class OpenRouterResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    id: str = Field(min_length=1)
    choices: list[OpenRouterChoice] = Field(min_length=1)


class OpenRouterClient:
    def __init__(self, key: str, timeout: float, retries: int, calls_per_minute: int, transport: httpx.BaseTransport | None = None, sleep: Callable[[float], None] = time.sleep, *, initial_backoff: float = 1, max_backoff: float = 8, clock: Callable[[], float] = time.time, load_calls: Callable[[], list[float]] | None = None, save_calls: Callable[[list[float]], None] | None = None, stopped: Callable[[float], bool] | None = None):
        self.calls: list[float] = []
        self.key, self.limit, self.clock = key, calls_per_minute, clock
        self.load_calls = load_calls or (lambda: self.calls)
        self.save_calls = save_calls or (lambda calls: self.calls.__setitem__(slice(None), calls))
        self.client = httpx.Client(base_url="https://openrouter.ai/api/v1", timeout=timeout, transport=transport)
        wait = stopped or (lambda delay: (sleep(delay), False)[1])
        self.policy = RetryPolicy(retries, initial_backoff, max_backoff, wait, clock)

    def complete(self, model: str, parameters: dict[str, Any], system: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        now = self.clock()
        calls = sorted(value for value in self.load_calls() if isinstance(value, (int, float)) and now - value < 60)
        if len(calls) >= self.limit: raise RateLimitExceeded(calls[0] + 60)
        calls.append(now); self.save_calls(calls); call_id = str(uuid.uuid4())
        request = {**parameters, "model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], "response_format": {"type": "json_object"}}
        def invoke() -> httpx.Response:
            response = self.client.post("/chat/completions", headers={"Authorization": f"Bearer {self.key}", "X-Request-Id": call_id}, json=request)
            response.raise_for_status()
            return response
        response = self.policy.run(invoke)
        try: data = OpenRouterResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc: raise ValueError(f"OpenRouter chat/completions: ungültige Antwort am Schlüsselpfad {_path(exc)}") from exc
        try: content = json.loads(data.choices[0].message.content)
        except json.JSONDecodeError as exc: raise ValueError("OpenRouter chat/completions: ungültige Antwort am Schlüsselpfad choices.0.message.content") from exc
        if not isinstance(content, dict): raise ValueError("OpenRouter chat/completions: Schlüsselpfad choices.0.message.content muss ein JSON-Objekt sein")
        return call_id, content
    def close(self) -> None: self.client.close()


def _path(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return ", ".join(".".join(str(value) for value in item["loc"]) or "<root>" for item in exc.errors(include_input=False))
    return "<json>"
