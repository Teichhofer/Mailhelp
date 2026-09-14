"""Fachliche LLM-Schritte; jede Ausgabe wird an einem festen Schema validiert."""
from __future__ import annotations
from typing import Any, Protocol, TypeVar
from pydantic import BaseModel, ValidationError
from .config import PromptConfig, Topic
from .models import Actions, Relevance, Summary

T = TypeVar("T", bound=BaseModel)
class Completer(Protocol):
    def complete(self, model: str, parameters: dict[str, Any], system: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]: ...


class Analyzer:
    def __init__(self, client: Completer, prompts: PromptConfig, validation_retries: int = 1): self.client, self.prompts, self.retries = client, prompts, validation_retries

    def _run(self, step: str, schema: type[T], mail: dict[str, Any], extra: dict[str, Any] | None = None) -> tuple[str, T]:
        model, params, prompt = self.prompts.resolved(step); error = None
        for _ in range(self.retries + 1):
            call_id, raw = self.client.complete(model, params, prompt, {"mail": mail, **(extra or {}), "previous_validation_error": error})
            try: return call_id, schema.model_validate(raw)
            except ValidationError as exc: error = str(exc)
        raise ValueError(f"Ungültige LLM-Ausgabe für {step}: {error}")

    def relevance(self, mail: dict[str, Any], topics: list[Topic]) -> tuple[str, Relevance]:
        enabled = [topic for topic in topics if topic.enabled]
        call_id, result = self._run("relevance", Relevance, mail, {"topics": [topic.model_dump() for topic in enabled]})
        unknown = set(result.topic_ids) - {topic.id for topic in enabled}
        if unknown:
            raise ValueError(f"LLM lieferte unbekannte Themen-IDs: {sorted(unknown)}")
        if result.decision == "relevant" and not result.topic_ids:
            raise ValueError("Eine relevante Nachricht benötigt mindestens ein Thema")
        return call_id, result
    def summary(self, mail: dict[str, Any]) -> tuple[str, Summary]: return self._run("summary", Summary, mail)
    def actions(self, mail: dict[str, Any]) -> tuple[str, Actions]: return self._run("actions", Actions, mail)
