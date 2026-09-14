"""Begrenzter OpenRouter-Client mit Timeouts, Wiederholung und Rate-Limit."""
from __future__ import annotations
import json, time, uuid
from collections import deque
from typing import Any, Callable
import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class RateLimitExceeded(RuntimeError): pass


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
    def __init__(self, key: str, timeout: float, retries: int, calls_per_minute: int, transport: httpx.BaseTransport | None = None, sleep: Callable[[float], None] = time.sleep):
        self.key, self.retries, self.limit, self.sleep = key, retries, calls_per_minute, sleep
        self.client = httpx.Client(base_url="https://openrouter.ai/api/v1", timeout=timeout, transport=transport)
        self.calls: deque[float] = deque()

    def complete(self, model: str, parameters: dict[str, Any], system: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        now = time.monotonic()
        while self.calls and now - self.calls[0] >= 60: self.calls.popleft()
        if len(self.calls) >= self.limit: raise RateLimitExceeded("OpenRouter-Aufruflimit erreicht")
        self.calls.append(now); call_id = str(uuid.uuid4())
        request = {**parameters, "model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], "response_format": {"type": "json_object"}}
        attempt = 0
        while True:
            try:
                response = self.client.post("/chat/completions", headers={"Authorization": f"Bearer {self.key}"}, json=request)
                response.raise_for_status()
                try: data = OpenRouterResponse.model_validate(response.json())
                except (ValueError, ValidationError) as exc: raise ValueError(f"OpenRouter chat/completions: ungültige Antwort am Schlüsselpfad {_path(exc)}") from exc
                try: content = json.loads(data.choices[0].message.content)
                except json.JSONDecodeError as exc: raise ValueError("OpenRouter chat/completions: ungültige Antwort am Schlüsselpfad choices.0.message.content") from exc
                if not isinstance(content, dict): raise ValueError("OpenRouter chat/completions: Schlüsselpfad choices.0.message.content muss ein JSON-Objekt sein")
                return call_id, content
            except (httpx.TransportError, httpx.HTTPStatusError, ValueError, json.JSONDecodeError):
                if attempt == self.retries: raise
                self.sleep(2 ** attempt); attempt += 1
    def close(self) -> None: self.client.close()


def _path(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return ", ".join(".".join(str(value) for value in item["loc"]) or "<root>" for item in exc.errors(include_input=False))
    return "<json>"
