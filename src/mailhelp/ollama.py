"""Experimental local LLM backend: a Ollama server instead of OpenRouter.

``OllamaClient`` reuses the complete OpenRouter request flow (budget, retries,
logging, JSON and schema validation) and only translates the protocol: the
OpenAI-style request becomes a native ``/api/chat`` request with the JSON
schema as ``format``, and the native answer is mapped back to the
OpenAI-compatible envelope.  Every stage uses the one configured local model;
OpenRouter models, provider preferences and reasoning settings do not apply.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
from typing import Any

import httpx

from .openrouter import OpenRouterClient

# OpenRouter request parameters with a direct counterpart in Ollama ``options``.
_OPTION_NAMES = {
    "temperature": "temperature", "max_tokens": "num_predict", "top_p": "top_p",
    "top_k": "top_k", "min_p": "min_p", "seed": "seed", "stop": "stop",
    "frequency_penalty": "frequency_penalty", "presence_penalty": "presence_penalty",
    "repetition_penalty": "repeat_penalty",
}
_HOSTNAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")


@dataclass(frozen=True)
class LocalLlm:
    """Address and model of the experimental local Ollama server."""

    host: str
    port: int
    model: str
    num_ctx: int = 16384

    @property
    def base_url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}"


def parse_address(value: str) -> tuple[str, int]:
    """Parse ``HOST:PORT``; IPv6 addresses need brackets, e.g. ``[::1]:11434``."""
    host, separator, port = value.strip().rpartition(":")
    if not separator or not host:
        raise ValueError("Adresse als HOST:PORT angeben, z. B. 192.168.1.20:11434")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
        try:
            ipaddress.IPv6Address(host)
        except ValueError as exc:
            raise ValueError("ungültige IPv6-Adresse") from exc
    elif ":" in host:
        raise ValueError("IPv6-Adressen in eckigen Klammern angeben, z. B. [::1]:11434")
    elif not _HOSTNAME.fullmatch(host):
        raise ValueError("ungültiger Hostname oder ungültige IP-Adresse")
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("Port muss eine Zahl von 1 bis 65535 sein")
    return host, int(port)


class OllamaClient(OpenRouterClient):
    service_name = "Ollama (lokal, experimentell)"
    endpoint = "/api/chat"

    def __init__(self, local: LocalLlm, timeout: float, retries: int,
                 calls_per_minute: int, **kwargs: Any):
        super().__init__("", timeout, retries, calls_per_minute,
                         base_url=local.base_url, **kwargs)
        self.model, self.num_ctx = local.model, local.num_ctx

    def _resolve_model(self, model: str) -> str:
        return self.model

    def _headers(self, call_id: str) -> dict[str, str]:
        # A local server needs no credentials; never send the OpenRouter key.
        return {"X-Request-Id": call_id}

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            exc.safe_detail = f"Ollama: HTTP {response.status_code}" + (
                " (Modell auf dem Ollama-Server nicht gefunden)"
                if response.status_code == 404 else "")
            raise

    def _prepare_request(self, request: dict[str, Any]) -> dict[str, Any]:
        response_format = request["response_format"]
        options: dict[str, Any] = {"num_ctx": self.num_ctx}
        options.update({target: request[source] for source, target in _OPTION_NAMES.items()
                        if source in request})
        return {
            "model": request["model"],
            "messages": request["messages"],
            "stream": False,
            "format": (response_format["json_schema"]["schema"]
                       if response_format["type"] == "json_schema" else "json"),
            "options": options,
        }

    @staticmethod
    def _envelope(raw: Any) -> Any:
        if not isinstance(raw, dict) or not isinstance(raw.get("message"), dict):
            # Left unchanged, the shared validation reports an invalid envelope.
            return raw
        done_reason = raw.get("done_reason")
        created = raw.get("created_at")
        return {
            "id": f"ollama-{created}" if isinstance(created, str) and created else "ollama-response",
            "provider": "ollama",
            "choices": [{
                "message": raw["message"],
                "finish_reason": done_reason if isinstance(done_reason, str) else None,
            }],
            "usage": {target: raw[source] for target, source in (
                ("prompt_tokens", "prompt_eval_count"), ("completion_tokens", "eval_count"))
                if isinstance(raw.get(source), int)},
        }

    def check_access(self) -> None:
        """Check that the server answers and the configured model is installed."""
        def invoke() -> httpx.Response:
            response = self.client.get("/api/tags")
            self._raise_for_status(response)
            return response

        value = self.policy.run(invoke).json()
        models = value.get("models") if isinstance(value, dict) else None
        if not isinstance(models, list):
            raise ValueError("Ollama /api/tags: ungültige Antwort am Schlüsselpfad models")
        names = {item.get(key) for item in models if isinstance(item, dict)
                 for key in ("name", "model")}
        if self.model not in names and f"{self.model}:latest" not in names:
            raise ValueError(f"Ollama: Modell {self.model!r} ist nicht installiert "
                             f"(auf dem Server 'ollama pull {self.model}' ausführen)")


__all__ = ["LocalLlm", "OllamaClient", "parse_address"]
