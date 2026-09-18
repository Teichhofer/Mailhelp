"""Begrenzter OpenRouter-Client mit Timeouts, Wiederholung und Rate-Limit."""
from __future__ import annotations
import hashlib, json, time, traceback, uuid
from datetime import datetime, timezone
from typing import Any, Callable
import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError


from .adapter import RetryPolicy
from .logging import EventLogger, NullLogger


class RateLimitExceeded(RuntimeError):
    def __init__(self, next_allowed_at: float):
        self.next_allowed_at = next_allowed_at
        super().__init__(f"OpenRouter-Aufruflimit erreicht; naechster Aufruf {datetime.fromtimestamp(next_allowed_at, timezone.utc).isoformat()}")


class OpenRouterResponseError(ValueError):
    """OpenRouter returned a successful HTTP response without usable JSON output."""


class ProviderResponseInvalid(OpenRouterResponseError):
    """The provider envelope is incomplete or structurally invalid."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"OpenRouter chat/completions: provider_response_invalid ({reason})")


class InvalidJson(OpenRouterResponseError):
    """The provider supplied content, but it is not syntactically valid JSON."""

    def __init__(self):
        super().__init__("OpenRouter chat/completions: invalid_json")


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
    def __init__(self, key: str, timeout: float, retries: int, calls_per_minute: int, transport: httpx.BaseTransport | None = None, sleep: Callable[[float], None] = time.sleep, *, initial_backoff: float = 1, max_backoff: float = 8, clock: Callable[[], float] = time.time, load_calls: Callable[[], list[float]] | None = None, save_calls: Callable[[list[float]], None] | None = None, stopped: Callable[[float], bool] | None = None, logger: EventLogger | None = None):
        self.calls: list[float] = []
        self.key, self.limit, self.clock = key, calls_per_minute, clock
        self.load_calls = load_calls or (lambda: self.calls)
        self.save_calls = save_calls or (lambda calls: self.calls.__setitem__(slice(None), calls))
        self.client = httpx.Client(base_url="https://openrouter.ai/api/v1", timeout=timeout, transport=transport)
        self.logger = logger or NullLogger()
        wait = stopped or (lambda delay: (sleep(delay), False)[1])
        self.policy = RetryPolicy(retries, initial_backoff, max_backoff, wait, clock)

    def check_access(self) -> None:
        """Validate the API key using a read-only endpoint without an LLM call."""
        response = self.policy.run(lambda: self.client.get(
            "/auth/key", headers={"Authorization": f"Bearer {self.key}"},
        ))
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict) or not isinstance(value.get("data"), dict):
            raise ValueError("OpenRouter auth/key: ungültige Antwort am Schlüsselpfad data")

    def complete(self, model: str, parameters: dict[str, Any], system: str, payload: dict[str, Any]) -> tuple[str, Any]:
        now = self.clock()
        calls = sorted(value for value in self.load_calls() if isinstance(value, (int, float)) and now - value < 60)
        if len(calls) >= self.limit: raise RateLimitExceeded(calls[0] + 60)
        calls.append(now); self.save_calls(calls); call_id = str(uuid.uuid4())
        request = {**parameters, "model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], "response_format": {"type": "json_object"}}
        started = time.perf_counter()
        fingerprint = hashlib.sha256(json.dumps(request["messages"], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        correlation = _correlation(payload)
        attempt = 0
        def begin(number: int) -> None:
            nonlocal attempt
            attempt = number
            self.logger.llm_event("request_started", request=request, call_id=call_id, model=model,
                                  parameters=parameters, prompt_fingerprint=fingerprint, attempt=number, status="started", **correlation)
        def failed_attempt(number: int, exc: Exception) -> None:
            self.logger.event("WARNING", "openrouter", "retry_failed", call_id=call_id, attempt=number,
                              error=exc, status=getattr(getattr(exc, "response", None), "status_code", None), **correlation)
        def invoke() -> httpx.Response:
            response = self.client.post("/chat/completions", headers={"Authorization": f"Bearer {self.key}", "X-Request-Id": call_id}, json=request)
            response.raise_for_status()
            return response
        try:
            response = self.policy.run(invoke, begin, failed_attempt)
            try:
                raw = response.json()
            except (ValueError, json.JSONDecodeError) as exc:
                raise ProviderResponseInvalid("invalid_provider_envelope") from exc
            reason = _provider_error_reason(raw)
            if reason is not None:
                raise ProviderResponseInvalid(reason)
            try: data = OpenRouterResponse.model_validate(raw)
            except (ValueError, ValidationError) as exc: raise ProviderResponseInvalid("invalid_provider_envelope") from exc
            try: content = json.loads(data.choices[0].message.content)
            except json.JSONDecodeError as exc: raise InvalidJson() from exc
            self.logger.llm_event("response_received", response=raw, call_id=call_id, model=model, parameters=parameters,
                                  prompt_fingerprint=fingerprint, duration_ms=round((time.perf_counter() - started) * 1000, 3),
                                  status=response.status_code, attempt=attempt, token_usage=raw.get("usage"),
                                  reported_cost=raw.get("cost", raw.get("usage", {}).get("cost") if isinstance(raw.get("usage"), dict) else None), **correlation)
            return call_id, content
        except Exception as exc:
            self.logger.llm_event("request_failed", call_id=call_id, model=model, parameters=parameters,
                                  prompt_fingerprint=fingerprint, duration_ms=round((time.perf_counter() - started) * 1000, 3),
                                  status=getattr(getattr(exc, "response", None), "status_code", "error"), attempt=attempt,
                                  error=exc, stacktrace=traceback.format_exc(), **correlation)
            raise
    def close(self) -> None: self.client.close()


def _path(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return ", ".join(".".join(str(value) for value in item["loc"]) or "<root>" for item in exc.errors(include_input=False))
    return "<json>"


def _provider_error_reason(raw: Any) -> str | None:
    """Return a content-free, stable reason for a malformed provider envelope."""
    if not isinstance(raw, dict):
        return "invalid_provider_envelope"
    if "choices" not in raw:
        return "choices_missing"
    choices = raw["choices"]
    if not isinstance(choices, list):
        return "invalid_provider_envelope"
    if not choices:
        return "choice_missing"
    choice = choices[0]
    if not isinstance(choice, dict):
        return "invalid_provider_envelope"
    if "message" not in choice:
        return "message_missing"
    message = choice["message"]
    if not isinstance(message, dict) or "content" not in message:
        return "invalid_provider_envelope"
    content = message["content"]
    if content is None:
        return "message_content_null"
    if isinstance(content, str) and not content.strip():
        return "message_content_empty"
    if not isinstance(content, str):
        return "invalid_provider_envelope"
    return None


def _correlation(payload: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for source, target in (("internal_id", "mail_id"), ("mail_id", "mail_id"), ("source_mail_id", "mail_id"), ("proposal_id", "proposal_id")):
        if source in payload and target not in result:
            result[target] = payload[source]
    return result
