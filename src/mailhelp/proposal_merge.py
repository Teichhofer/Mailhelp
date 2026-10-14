"""Non-destructive addition of source facts; every material change is versioned."""

from datetime import datetime
from typing import Any

from .domain.proposal import KnownTemporalFacts, Proposal, ProposalStatus, required_revision_questions
from .domain.proposal_sources import ProposalReference
from .proposal_matching import day

_TIME_QUESTIONS = ("Wann beginnt der Termin?", "Wann endet der Termin?",
                   "Welches konkrete Datum", "Ist die extrahierte Information sicher belegt?")
# Fields an additional source may add or change, in the order they are compared.
_MERGED_FIELDS = ("start", "end", "due", "location", "video_link", "known_temporal_facts")
_TEMPORAL_FIELDS = {"start", "end", "known_temporal_facts"}
# Fields that belong to an accepted start or end and are dropped with an inconsistent interval.
_INTERVAL_FIELDS = ("start", "end", "known_temporal_facts", "temporal_fact", "end_origin", "default_duration_minutes")
_NON_BINDING_QUESTION = "Soll der nicht bindende Hinweis dennoch als neuer Eintrag angelegt werden?"


class _Merge:
    """The changes and open questions that one additional source causes."""

    def __init__(self, previous: Proposal, incoming: Proposal):
        self.previous, self.incoming = previous, incoming
        self.changes: dict[str, Any] = {
            "sources": list(previous.sources), "explicit_create_fallback_confirmed": False,
            "explicit_non_binding_create_confirmed": False, "explicit_duplicate_create_confirmed_version": None}
        if incoming.duplicate_check_failed:
            self.changes["duplicate_check_failed"] = True
        for source in incoming.sources:
            if source not in self.changes["sources"]:
                self.changes["sources"].append(source)
        self.questions = list(previous.open_questions)
        self.latest_old = max((s.sent_at for s in previous.sources if s.sent_at is not None), default=None)
        self.latest_new = max((s.sent_at for s in incoming.sources if s.sent_at is not None), default=None)
        self.newer = self.latest_new is not None and (self.latest_old is None or self.latest_new > self.latest_old)

    def hold_for_review(self) -> None:
        """An uncertain match only records the source; its facts wait for the user."""
        reference = ProposalReference(mail_id=self.incoming.source_mail_id, proposal_id=self.incoming.id)
        pending = dict.fromkeys((item.mail_id, item.proposal_id)
                                for item in [*self.previous.pending_sources, reference])
        self.changes["pending_sources"] = [ProposalReference(mail_id=mail, proposal_id=proposal)
                                           for mail, proposal in pending]
        self.questions.append("Zuordnung der zusätzlichen Quelle prüfen.")

    def add_facts(self) -> None:
        self._upgrade_classification()
        for field in _MERGED_FIELDS:
            self._merge_field(field)
        self._follow_up_fields()
        self._merge_description()
        self._check_interval()

    def _protected_clock_changed(self) -> bool:
        known, incoming = self.previous.known_temporal_facts, self.incoming
        start = incoming.start or (incoming.known_temporal_facts.start if incoming.known_temporal_facts else None)
        return bool(known and isinstance(start, datetime) and (
            known.start is not None and known.start != start
            or known.start_time is not None and known.start_time != start.time()))

    def _upgrade_classification(self) -> None:
        previous, incoming = self.previous, self.incoming
        if (self.newer and previous.classification == "non_binding" and incoming.classification == "new"
                and "classification" not in previous.protected_fields):
            self.changes["classification"] = incoming.classification
            self.questions = [question for question in self.questions if question != _NON_BINDING_QUESTION]

    def _merge_field(self, field: str) -> None:
        old, new = getattr(self.previous, field), getattr(self.incoming, field)
        if new is None or new == old or self._settled_temporally(field, old, new):
            return
        previous, incoming = self.previous, self.incoming
        if field in previous.protected_fields:
            self.questions.append(f"Widerspruch bei {field}: Angaben aus den Quellen vergleichen.")
        elif field == "start" and old is not None and incoming.end is None:
            self.questions.append("Abweichender Beginn ohne belegtes Ende: Quellen vergleichen.")
        elif old is None or self._replaces(field):
            self.changes[field] = new
        elif self.newer or self.latest_new is None or self.latest_new == self.latest_old:
            self.questions.append(f"Widerspruch bei {field}: Angaben aus den Quellen vergleichen.")

    def _settled_temporally(self, field: str, old: Any, new: Any) -> bool:
        """Temporal rules that decide a field on their own; ``True`` once the field is handled."""
        previous, incoming = self.previous, self.incoming
        if field in _TEMPORAL_FIELDS and previous.all_day != incoming.all_day:
            self.questions.append("Ganztägige und zeitgebundene Angaben aus den Quellen vergleichen.")
            return True
        if field in {"start", "end"} and "known_temporal_facts" in previous.protected_fields and (
                day(previous) is not None and day(incoming) != day(previous) or self._protected_clock_changed()):
            self.questions.append("Widerspruch zum manuell festgelegten Datum oder Beginn: Quellen vergleichen.")
            return True
        if field != "known_temporal_facts":
            return False
        if previous.start is None and _completes_known_facts(old, new):
            self.changes[field] = KnownTemporalFacts(date=old.date or new.start.date(), start=new.start)
            return True
        # An accepted start already says more than the known facts of another source.
        return previous.start is not None

    def _replaces(self, field: str) -> bool:
        """A documented end replaces an assumed one; a newer change replaces any value."""
        previous, incoming = self.previous, self.incoming
        return (field == "end" and previous.end_origin == "standard" and incoming.end_origin != "standard"
                and incoming.start == previous.start
                or self.newer and incoming.classification == "change")

    def _follow_up_fields(self) -> None:
        changes, incoming = self.changes, self.incoming
        if changes.get("known_temporal_facts") is not None:
            changes["temporal_fact"] = incoming.temporal_fact
        if changes.get("start") is not None:
            changes["known_temporal_facts"] = None
            changes["temporal_fact"] = incoming.temporal_fact
        if "end" in changes:
            changes.update(end_origin=incoming.end_origin, default_duration_minutes=incoming.default_duration_minutes)
        if self.previous.meeting_mode == "unknown":
            changes["meeting_mode"] = incoming.meeting_mode
        if incoming.certainty == "certain" and self.newer:
            changes["certainty"] = incoming.certainty

    def _merge_description(self) -> None:
        fragment = self.incoming.description.split("\n\nAbsender:", 1)[0].strip()
        if not fragment or fragment in self.previous.description:
            return
        if "description" in self.previous.protected_fields:
            self.questions.append("Zusätzliche Beschreibung aus der neuen Quelle prüfen.")
        else:
            self.changes["description"] = (self.previous.description + "\n\nErgänzung: " + fragment)[:4000]

    def _check_interval(self) -> None:
        """Drop an inconsistent interval; settled times answer their open questions."""
        candidate = self.previous.model_copy(update=self.changes)
        if candidate.start is not None and candidate.end is not None and candidate.end <= candidate.start:
            for field in _INTERVAL_FIELDS:
                self.changes.pop(field, None)
            self.questions.append("Widersprüchliches Zeitintervall aus den Quellen prüfen.")
            candidate = self.previous.model_copy(update=self.changes)
        if candidate.certainty == "certain":
            self.questions = [question for question in self.questions
                              if not question.startswith(_answered_questions(candidate))]
        self.questions.extend(required_revision_questions(candidate))


def _completes_known_facts(old: KnownTemporalFacts | None, new: KnownTemporalFacts) -> bool:
    """A start of another source that only adds the clock to the same known date."""
    return (old is not None and old.start is None and new.start is not None
            and (old.date is None or old.date == new.start.date())
            and (old.start_time is None or old.start_time == new.start.time()))


def _answered_questions(candidate: Proposal) -> tuple[str, ...]:
    """Prefixes of the time questions a certain candidate has answered."""
    if candidate.start is not None and candidate.end is not None:
        return _TIME_QUESTIONS
    if candidate.known_temporal_facts is not None and candidate.known_temporal_facts.start is not None:
        return (_TIME_QUESTIONS[0], *_TIME_QUESTIONS[2:])
    return ()


def merge_facts(previous: Proposal, incoming: Proposal, *, uncertain=False) -> Proposal:
    merge = _Merge(previous, incoming)
    if uncertain:
        merge.hold_for_review()
    else:
        merge.add_facts()
    changes = merge.changes
    changes["open_questions"] = list(dict.fromkeys(merge.questions))
    changes["status"] = (ProposalStatus.NEEDS_CLARIFICATION if changes["open_questions"]
                         else ProposalStatus.PENDING_CONFIRMATION)
    if all(getattr(previous, name) == value for name, value in changes.items()):
        return previous
    changes.update(version=previous.version + 1, explicit_create_fallback_confirmed=False,
                   explicit_non_binding_create_confirmed=False, explicit_duplicate_create_confirmed_version=None,
                   uncertain_notified=False)
    return Proposal.model_validate(previous.model_copy(update=changes).model_dump())
