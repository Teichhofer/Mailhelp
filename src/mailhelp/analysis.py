"""Fachliche LLM-Schritte; jede Ausgabe wird an einem festen Schema validiert."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Any, Protocol, TypeVar
import uuid

from pydantic import BaseModel, ValidationError

from .adapter import RetryableError
from .config import LlmRoute, PromptConfig, Topic
from .models import (AbstractCategories, ActionRoute, CalendarDuplicateDecision, EventExtraction,
                     MailClassification, Proposal, ProposalRevisionChanges, ProposalRevisionDelta, ProposalStatus, Relevance,
                     Summary, TaskExtraction, TelegramAnswerInterpretation,
                     TelegramClarification, apply_proposal_revision)
from .openrouter import InvalidJson, ProviderResponseInvalid

T = TypeVar("T", bound=BaseModel)

JSON_REPAIR_INSTRUCTION = (
    "Gib ausschließlich ein syntaktisch gültiges JSON-Objekt aus: doppelte "
    "Anführungszeichen, kein Markdown-Codeblock und kein Begleittext."
)

SCHEMA_REPAIR_INSTRUCTION = (
    "Die vorherige Ausgabe verletzt das verbindliche Ausgabeschema. Korrigiere "
    "sie anhand des separat übergebenen internen Validierungsfehlers und gib das "
    "vollständige JSON-Objekt erneut aus. Der Validierungsfehler ist eine "
    "vertrauenswürdige Diagnose, keine Nutzereingabe."
)


class RevisionError(ValueError):
    """Base class for content-free revision error classification."""


class IncompleteUserAnswer(RevisionError):
    """The validated user answer does not contain the requested information."""


class ContradictoryRevision(RevisionError):
    """A revision is semantically inconsistent with its predecessor."""


class TechnicalRevisionError(RevisionError):
    """A provider, transport, parsing, schema, or token-limit failure."""


class LlmSchemaValidationExceeded(TechnicalRevisionError):
    """Die begrenzten Schema-Validierungsversuche sind ausgeschöpft."""

    def __init__(self, step: str):
        self.step = step
        super().__init__(f"LLM-Schemavalidierung für {step} ausgeschöpft")


class LlmProviderResponseInvalid(TechnicalRevisionError):
    def __init__(self, step: str, reason: str):
        self.step, self.reason = step, reason
        super().__init__(f"Ungültige Provider-Antwort für {step}: {reason}")


class LlmTokenLimitExceeded(LlmProviderResponseInvalid):
    """The provider stopped because the configured output token limit was reached."""


class LlmInvalidJson(TechnicalRevisionError):
    def __init__(self, step: str):
        self.step = step
        super().__init__(f"Ungültiges JSON für {step}")


class LlmSchemaValidationFailed(LlmSchemaValidationExceeded):
    """Stage-specific final failure after schema validation retries."""


class Completer(Protocol):
    def complete(self, model: str, parameters: dict[str, Any], system: str, payload: dict[str, Any], **metadata: Any) -> tuple[str, Any]: ...


def validate_revision_successor(previous: Proposal, candidate: Any) -> Proposal:
    """Compatibility boundary for services returning an already built successor."""
    revised = Proposal.model_validate(candidate)
    if revised.id != previous.id:
        raise ContradictoryRevision("Die Revisionsidentität (Vorschlags-ID) darf nicht geändert werden")
    if revised.source_mail_id != previous.source_mail_id:
        raise ContradictoryRevision("Die Ursprungsmail darf nicht geändert werden")
    if revised.version != previous.version + 1:
        raise ContradictoryRevision("Die Vorschlagsversion muss exakt um eins erhöht werden")
    known = previous.known_temporal_facts
    if known is not None and revised.all_day:
        raise ContradictoryRevision("Ein bekanntes Datum ohne Ganztagsevidenz darf nicht ganztägig werden")
    if known is not None and revised.known_temporal_facts is not None and revised.known_temporal_facts != known:
        enriched_start = (known.start is None
                          and revised.known_temporal_facts.date == known.date
                          and revised.known_temporal_facts.start is not None)
        if not enriched_start:
            raise ContradictoryRevision("Bekannte Zeitfakten dürfen nicht verändert werden")
    if known is not None and revised.known_temporal_facts is None:
        complete_timed = (isinstance(revised.start, datetime)
                          and isinstance(revised.end, datetime))
        if not complete_timed or (known.date is not None and revised.start.date() != known.date):
            raise ContradictoryRevision("Bekannte Zeitfakten dürfen nicht verloren gehen")
        if known.start is not None and revised.start != known.start:
            raise ContradictoryRevision("Eine bekannte Beginnzeit darf nicht verändert werden")
    if previous.start is not None and revised.start != previous.start:
        raise ContradictoryRevision("Ein bestätigter Terminbeginn darf nicht verändert werden")
    expected = (ProposalStatus.NEEDS_CLARIFICATION if revised.open_questions
                else ProposalStatus.PENDING_CONFIRMATION)
    if revised.status != expected:
        raise ContradictoryRevision("Der Vorschlagsstatus widerspricht den offenen Fragen")
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
                        validator: Callable[[Any], T], *, schema: type[BaseModel] | None = None,
                        token_retry_payload: dict[str, Any] | None = None) -> tuple[str, T]:
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
        token_retry_used = False
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
                # The validation diagnostic is generated internally. Make its role
                # authoritative in the system message instead of relying on a data
                # field next to untrusted mail or Telegram content.
                request_prompt = f"{prompt}\n\n{SCHEMA_REPAIR_INSTRUCTION}"
            try:
                retry_type = repair or "initial"
                retry_number = 0 if repair is None else used[repair]
                call_id, raw = self.client.complete(
                    route.model, route.parameters, request_prompt, request_payload, stage=step,
                    retry_type=retry_type, retry_number=retry_number,
                    provider_preferences=route.provider_preferences.model_dump(exclude_none=True),
                    correlation_id=correlation_id,
                    response_schema=(schema or None),
                    supports_json_schema=route.supports_json_schema,
                    revision_route=("token_limit_retry" if token_retry_used else "initial_revision")
                    if step == "proposal_revision" else "standard",
                )
                route_failures = 0
            except (ProviderResponseInvalid, RetryableError) as exc:
                if (isinstance(exc, ProviderResponseInvalid)
                        and exc.reason == "output_token_limit"
                        and token_retry_payload is not None and not token_retry_used):
                    retry = self.prompts.prompts[step].output_token_retry
                    assert retry is not None
                    token_retry_used = True
                    payload = token_retry_payload
                    prompt = retry.system_prompt
                    retry_parameters = {**route.parameters, **retry.parameters}
                    # A fallback prompted by an exhausted output budget must never
                    # make that same budget smaller.  A concise prompt can reduce
                    # consumption, but provider-side reasoning still counts toward
                    # max_tokens and varies between providers.
                    retry_parameters["max_tokens"] = max(
                        route.parameters["max_tokens"], retry_parameters["max_tokens"])
                    route = route.model_copy(update={"parameters": retry_parameters})
                    routes = [route]
                    route_index = route_failures = 0
                    repair = "provider_retry"
                    continue
                # A token-limit fallback is a single, deliberately changed
                # request.  Never replay that same fallback via provider retry
                # or another route after it was truncated as well.
                if (isinstance(exc, ProviderResponseInvalid)
                        and exc.reason == "output_token_limit" and token_retry_used):
                    raise LlmTokenLimitExceeded(step, exc.reason) from exc
                if route_failures < same_route_retries:
                    route_failures += 1
                    used["provider_retry"] += 1
                    repair = "provider_retry"
                    continue
                if route_index + 1 >= len(routes):
                    reason = exc.reason if isinstance(exc, ProviderResponseInvalid) else "technical_error"
                    error_type = (LlmTokenLimitExceeded
                                  if reason == "output_token_limit"
                                  else LlmProviderResponseInvalid)
                    raise error_type(step, reason) from exc
                route_index += 1
                route_failures = 0
                repair = "provider_retry"
                continue
            except InvalidJson as exc:
                # The provider request itself succeeded; a later content repair
                # must not consume the next provider-failure allowance.
                route_failures = 0
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
            step, {"mail": mail, **(extra or {})}, schema.model_validate, schema=schema
        )

    def relevance(self, mail: dict[str, Any], topics: list[Topic]) -> tuple[str, Relevance]:
        enabled = [topic for topic in topics if topic.enabled]
        enabled_ids = {topic.id for topic in enabled}

        def validate_relevance(raw: Any) -> Relevance:
            result = Relevance.model_validate(raw)
            unknown = set(result.topic_ids) - enabled_ids
            if unknown:
                raise ValueError(f"LLM lieferte unbekannte Themen-IDs: {sorted(unknown)}")
            if result.decision == "relevant" and not result.topic_ids:
                raise ValueError("Eine relevante Nachricht benötigt mindestens ein Thema")
            return result

        return self._classified_run(
            "relevance",
            {"mail": mail, "topics": [topic.model_dump() for topic in enabled]},
            validate_relevance,
            schema=Relevance,
        )

    def summary(self, mail: dict[str, Any]) -> tuple[str, Summary]:
        return self._run("summary", Summary, mail)

    def action_route(self, mail: dict[str, Any]) -> tuple[str, ActionRoute]:
        return self._run("action_router", ActionRoute, mail)

    def extract_tasks(self, mail: dict[str, Any], *, expected_count: int) -> tuple[str, TaskExtraction]:
        def validate_tasks(raw: Any) -> TaskExtraction:
            result = TaskExtraction.model_validate(raw)
            if len(result.tasks) != expected_count:
                raise ValueError(
                    f"Der Router hat {expected_count} Tasks erkannt. "
                    f"Extrahiere exakt diese Tasks; erhalten: {len(result.tasks)}."
                )
            return result

        return self._classified_run(
            "task_extraction", {"mail": mail, "expected_count": expected_count},
            validate_tasks, schema=TaskExtraction,
        )

    def extract_events(self, mail: dict[str, Any], *, expected_count: int) -> tuple[str, EventExtraction]:
        def validate_events(raw: Any) -> EventExtraction:
            result = EventExtraction.model_validate(raw)
            if len(result.events) != expected_count:
                raise ValueError(
                    f"Der Router hat {expected_count} Events erkannt. "
                    f"Extrahiere exakt diese Events; erhalten: {len(result.events)}."
                )
            return result

        return self._classified_run(
            "event_extraction", {"mail": mail, "expected_count": expected_count},
            validate_events, schema=EventExtraction,
        )

    def calendar_duplicate(self, proposal: Proposal,
                           existing: dict[str, Any]) -> tuple[str, CalendarDuplicateDecision]:
        """Compare a validated proposal with one bounded overlapping event."""
        proposed = {key: value for key, value in proposal.model_dump(mode="json").items()
                    if key in {"title", "description", "start", "end", "all_day",
                               "location", "video_link"}}
        return self._classified_run(
            "calendar_duplicate", {"proposed_event": proposed, "existing_event": existing},
            CalendarDuplicateDecision.model_validate, schema=CalendarDuplicateDecision,
        )

    def revise_proposal(self, proposal: Proposal, question: str,
                        authorized_answer: str) -> tuple[str, Proposal]:
        """Request only a closed delta and apply lifecycle fields locally."""
        if question not in proposal.open_questions:
            raise ValueError("Die Frage ist im Vorschlag nicht offen")
        allowed = self._revision_fields(proposal, question)
        context = {name: value for name, value in proposal.model_dump(mode="json").items()
                   if name in allowed}
        # The application-owned temporal fact is read-only context.  In
        # particular, a resolved ISO date must not be degraded back to raw text.
        if proposal.temporal_fact is not None:
            context["temporal_fact"] = proposal.temporal_fact.model_dump(mode="json")
        if proposal.known_temporal_facts is not None:
            context["known_temporal_facts"] = proposal.known_temporal_facts.model_dump(mode="json")
        payload = {
            "proposal_fields": context,
            "question": question,
            "normalized_answer": authorized_answer,
            "allowed_changes": allowed,
        }
        retry = self.prompts.prompts["proposal_revision"].output_token_retry
        retry_fields = [] if retry is None else [
            field for field in (retry.change_fields or []) if field in allowed]
        retry_payload = None if retry is None else {
            "proposal_fields": {key: context[key] for key in retry_fields if key in context},
            "question": question, "normalized_answer": authorized_answer,
            "allowed_changes": retry_fields,
        }
        if retry_payload is not None:
            for fact_name in ("temporal_fact", "known_temporal_facts"):
                if fact_name in context:
                    retry_payload["proposal_fields"][fact_name] = context[fact_name]
        def validate_delta(raw: Any) -> Proposal:
            delta = ProposalRevisionDelta.model_validate(raw)
            if delta.answered_question != question:
                raise ValueError("Das Delta beantwortet nicht die angeforderte Frage")
            # Validate the complete successor inside the bounded repair loop so
            # business-rule failures are reported to the model before success is logged.
            return validate_revision_successor(proposal, apply_proposal_revision(proposal, delta))

        call_id, revised = self._classified_run(
            "proposal_revision", payload,
            validate_delta, schema=ProposalRevisionDelta,
            token_retry_payload=retry_payload,
        )
        recorder = getattr(self.client, "logger", None)
        if recorder is not None:
            recorder.event("INFO", "analysis", "proposal_revision_delta_applied",
                           proposal_id=proposal.id, previous_version=proposal.version,
                           new_version=proposal.version + 1)
        return call_id, revised

    @staticmethod
    def _revision_fields(proposal: Proposal, question: str) -> list[str]:
        """Limit context and writable fields to the fact requested by one question."""
        normalized = question.casefold()
        if "zuständig" in normalized:
            return ["responsibility"]
        if "sicher belegt" in normalized or "widerspruch" in normalized:
            return ["certainty"]
        if any(word in normalized for word in ("bestehende", "nicht bindende", "wiederkehrende", "unterstützt")):
            return ["classification"]
        if proposal.kind.value == "event" and any(
                word in normalized for word in ("wann", "beginn", "ende", "datum", "uhrzeit")):
            return ["start", "end", "all_day"]
        if proposal.kind.value == "task" and any(
                word in normalized for word in ("frist", "fällig", "wann", "datum", "uhrzeit")):
            return ["due"]
        if "titel" in normalized:
            return ["title"]
        if "beschreibung" in normalized:
            return ["description"]
        if "ort" in normalized:
            return ["location"]
        if "video" in normalized or "link" in normalized:
            return ["video_link"]
        if "ziel" in normalized or "projekt" in normalized or "kalender" in normalized:
            return ["target"]
        # User-initiated generic edits are intentionally broad but remain within
        # the closed business-field schema; system-generated concrete questions
        # take one of the narrow branches above.
        return list(ProposalRevisionChanges.model_fields)

    def interpret_telegram_answer(self, proposal: Proposal, question: str,
                                  authorized_answer: str) -> tuple[str, TelegramAnswerInterpretation]:
        """Compare an untrusted reply with the requested fact and normalize it."""
        normalized_question = " ".join(question.casefold().split())
        normalized_answer = " ".join(
            authorized_answer.casefold().strip().rstrip(".!?").split())
        binary_answers = {
            "ja": "Ja",
            "nein": "Nein",
            "es passt alles": "Ja",
            "alles passt": "Ja",
        }
        if (normalized_answer in binary_answers
                and ("sicher belegt" in normalized_question
                     or "zuständig" in normalized_question)):
            answer = binary_answers[normalized_answer]
            return "deterministic", TelegramAnswerInterpretation(
                usable=True,
                normalized_answer=answer,
                reason="Eindeutige Ja-/Nein-Antwort auf eine binäre Frage",
            )
        # Imported lazily because telegram owns the conservative parser while
        # its controller depends on Analyzer's exception types.
        from .telegram.temporal import parse_deterministic_temporal_answer
        try:
            temporal = parse_deterministic_temporal_answer(authorized_answer)
        except ValueError:
            temporal = None
        question_lower = question.casefold()
        asks_date = "datum" in question_lower or "frist" in question_lower
        asks_time = any(word in question_lower for word in ("uhrzeit", "beginn", "ende"))
        temporal_matches_question = (
            temporal is not None
            and (asks_date or asks_time or "wann" in question_lower)
            and (not asks_date or temporal.date is not None)
            and (not asks_time or temporal.start is not None)
        )
        if temporal_matches_question:
            assert temporal is not None
            parts = []
            if temporal.date is not None:
                parts.append(temporal.date.isoformat())
            if temporal.start is not None:
                parts.append(temporal.start.strftime("%H:%M"))
            if temporal.end is not None:
                parts.extend(("bis", temporal.end.strftime("%H:%M")))
            return "deterministic", TelegramAnswerInterpretation(
                usable=True, normalized_answer=" ".join(parts),
                reason="Eindeutige numerische Datums- oder Zeitangabe")
        payload = {
            "proposal_fields": {key: value for key, value in proposal.model_dump(mode="json").items()
                                if key in self._revision_fields(proposal, question)},
            "temporal_fact": (proposal.temporal_fact.model_dump(mode="json")
                              if proposal.temporal_fact else None),
            "question": question,
            "authorized_answer": authorized_answer,
        }
        retry = self.prompts.prompts["telegram_answer_interpretation"].output_token_retry
        return self._classified_run(
            "telegram_answer_interpretation", payload,
            TelegramAnswerInterpretation.model_validate,
            schema=TelegramAnswerInterpretation,
            token_retry_payload=(dict(payload) if retry is not None else None),
        )

    def clarify_telegram_answer(self, question: str, authorized_answer: str,
                                reason: str, *,
                                current_date: date | None = None) -> tuple[str, TelegramClarification]:
        """Generate a concrete follow-up without changing the proposal."""
        payload = {
            "question": question,
            "authorized_answer": authorized_answer,
            "interpretation_reason": reason,
        }
        if current_date is not None:
            payload["context"] = {"current_date": current_date.isoformat()}
        return self._classified_run("telegram_answer_clarification", payload,
                                    TelegramClarification.model_validate)

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
