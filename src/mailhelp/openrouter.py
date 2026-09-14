"""Begrenzter OpenRouter-Client mit Timeouts, Wiederholung und Rate-Limit."""
from __future__ import annotations
import json, time, uuid
from collections import deque
from typing import Any, Callable
import httpx


class RateLimitExceeded(RuntimeError): pass


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
                response.raise_for_status(); data = response.json()
                return call_id, json.loads(data["choices"][0]["message"]["content"])
            except (httpx.TransportError, httpx.HTTPStatusError, KeyError, TypeError, json.JSONDecodeError):
                if attempt == self.retries: raise
                self.sleep(2 ** attempt); attempt += 1
    def close(self) -> None: self.client.close()
