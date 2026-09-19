"""Fachliche LLM-Schritte; jede Ausgabe wird an einem festen Schema validiert."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, TypeVar
import uuid

from pydantic import BaseModel, ValidationError

from .adapter import RetryableError
from .config import LlmRoute, PromptConfig, Topic
from .models import (AbstractCategories, ActionRoute, EventExtraction,
                     MailClassification, Proposal, ProposalStatus, Relevance,
                     Summary, TaskExtraction)
from .openrouter import InvalidJson, ProviderResponseInvalid

T = TypeVar("T", bound=BaseModel)

JSON_REPAIR_INSTRUCTION = (
    "Gib ausschließlich ein syntaktisch gültiges JSON-Objekt aus: doppelte "
    "Anführungszeichen, kein Markdown-Codeblock und kein Begleittext."
)


class LlmSchemaValidationExceeded(ValueError):
    """Die begrenzten Schema-Validierungsversuche sind ausgeschöpft."""

    def __init__(self, step: str):
        self.step = step
        super().__init__(f"LLM-Schemavalidierung für {step} ausgeschöpft")


class LlmProviderResponseInvalid(ValueError):
    def __init__(self, step: str, reason: str):
        self.step, self.reason = step, reason
        super().__init__(f"Ungültige Provider-Antwort für {step}: {reason}")


class LlmInvalidJson(ValueError):
    def __init__(self, step: str):
        self.step = step
        super().__init__(f"Ungültiges JSON für {step}")


class LlmSchemaValidationFailed(LlmSchemaValidationExceeded):
    """Stage-specific final failure after schema validation retries."""


class Completer(Protocol):
    def complete(self, model: str, parameters: dict[str, Any], system: str, payload: dict[str, Any], **metadata: Any) -> tuple[str, Any]: ...


def validate_revision_successor(previous: Proposal, candidate: Any) -> Proposal:
    """Validate both the complete schema and immutable revision identity."""
    revised = Proposal.model_validate(candidate)
    if revised.id != previous.id:
        raise ValueError("Die Vorschlags-ID darf nicht geändert werden")
    if revised.source_mail_id != previous.source_mail_id:
        raise ValueError("Die Ursprungsmail darf nicht geändert werden")
    if revised.version != previous.version + 1:
        raise ValueError("Die Vorschlagsversion muss exakt um eins erhöht werden")
    expected = (ProposalStatus.NEEDS_CLARIFICATION if revised.open_questions
                else ProposalStatus.PENDING_CONFIRMATION)
    if revised.status != expected:
        raise ValueError("Der Vorschlagsstatus widerspricht den offenen Fragen")
    return revised


class Analyzer:
    def __init__(self, client: Completer, prompts: PromptConfig,
                 validation_retries: int = 1, *, provider_retries: int | None = None,
                 json_repair_retries: int | None = None,
                 schema_repair_retries: int | None = None):
        """Create an analyzer with separately bounded retry categories.

        ``validation_retries`` remains as a compatibility default. Explicit category
        limits take precedence and ensure the maximum number of calls is
        ``1 + provider + json + schema``.
        """
        limits = (provider_retries, json_repair_retries, schema_repair_retries)
        if validation_retries < 0 or any(value is not None and value < 0 for value in limits):
            raise ValueError("Retry-Anzahlen dürfen nicht negativ sein")
        self.client, self.prompts = client, prompts
        self.provider_retries = provider_retries
        self.json_repair_retries = validation_retries if json_repair_retries is None else json_repair_retries
        self.schema_repair_retries = validation_retries if schema_repair_retries is None else schema_repair_retries

    def _classified_run(self, step: str, payload: dict[str, Any],
                        validator: Callable[[Any], T]) -> tuple[str, T]:
        """Run one flat, classified retry state machine."""
        routes, prompt, configured_provider_retries = self.prompts.resolved_routes(step)
        same_route_retries = (configured_provider_retries if self.provider_retries is None
                              else self.provider_retries)
        used = {"provider_retry": 0, "json_repair": 0, "schema_repair": 0}
        limits = {"json_repair": self.json_repair_retries,
                  "schema_repair": self.schema_repair_retries}
        repair: str | None = None
        validation_error: Exception | None = None
        route_index = 0
        route_failures = 0
        # One correlation groups the logical stage; every network call receives
        # its own attempt/call ID, which is the persistent call reference.
        correlation_id = str(uuid.uuid4())
        while True:
            route: LlmRoute = routes[route_index]
            request_payload = dict(payload)
            request_prompt = prompt
            if repair == "json_repair":
                request_payload["json_repair_instruction"] = JSON_REPAIR_INSTRUCTION
                # A repair instruction in the JSON payload alone can be mistaken for
                # untrusted mail data.  Keep it there for an explicit audit trail, but
                # also add the authoritative instruction to the system message.
                request_prompt = f"{prompt}\n\n{JSON_REPAIR_INSTRUCTION}"
            elif repair == "schema_repair":
                request_payload["previous_validation_error"] = str(validation_error)
            try:
                retry_type = repair or "initial"
                retry_number = 0 if repair is None else used[repair]
                call_id, raw = self.client.complete(
                    route.model, route.parameters, request_prompt, request_payload, stage=step,
                    retry_type=retry_type, retry_number=retry_number,
                    provider_preferences=route.provider_preferences.model_dump(exclude_none=True),
                    correlation_id=correlation_id,
                )
            except (ProviderResponseInvalid, RetryableError) as exc:
                if route_failures < same_route_retries:
                    route_failures += 1
                    used["provider_retry"] += 1
                    repair = "provider_retry"
                    continue
                if route_index + 1 >= len(routes):
                    reason = exc.reason if isinstance(exc, ProviderResponseInvalid) else "technical_error"
                    raise LlmProviderResponseInvalid(step, reason) from exc
                route_index += 1
                route_failures = 0
                repair = "provider_retry"
                continue
            except InvalidJson as exc:
                if used["json_repair"] >= limits["json_repair"]:
                    raise LlmInvalidJson(step) from exc
                used["json_repair"] += 1
                repair = "json_repair"
                continue
            try:
                result = validator(raw)
            except (ValidationError, ValueError) as exc:
                self._record_schema_result(call_id, step, route.model, False,
                                           retry_type, retry_number)
                validation_error = exc
                if used["schema_repair"] >= limits["schema_repair"]:
                    raise LlmSchemaValidationFailed(step) from exc
                used["schema_repair"] += 1
                repair = "schema_repair"
            else:
                self._record_schema_result(call_id, step, route.model, True,
                                           retry_type, retry_number)
                return call_id, result

    def _record_schema_result(self, call_id: str, stage: str, model: str,
                              success: bool, retry_type: str,
                              retry_number: int) -> None:
        """Complete observability only after the untrusted output was validated."""
        recorder = getattr(self.client, "record_schema_validation", None)
        if callable(recorder):
            recorder(call_id=call_id, stage=stage, model=model, success=success,
                     retry_type=retry_type, retry_number=retry_number)

    def _run(self, step: str, schema: type[T], mail: dict[str, Any],
             extra: dict[str, Any] | None = None) -> tuple[str, T]:
        return self._classified_run(
            step, {"mail": mail, **(extra or {})}, schema.model_validate
        )

    def relevance(self, mail: dict[str, Any], topics: list[Topic]) -> tuple[str, Relevance]:
        enabled = [topic for topic in topics if topic.enabled]
        call_id, result = self._run("relevance", Relevance, mail, {
            "topics": [topic.model_dump() for topic in enabled]
        })
        unknown = set(result.topic_ids) - {topic.id for topic in enabled}
        if unknown:
            raise ValueError(f"LLM lieferte unbekannte Themen-IDs: {sorted(unknown)}")
        if result.decision == "relevant" and not result.topic_ids:
            raise ValueError("Eine relevante Nachricht benötigt mindestens ein Thema")
        return call_id, result

    def summary(self, mail: dict[str, Any]) -> tuple[str, Summary]:
        return self._run("summary", Summary, mail)

    def action_route(self, mail: dict[str, Any]) -> tuple[str, ActionRoute]:
        return self._run("action_router", ActionRoute, mail)

    def extract_tasks(self, mail: dict[str, Any]) -> tuple[str, TaskExtraction]:
        return self._run("task_extraction", TaskExtraction, mail)

    def extract_events(self, mail: dict[str, Any]) -> tuple[str, EventExtraction]:
        return self._run("event_extraction", EventExtraction, mail)

    def revise_proposal(self, proposal: Proposal, question: str,
                        authorized_answer: str) -> tuple[str, Proposal]:
        """Create a fully validated successor from three deliberately separate inputs."""
        payload = {
            "validated_proposal": proposal.model_dump(mode="json"),
            "question": question,
            "authorized_answer": authorized_answer,
        }
        return self._classified_run(
            "proposal_revision", payload,
            lambda raw: validate_revision_successor(proposal, raw),
        )

    def classify_for_learning(self, mail: dict[str, Any]) -> tuple[str, MailClassification]:
        """Freely classify one untrusted mail without using configured topics."""
        return self._run("learning_classification", MailClassification, mail)

    def abstract_learned_categories(
        self, categories: list[MailClassification]
    ) -> tuple[str, AbstractCategories]:
        """Consolidate per-mail suggestions into broader topic candidates."""
        return self._classified_run(
            "learning_abstraction",
            {"classifications": [item.model_dump() for item in categories]},
            AbstractCategories.model_validate,
        )
