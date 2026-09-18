"""Fachliche LLM-Schritte; jede Ausgabe wird an einem festen Schema validiert."""
from __future__ import annotations
from typing import Any, Protocol, TypeVar
from pydantic import BaseModel, ValidationError
from .config import PromptConfig, Topic
from .models import Actions, Proposal, ProposalStatus, Relevance, Summary
from .openrouter import InvalidJson, ProviderResponseInvalid

T = TypeVar("T", bound=BaseModel)


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
    def complete(self, model: str, parameters: dict[str, Any], system: str, payload: dict[str, Any]) -> tuple[str, Any]: ...


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
    def __init__(self, client: Completer, prompts: PromptConfig, validation_retries: int = 1): self.client, self.prompts, self.retries = client, prompts, validation_retries

    def _run(self, step: str, schema: type[T], mail: dict[str, Any], extra: dict[str, Any] | None = None) -> tuple[str, T]:
        model, params, prompt = self.prompts.resolved(step); error = None
        validation_error: ValidationError | None = None
        for _ in range(self.retries + 1):
            try:
                call_id, raw = self.client.complete(model, params, prompt, {"mail": mail, **(extra or {}), "previous_validation_error": error})
            except ProviderResponseInvalid as exc:
                raise LlmProviderResponseInvalid(step, exc.reason) from exc
            except InvalidJson as exc:
                raise LlmInvalidJson(step) from exc
            try: return call_id, schema.model_validate(raw)
            except ValidationError as exc:
                validation_error = exc
                error = str(exc)
        raise LlmSchemaValidationFailed(step) from validation_error

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

    def revise_proposal(self, proposal: Proposal, question: str, authorized_answer: str) -> tuple[str, Proposal]:
        """Create a fully validated successor from three deliberately separate inputs."""
        model, params, prompt = self.prompts.resolved("proposal_revision")
        error: str | None = None
        validation_error: Exception | None = None
        payload = {
            "validated_proposal": proposal.model_dump(mode="json"),
            "question": question,
            "authorized_answer": authorized_answer,
        }
        for _ in range(self.retries + 1):
            try:
                call_id, raw = self.client.complete(
                    model, params, prompt, {**payload, "previous_validation_error": error}
                )
            except ProviderResponseInvalid as exc:
                raise LlmProviderResponseInvalid("proposal_revision", exc.reason) from exc
            except InvalidJson as exc:
                raise LlmInvalidJson("proposal_revision") from exc
            try:
                revised = validate_revision_successor(proposal, raw)
                return call_id, revised
            except (ValidationError, ValueError) as exc:
                validation_error = exc
                error = str(exc)
        raise LlmSchemaValidationFailed("proposal_revision") from validation_error
