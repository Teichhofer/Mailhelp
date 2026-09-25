"""Begrenzter OpenRouter-Client mit Timeouts, Wiederholung und Rate-Limit."""
from __future__ import annotations
import hashlib, json, time, traceback, uuid
from threading import Lock
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


def _raise_for_status(response: httpx.Response) -> None:
    """Raise with a service-specific, secret-free authentication diagnostic."""
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if response.status_code == 401:
            exc.safe_detail = (
                "OpenRouter: Authentifizierungsfehler "
                "(OPENROUTER_API_KEY wurde abgelehnt)"
            )
        raise


class OpenRouterMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    content: str = Field(min_length=1)


class OpenRouterChoice(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    message: OpenRouterMessage
    finish_reason: str | None = None


class OpenRouterResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    id: str = Field(min_length=1)
    choices: list[OpenRouterChoice] = Field(min_length=1)
    provider: str | None = None


class OpenRouterClient:
    def __init__(self, key: str, timeout: float, retries: int, calls_per_minute: int, transport: httpx.BaseTransport | None = None, sleep: Callable[[float], None] = time.sleep, *, initial_backoff: float = 1, max_backoff: float = 8, clock: Callable[[], float] = time.time, load_calls: Callable[[], list[float]] | None = None, save_calls: Callable[[list[float]], None] | None = None, stopped: Callable[[float], bool] | None = None, logger: EventLogger | None = None):
        self.calls: list[float] = []
        self.key, self.limit, self.clock = key, calls_per_minute, clock
        self.load_calls = load_calls or (lambda: self.calls)
        self.save_calls = save_calls or (lambda calls: self.calls.__setitem__(slice(None), calls))
        self.client = httpx.Client(base_url="https://openrouter.ai/api/v1", timeout=timeout, transport=transport)
        self.logger = logger or NullLogger()
        self._observations: dict[str, dict[str, Any]] = {}
        self._state_lock = Lock()
        wait = stopped or (lambda delay: (sleep(delay), False)[1])
        self.policy = RetryPolicy(retries, initial_backoff, max_backoff, wait, clock)

    def check_access(self) -> None:
        """Validate the API key using a read-only endpoint without an LLM call."""
        def invoke() -> httpx.Response:
            response = self.client.get(
                "/auth/key", headers={"Authorization": f"Bearer {self.key}"},
            )
            _raise_for_status(response)
            return response

        response = self.policy.run(invoke)
        value = response.json()
        if not isinstance(value, dict) or not isinstance(value.get("data"), dict):
            raise ValueError("OpenRouter auth/key: ungültige Antwort am Schlüsselpfad data")

    def complete(self, model: str, parameters: dict[str, Any], system: str,
                 payload: dict[str, Any], *, stage: str = "unknown",
                 retry_type: str = "initial", retry_number: int = 0,
                 provider_preferences: dict[str, Any] | None = None,
                 correlation_id: str | None = None,
                 attempt_id: str | None = None,
                 response_schema: type[BaseModel] | None = None,
                 supports_json_schema: bool = True,
                 revision_route: str = "standard") -> tuple[str, Any]:
        with self._state_lock:
            now = self.clock()
            calls = sorted(value for value in self.load_calls() if isinstance(value, (int, float)) and now - value < 60)
            if len(calls) >= self.limit:
                raise RateLimitExceeded(calls[0] + 60)
            calls.append(now)
            self.save_calls(calls)
        correlation_id = correlation_id or str(uuid.uuid4())
        call_id = attempt_id or str(uuid.uuid4())
        response_format: dict[str, Any] = {"type": "json_object"}
        if response_schema is not None and supports_json_schema:
            response_format = {"type": "json_schema", "json_schema": {
                "name": response_schema.__name__, "strict": True,
                "schema": response_schema.model_json_schema(),
            }}
        request = {**parameters, "model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], "response_format": response_format}
        if provider_preferences is not None:
            request["provider"] = provider_preferences
        started = time.perf_counter()
        fingerprint = hashlib.sha256(json.dumps(request["messages"], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        correlation = _correlation(payload)
        attempt = 0
        metadata = dict(stage=stage, model=model, provider=None, call_id=call_id,
                        correlation_id=correlation_id, attempt_id=call_id,
                        http_status=None, finish_reason=None, content_present=False,
                        content_length=0, json_parse_success=False,
                        schema_validation_success=None, retry_type=retry_type,
                        retry_number=retry_number)
        metadata["revision_route"] = revision_route
        metadata["structured_output"] = response_format["type"]
        def begin(number: int) -> None:
            nonlocal attempt
            attempt = number
            self.logger.llm_event("request_started", request=request,
                                  parameters=parameters, prompt_fingerprint=fingerprint, attempt=number,
                                  status="started", **metadata, **correlation)
        def failed_attempt(number: int, exc: Exception) -> None:
            self.logger.event("WARNING", "openrouter", "retry_failed", attempt=number,
                              error=exc, status=getattr(getattr(exc, "response", None), "status_code", None),
                              **metadata, **correlation)
        def invoke() -> httpx.Response:
            response = self.client.post("/chat/completions", headers={"Authorization": f"Bearer {self.key}", "X-Request-Id": call_id}, json=request)
            _raise_for_status(response)
            return response
        try:
            response = self.policy.run(invoke, begin, failed_attempt)
            try:
                raw = response.json()
            except (ValueError, json.JSONDecodeError) as exc:
                metadata["http_status"] = response.status_code
                self._log_attempt("provider_response_invalid", metadata,
                                  reason="invalid_provider_envelope", retryable=True,
                                  **correlation)
                raise ProviderResponseInvalid("invalid_provider_envelope") from exc
            metadata.update(http_status=response.status_code,
                            provider=raw.get("provider") if isinstance(raw, dict) and isinstance(raw.get("provider"), str) else None)
            reason = _provider_error_reason(raw)
            if reason is not None:
                choice = raw.get("choices", [{}])[0] if isinstance(raw, dict) and isinstance(raw.get("choices"), list) and raw.get("choices") else {}
                if isinstance(choice, dict):
                    metadata["finish_reason"] = choice.get("finish_reason") if isinstance(choice.get("finish_reason"), str) else None
                self._log_attempt("provider_response_invalid", metadata,
                                  reason=reason, retryable=True, **correlation)
                raise ProviderResponseInvalid(reason)
            try: data = OpenRouterResponse.model_validate(raw)
            except (ValueError, ValidationError) as exc:
                self._log_attempt("provider_response_invalid", metadata,
                                  reason="invalid_provider_envelope", retryable=True,
                                  **correlation)
                raise ProviderResponseInvalid("invalid_provider_envelope") from exc
            text = data.choices[0].message.content
            metadata.update(provider=data.provider, finish_reason=data.choices[0].finish_reason,
                            content_present=True, content_length=len(text))
            token_usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else None
            self.logger.llm_event(
                "token_usage_recorded", parameters=parameters,
                prompt_fingerprint=fingerprint, attempt=attempt,
                token_usage=token_usage, token_usage_available=token_usage is not None,
                **metadata, **correlation,
            )
            try: content = json.loads(text)
            except json.JSONDecodeError as exc:
                self._log_attempt("invalid_json", metadata, **correlation)
                raise InvalidJson() from exc
            metadata["json_parse_success"] = True
            with self._state_lock:
                self._observations[call_id] = metadata
            self.logger.llm_event("response_received", response=raw, parameters=parameters,
                                  prompt_fingerprint=fingerprint, duration_ms=round((time.perf_counter() - started) * 1000, 3),
                                  status=response.status_code, attempt=attempt, token_usage=token_usage,
                                  reported_cost=raw.get("cost", raw.get("usage", {}).get("cost") if isinstance(raw.get("usage"), dict) else None),
                                  **metadata, **correlation)
            return call_id, content
        except Exception as exc:
            if not isinstance(exc, (ProviderResponseInvalid, InvalidJson)):
                metadata["http_status"] = getattr(getattr(exc, "response", None), "status_code", None)
                self.logger.llm_event("request_failed", parameters=parameters,
                                      prompt_fingerprint=fingerprint, duration_ms=round((time.perf_counter() - started) * 1000, 3),
                                      status=getattr(getattr(exc, "response", None), "status_code", "error"), attempt=attempt,
                                      error=exc, stacktrace=traceback.format_exc(), **metadata, **correlation)
            raise

    def _log_attempt(self, event: str, metadata: dict[str, Any], **context: Any) -> None:
        self.logger.llm_event(event, **metadata, **context)

    def record_schema_validation(self, *, call_id: str, stage: str, model: str,
                                 success: bool, retry_type: str,
                                 retry_number: int) -> None:
        with self._state_lock:
            metadata = self._observations.pop(call_id)
        metadata["schema_validation_success"] = success
        self._log_attempt("schema_validation_succeeded" if success else "schema_validation_failed",
                          metadata)
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
    # A provider may return a truncated, non-null fragment. It is still a token
    # limit failure and must not be misclassified as repairable JSON.
    if choice.get("finish_reason") == "length":
        return "output_token_limit"
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
