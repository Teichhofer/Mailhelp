"""Channel-neutral proposal card content shared by Telegram and the web.

A card shows what matters for the decision: title and time first, empty fields
and default values left out, long texts shortened.  Telegram renders the
content as text; the web renders the same content as HTML and can also show
the unshortened description and evidence.  The complete data stays in the
stored proposal and is written to Todoist or Google Calendar unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.utils import parseaddr
from zoneinfo import ZoneInfo

from ..domain.proposal import Proposal, ProposalKind
from ..external.contracts import proposal_is_writable
from ..external.google_tasks import DUE_NOTE
from ..formatting import format_datetime_local
from ..i18n import tr
from ..i18n.formatting import clock, clock_suffix, day, day_time

RESPONSIBILITY = {"user": "Du", "other": "Andere Person", "unclear": "Noch unklar"}
CERTAINTY = {"certain": "Eindeutig", "uncertain": "Unsicher", "contradictory": "Widersprüchlich"}
CLASSIFICATION = {
    "new": "Neu", "non_binding": "Unverbindlicher Hinweis",
    "already_completed": "Bereits erledigt", "change": "Änderung eines bestehenden Eintrags",
    "cancellation": "Absage", "recurring": "Wiederkehrend", "unsupported": "Manuell prüfen",
}
# Stored question texts are identities used by the domain logic; only their
# display is shortened and addressed to the user.
QUESTION_DISPLAY = {
    "Ist die Nutzerin oder der Nutzer für diesen Eintrag zuständig?": "Bist du dafür zuständig?",
    "Ist die extrahierte Information sicher belegt?": "Stimmen die Angaben so?",
    "Soll der nicht bindende Hinweis dennoch als neuer Eintrag angelegt werden?":
        "Ist nur ein Hinweis – trotzdem anlegen?",
}
DESCRIPTION_LIMIT = 300
EVIDENCE_LIMIT = 200
SUBJECT_LIMIT = 80
# The trailing provenance block ProposalBuilder appends to every description.
_PROVENANCE = re.compile(r"(?:\n\n|^)Absender: [^\n]*\nBetreff: [^\n]*\nMail-Datum: [^\n]*\Z")


def display_date(value: date | datetime | None, configured_timezone: str) -> str:
    """Date, or date and clock time in the configured timezone."""
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return format_datetime_local(value, configured_timezone)
    return day(value)


def shorten(text: str, limit: int) -> str:
    """Collapse whitespace and cut at a word boundary with an ellipsis."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit - 1]
    return (cut.rsplit(" ", 1)[0] if " " in cut else cut) + "…"


def sender_name(sender: str) -> str:
    """The display name of a sender header, or its address if it has none."""
    name, address = parseaddr(sender)
    return name.strip().strip('"') or address or sender


def display_question(question: str) -> str:
    """The question as shown; stored texts stay German identities, only the display is translated (7.5)."""
    return tr(QUESTION_DISPLAY.get(question, question))


_YES_NO = "„ja“ oder „nein“"


def _example(question: str) -> str | None:
    """The German example answer for the kind of the (German, stored) question."""
    words = set(re.findall(r"\w+", question.casefold()))
    if words & {"endet", "ende"}:
        return "„16:00“ oder „nach 2 Stunden“"
    if words & {"beginnt", "datum", "wann", "uhrzeit"}:
        return "„21.10.2026 14:00“"
    if words & {"zuständig", "belegt", "dennoch"}:
        return _YES_NO
    if "ort" in words:
        return "„Raum 3“"
    return None


def answer_example(question: str) -> str | None:
    """A short example answer that matches the kind of question, in the active language (7.5)."""
    example = _example(question)
    return tr(example) if example is not None else None


def yes_no_question(question: str) -> bool:
    """Whether the question is answered with yes or no; independent of the display language."""
    return _example(question) == _YES_NO


def event_time(proposal: Proposal, configured_timezone: str) -> str | None:
    text = _event_time(proposal, configured_timezone)
    if proposal.default_duration_minutes is not None:
        text = f"{text} · " + tr("Ende angenommen: Standarddauer {minutes} Min.",
                                  minutes=proposal.default_duration_minutes)
    return text


def _event_time(proposal: Proposal, configured_timezone: str) -> str | None:
    """One line for the event time; None if nothing about it is known yet."""
    zone = ZoneInfo(configured_timezone)
    start = proposal.start or (
        proposal.known_temporal_facts.start if proposal.known_temporal_facts else None
    )
    end = proposal.end
    if proposal.all_day and isinstance(start, date) and not isinstance(start, datetime):
        last = end - timedelta(days=1) if isinstance(end, date) else None
        if last is not None and last != start:
            return f"{day(start)} – {day(last)}, {tr('ganztägig')}"
        return f"{day(start)}, {tr('ganztägig')}"
    if isinstance(start, datetime):
        local_start = start.astimezone(zone)
        if isinstance(end, datetime):
            local_end = end.astimezone(zone)
            if local_end.date() == local_start.date():
                return f"{day(local_start)}, {clock(local_start)}–{clock(local_end)}{clock_suffix()}"
            return f"{day_time(local_start)} – {day_time(local_end)}"
        text = day_time(local_start)
        if proposal.duration_minutes:
            minutes = tr("{n} Min.", n=proposal.duration_minutes)
            bounded = tr("höchstens {duration}", duration=minutes) if proposal.duration_is_upper_bound else minutes
            text += f" ({bounded})"
        return text
    facts = proposal.known_temporal_facts
    if facts is not None and facts.date is not None:
        text = day(facts.date)
        if facts.start_time:
            text += f", {clock(facts.start_time)}{clock_suffix()}"
        return text
    return None


def full_description(proposal: Proposal) -> str | None:
    """The description without the appended mail provenance, if it adds anything."""
    text = _PROVENANCE.sub("", proposal.description or "").strip()
    if not text:
        return None
    normalized = " ".join(text.split()).casefold()
    if normalized in {" ".join(proposal.title.split()).casefold(),
                      " ".join(proposal.evidence.split()).casefold()}:
        return None
    return text


@dataclass(frozen=True)
class CardContent:
    """Everything a proposal card shows, as structured, unescaped values."""

    kind: ProposalKind
    title: str
    version: int
    when: str | None
    due: str | None
    location: str | None
    video_link: str | None
    responsibility: str | None
    certainty: str | None
    classification: str | None
    writable: bool
    test_mode: bool
    questions: tuple[str, ...]
    description: str | None
    description_full: str | None
    evidence: str
    evidence_full: str
    profile_label: str | None = None
    target: str | None = None
    target_hint: str | None = None


def card_content(proposal: Proposal, configured_timezone: str,
                 test_mode: bool = False) -> CardContent:
    """Build the card; deviations from the defaults are the only labels shown."""
    event = proposal.kind == ProposalKind.EVENT
    description = full_description(proposal)
    return CardContent(
        kind=proposal.kind,
        title=proposal.title,
        version=proposal.version,
        when=event_time(proposal, configured_timezone) if event else None,
        due=(display_date(proposal.due, configured_timezone)
             if not event and proposal.due is not None else None),
        location=proposal.location if event else None,
        video_link=str(proposal.video_link) if event and proposal.video_link else None,
        responsibility=(tr(RESPONSIBILITY[proposal.responsibility])
                        if proposal.responsibility != "user" else None),
        certainty=(tr(CERTAINTY[proposal.certainty])
                   if proposal.certainty != "certain" else None),
        classification=(tr(CLASSIFICATION[proposal.classification])
                        if proposal.classification != "new" else None),
        writable=proposal_is_writable(proposal),
        test_mode=test_mode,
        questions=tuple(display_question(question) for question in proposal.open_questions),
        description=shorten(description, DESCRIPTION_LIMIT) if description else None,
        description_full=description,
        evidence=shorten(proposal.evidence, EVIDENCE_LIMIT),
        evidence_full=proposal.evidence,
        target_hint=DUE_NOTE if not event and proposal.target_provider == "google_tasks" else None,
    )


__all__ = [
    "CERTAINTY", "CLASSIFICATION", "CardContent", "DESCRIPTION_LIMIT", "EVIDENCE_LIMIT",
    "QUESTION_DISPLAY", "RESPONSIBILITY", "SUBJECT_LIMIT", "answer_example", "card_content",
    "display_date", "display_question", "event_time", "full_description", "sender_name",
    "shorten", "yes_no_question",
]
