"""Fachliche LLM-Schritte; jede Ausgabe wird an einem festen Schema validiert."""
from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from datetime import date, datetime
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from .adapter import RetryableError
from .config import LlmRoute, PromptConfig, Topic
from .domain.prepared import PreparedAttachment
from .domain.revision_errors import ContradictoryRevision, TechnicalRevisionError
from .models import (
    AbstractCategories,
    ActionRoute,
    CalendarDuplicateDecision,
    EventExtraction,
    MailClassification,
    Proposal,
    ProposalRevisionChanges,
    ProposalRevisionDelta,
    ProposalStatus,
    Relevance,
    Summary,
    TaskExtraction,
    TelegramAnswerInterpretation,
    TelegramClarification,
    VisionExtractionResult,
    apply_proposal_revision,
)
from .openrouter import InvalidJson, ProviderResponseInvalid
from .temporal_answers import parse_deterministic_temporal_answer

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
    def complete(self, model: str, parameters: dict[str, Any], system: str,
                 payload: dict[str, Any], *, stage: str = ...,
                 retry_type: str = ..., retry_number: int = ...,
                 provider_preferences: dict[str, Any] | None = ...,
                 correlation_id: str | None = ...,
                 attempt_id: str | None = ...,
                 response_schema: type[BaseModel] | None = ...,
                 supports_json_schema: bool = ...,
                 revision_route: str = ...,
                 images: list[str] | None = ...) -> tuple[str, Any]:
        """Return the call id and the parsed JSON answer."""


def validate_revision_successor(previous: Proposal, candidate: Any, *,
                                allow_all_day_resolution: bool = False) -> Proposal:
    """Compatibility boundary for services returning an already built successor."""
    revised = Proposal.model_validate(candidate)
    if revised.id != previous.id:
        raise ContradictoryRevision("Die Revisionsidentität (Vorschlags-ID) darf nicht geändert werden")
    if revised.source_mail_id != previous.source_mail_id:
        raise ContradictoryRevision("Die Ursprungsmail darf nicht geändert werden")
    if revised.version != previous.version + 1:
        raise ContradictoryRevision("Die Vorschlagsversion muss exakt um eins erhöht werden")
    if revised.explicit_duplicate_create_confirmed_version is not None:
        raise ContradictoryRevision("Eine Revision darf keine Doppelanlage freigeben")
    for field in ("sources", "protected_fields", "canonical_ref", "target_provider", "matching_candidates",
                  "pending_sources", "merge_review_required", "end_origin", "default_duration_minutes", "meeting_mode",
                  "separated_from", "duplicate_check_failed"):
        if getattr(previous, field) != getattr(revised, field):
            raise ContradictoryRevision("Eine KI-Revision darf Abgleich- oder Herkunftsfelder nicht ändern")
    known = previous.known_temporal_facts
    resolved_all_day = (
        known is not None
        and allow_all_day_resolution
        and revised.all_day
        and isinstance(revised.start, date)
        and not isinstance(revised.start, datetime)
        and known.date == revised.start
        and known.start is None
        and known.start_time is None
    )
    if known is not None and revised.all_day and not resolved_all_day:
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
        start_day = revised.start.date() if isinstance(revised.start, datetime) else None
        if (not complete_timed and not resolved_all_day) or (
            complete_timed and known.date is not None and start_day != known.date
        ):
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


class ClassifiedRun:
    """One flat, classified retry state machine for a single analysis step.

    Provider failures, invalid JSON and schema violations are retried separately,
    each within its own limit; the state lives here instead of in loop variables.
    """

    def __init__(self, analyzer: Analyzer, step: str, payload: dict[str, Any],
                 validator: Callable[[Any], Any], schema: type[BaseModel] | None,
                 token_retry_payload: dict[str, Any] | None, images: list[str] | None):
        self.client, self.prompts = analyzer.client, analyzer.prompts
        self.step, self.payload, self.validator, self.schema = step, payload, validator, schema
        self.token_retry_payload, self.images = token_retry_payload, images
        self.routes, self.prompt, configured_provider_retries = self.prompts.resolved_routes(step)
        self.same_route_retries = (configured_provider_retries if analyzer.provider_retries is None
                                   else analyzer.provider_retries)
        self.used = {"provider_retry": 0, "json_repair": 0, "schema_repair": 0}
        self.limits = {"json_repair": analyzer.json_repair_retries,
                       "schema_repair": analyzer.schema_repair_retries}
        self.repair: str | None = None
        self.validation_error: Exception | None = None
        self.route_index = 0
        self.route_failures = 0
        self.token_retry_used = False
        # One correlation groups the logical stage; every network call receives
        # its own attempt/call ID, which is the persistent call reference.
        self.correlation_id = str(uuid.uuid4())

    def run(self) -> tuple[str, Any]:
        while True:
            route: LlmRoute = self.routes[self.route_index]
            retry_type = self.repair or "initial"
            retry_number = 0 if self.repair is None else self.used[self.repair]
            try:
                call_id, raw = self._complete(route, retry_type, retry_number)
                self.route_failures = 0
            except (ProviderResponseInvalid, RetryableError) as exc:
                self._provider_failed(exc, route)
                continue
            except InvalidJson as exc:
                # The provider request itself succeeded; a later content repair
                # must not consume the next provider-failure allowance.
                self.route_failures = 0
                if self.used["json_repair"] >= self.limits["json_repair"]:
                    raise LlmInvalidJson(self.step) from exc
                self.used["json_repair"] += 1
                self.repair = "json_repair"
                continue
            try:
                result = self.validator(raw)
            except (ValidationError, ValueError) as exc:
                self._record_schema_result(call_id, route.model, False, retry_type, retry_number)
                self.validation_error = exc
                if self.used["schema_repair"] >= self.limits["schema_repair"]:
                    raise LlmSchemaValidationFailed(self.step) from exc
                self.used["schema_repair"] += 1
                self.repair = "schema_repair"
            else:
                self._record_schema_result(call_id, route.model, True, retry_type, retry_number)
                return call_id, result

    def _complete(self, route: LlmRoute, retry_type: str, retry_number: int) -> tuple[str, Any]:
        request_payload = dict(self.payload)
        request_prompt = self.prompt
        if self.repair == "json_repair":
            request_payload["json_repair_instruction"] = JSON_REPAIR_INSTRUCTION
            # A repair instruction in the JSON payload alone can be mistaken for
            # untrusted mail data.  Keep it there for an explicit audit trail, but
            # also add the authoritative instruction to the system message.
            request_prompt = f"{self.prompt}\n\n{JSON_REPAIR_INSTRUCTION}"
        elif self.repair == "schema_repair":
            request_payload["previous_validation_error"] = str(self.validation_error)
            # The validation diagnostic is generated internally. Make its role
            # authoritative in the system message instead of relying on a data
            # field next to untrusted mail or Telegram content.
            request_prompt = f"{self.prompt}\n\n{SCHEMA_REPAIR_INSTRUCTION}"
        return self.client.complete(
            route.model, route.parameters, request_prompt, request_payload, stage=self.step,
            retry_type=retry_type, retry_number=retry_number,
            provider_preferences=route.provider_preferences.model_dump(exclude_none=True),
            correlation_id=self.correlation_id,
            response_schema=(self.schema or None),
            supports_json_schema=route.supports_json_schema,
            revision_route=("token_limit_retry" if self.token_retry_used else "initial_revision")
            if self.step == "proposal_revision" else "standard",
            **self._image_arguments(),
        )

    def _image_arguments(self) -> dict[str, Any]:
        # Only vision steps pass images; other completers need not know the parameter.
        return {"images": self.images} if self.images else {}

    def _provider_failed(self, exc: Exception, route: LlmRoute) -> None:
        """Choose the next attempt after a provider failure, or raise when none is left."""
        if (isinstance(exc, ProviderResponseInvalid)
                and exc.reason == "output_token_limit"
                and self.token_retry_payload is not None and not self.token_retry_used):
            retry = self.prompts.prompts[self.step].output_token_retry
            assert retry is not None
            self.token_retry_used = True
            self.payload = self.token_retry_payload
            self.prompt = retry.system_prompt
            retry_parameters = {**route.parameters, **retry.parameters}
            # A fallback prompted by an exhausted output budget must never
            # make that same budget smaller.  A concise prompt can reduce
            # consumption, but provider-side reasoning still counts toward
            # max_tokens and varies between providers.
            retry_parameters["max_tokens"] = max(
                route.parameters["max_tokens"], retry_parameters["max_tokens"])
            route = route.model_copy(update={"parameters": retry_parameters})
            self.routes = [route]
            self.route_index = self.route_failures = 0
            self.repair = "provider_retry"
            return
        # A token-limit fallback is a single, deliberately changed
        # request.  Never replay that same fallback via provider retry
        # or another route after it was truncated as well.
        if (isinstance(exc, ProviderResponseInvalid)
                and exc.reason == "output_token_limit" and self.token_retry_used):
            raise LlmTokenLimitExceeded(self.step, exc.reason) from exc
        if self.route_failures < self.same_route_retries:
            self.route_failures += 1
            self.used["provider_retry"] += 1
            self.repair = "provider_retry"
            return
        if self.route_index + 1 >= len(self.routes):
            reason = exc.reason if isinstance(exc, ProviderResponseInvalid) else "technical_error"
            error_type = (LlmTokenLimitExceeded
                          if reason == "output_token_limit"
                          else LlmProviderResponseInvalid)
            raise error_type(self.step, reason) from exc
        self.route_index += 1
        self.route_failures = 0
        self.repair = "provider_retry"

    def _record_schema_result(self, call_id: str, model: str, success: bool, retry_type: str,
                              retry_number: int) -> None:
        """Complete observability only after the untrusted output was validated."""
        recorder = getattr(self.client, "record_schema_validation", None)
        if callable(recorder):
            recorder(call_id=call_id, stage=self.step, model=model, success=success,
                     retry_type=retry_type, retry_number=retry_number)


class Analyzer:
    last_relevance_source: str = "OpenRouter"

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
                        token_retry_payload: dict[str, Any] | None = None,
                        images: list[str] | None = None) -> tuple[str, T]:
        """Run one flat, classified retry state machine."""
        return ClassifiedRun(self, step, payload, validator, schema, token_retry_payload, images).run()

    def _run(self, step: str, schema: type[T], mail: dict[str, Any],
             extra: dict[str, Any] | None = None) -> tuple[str, T]:
        return self._classified_run(
            step, {"mail": mail, **(extra or {})}, schema.model_validate, schema=schema
        )

    def suspicious_link_bait(self, mail: dict[str, Any]) -> bool:
        """Conservative, local heuristic; never resolve or visit untrusted URLs."""
        text = " ".join(mail.get("text", "").casefold().split())
        has_lure = any(phrase.casefold() in text for phrase in self.prompts.suspicious_link_phrases)
        return has_lure and any(
            re.search(r"https?://(?:www\.)?" + re.escape(host.casefold()) + r"(?=[/?#\s]|$)", text)
            for host in self.prompts.suspicious_link_hosts)

    @staticmethod
    def _enrich_mail_with_attachments(mail: dict[str, Any]) -> dict[str, Any]:
        attachments = mail.get("extracted_attachments")
        if not attachments:
            return mail
        snippets = []
        for att in map(PreparedAttachment.model_validate, attachments):
            if att.usable_text:
                ct = att.content_type
                header = f"--- Anhang: {att.filename} ({ct}) ---" if ct else f"--- Anhang: {att.filename} ---"
                snippets.append(f"\n\n{header}\n{att.usable_text}")
        if not snippets:
            return mail
        enriched = dict(mail)
        base_text = str(mail.get("text", ""))
        enriched["text"] = base_text + "".join(snippets)
        return enriched

    def relevance(self, mail: dict[str, Any], topics: list[Topic]) -> tuple[str, Relevance]:
        self.last_relevance_source = getattr(self.client, "service_name", "OpenRouter")
        if self.suspicious_link_bait(mail):
            return "local-link-safety", Relevance(decision="unclear", topic_ids=[],
                reason="Verdächtiger Kurzlink-Köder. Bitte unabhängig prüfen; daraus werden keine Aktionen angelegt.")
        mail = self._enrich_mail_with_attachments(mail)
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

    def draft_reply(self, mail: dict[str, Any], intent: str, personal_info: str = ""):
        """Reply draft for one requested intent (``accept``, ``decline``, ``question``).

        The model sees the mail, every recognized attachment text (including OCR)
        and the user's own ``personal_info``, but no technical metadata.
        """
        from .drafts import ReplyDraft
        attachments = [{"filename": item.filename, "text": item.usable_text}
                       for item in map(PreparedAttachment.model_validate, mail.get("extracted_attachments", []))
                       if item.usable_text]
        context = {"headers": {name: mail["headers"].get(name, "") for name in ("from", "subject", "date")},
                   "text": mail.get("text", ""), "attachments": attachments,
                   "calendar_events": mail.get("calendar_events", [])}
        return self._run("draft_reply", ReplyDraft, context, {"intent": intent, "personal_info": personal_info})

    def summary(self, mail: dict[str, Any]) -> tuple[str, Summary]:
        return self._run("summary", Summary, self._enrich_mail_with_attachments(mail))

    def action_route(self, mail: dict[str, Any]) -> tuple[str, ActionRoute]:
        if self.suspicious_link_bait(mail):
            return "local-link-safety", ActionRoute(action_state="none", task_count=0,
                event_count=0, reason="Verdächtiger Kurzlink-Köder: keine automatische Handlungsempfehlung.")
        return self._run("action_router", ActionRoute, self._enrich_mail_with_attachments(mail))

    def extract_tasks(self, mail: dict[str, Any], *, expected_count: int) -> tuple[str, TaskExtraction]:
        return self._classified_run(
            "task_extraction", {"mail": self._enrich_mail_with_attachments(mail), "expected_count": expected_count},
            TaskExtraction.model_validate, schema=TaskExtraction,
        )

    def extract_events(self, mail: dict[str, Any], *, expected_count: int) -> tuple[str, EventExtraction]:
        return self._classified_run(
            "event_extraction", {"mail": self._enrich_mail_with_attachments(mail), "expected_count": expected_count},
            EventExtraction.model_validate, schema=EventExtraction,
        )

    def read_document(self, filename: str, content_type: str,
                      images: list[str]) -> tuple[str, VisionExtractionResult]:
        """Read the visible text of one image or scanned document (``vision_ocr``)."""
        return self._classified_run(
            "vision_ocr",
            {"attachment": {"filename": filename, "content_type": content_type,
                            "pages": len(images)}},
            VisionExtractionResult.model_validate, schema=VisionExtractionResult, images=images,
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

    def open_proposal_match(self, proposal: Proposal, candidates: list[Proposal]):
        from .domain.proposal_sources import ProposalMatchDecision
        fields = {"kind", "title", "description", "start", "end", "due", "known_temporal_facts", "evidence"}
        payload = {"incoming": proposal.model_dump(mode="json", include=fields),
                   "candidates": [item.model_dump(mode="json", include=fields) for item in candidates]}
        payload["subjects"] = [[s.subject for s in item.sources[-3:]] for item in [proposal, *candidates]]
        return self._classified_run("open_proposal_match", payload, ProposalMatchDecision.model_validate,
                                    schema=ProposalMatchDecision)

    def answer_question_from_mail(self, mail: dict[str, Any], proposal: Proposal,
                                  question: str) -> tuple[str, TelegramAnswerInterpretation]:
        """Check whether one open proposal question is answered by its source mail."""
        if question not in proposal.open_questions:
            raise ValueError("Die Frage ist im Vorschlag nicht offen")
        allowed = self._revision_fields(proposal, question)
        context = {name: value for name, value in proposal.model_dump(mode="json").items()
                   if name in allowed}
        return self._classified_run(
            "mail_question_resolution",
            {"mail": self._enrich_mail_with_attachments(mail), "question": question, "proposal_fields": context},
            TelegramAnswerInterpretation.model_validate,
            schema=TelegramAnswerInterpretation,
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
            context["known_temporal_facts"] = proposal.known_temporal_facts.model_dump(
                mode="json", exclude_none=True)
        payload = {
            "proposal_fields": context,
            "question": question,
            "normalized_answer": authorized_answer,
            "allowed_changes": allowed,
        }
        retry = self.prompts.prompts["proposal_revision"].output_token_retry
        retry_fields = [] if retry is None else [
            field for field in (retry.change_fields or []) if field in allowed]
        retry_payload: dict[str, Any] | None = None if retry is None else {
            "proposal_fields": {key: context[key] for key in retry_fields if key in context},
            "question": question, "normalized_answer": authorized_answer,
            "allowed_changes": retry_fields,
        }
        if retry_payload is not None:
            for fact_name in ("temporal_fact", "known_temporal_facts"):
                if fact_name in context:
                    retry_payload["proposal_fields"][fact_name] = context[fact_name]
        def validate_delta(raw: Any) -> Proposal:
            # The question is application-owned input.  Never let an LLM typo
            # or its frequent confusion with ``normalized_answer`` choose which
            # open question is closed.  Unknown fields and ``changes`` remain
            # subject to the strict output schema and successor validation.
            if isinstance(raw, dict):
                raw = {**raw, "answered_question": question}
            delta = ProposalRevisionDelta.model_validate(raw)
            # The closed schema admits every business field, so the per-question
            # allowance must be enforced on the untrusted delta itself.
            outside = sorted(delta.changes.model_fields_set - set(allowed))
            if outside:
                raise ValueError(
                    "changes enthält nicht erlaubte Felder: " + ", ".join(outside)
                    + "; erlaubt sind nur: " + ", ".join(allowed))
            # Validate the complete successor inside the bounded repair loop so
            # business-rule failures are reported to the model before success is logged.
            return validate_revision_successor(
                proposal,
                apply_proposal_revision(proposal, delta),
                allow_all_day_resolution=delta.changes.all_day is True,
            )

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
        # An impossible day or time is no deterministic answer (the parser returns None).
        temporal = parse_deterministic_temporal_answer(authorized_answer)
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
        payload: dict[str, Any] = {
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
