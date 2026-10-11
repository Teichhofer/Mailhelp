"""Pure Telegram message splitting and proposal rendering.

Proposals are rendered as a compact card: what matters for the decision comes
first, empty fields and default values are left out, and long texts are
shortened.  The complete data stays in the stored proposal and is written to
Todoist or Google Calendar unchanged.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from email.utils import parseaddr
from zoneinfo import ZoneInfo

from ..integrations import proposal_is_writable
from ..models import Proposal, ProposalKind


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
_VERSION = re.compile(r" \(Version \d+\)")
_PROVENANCE = re.compile(r"(?:\n\n|^)Absender: [^\n]*\nBetreff: [^\n]*\nMail-Datum: [^\n]*\Z")


def display_date(value: date | datetime | None, configured_timezone: str) -> str:
    """Date, or date and clock time in the configured timezone."""
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.astimezone(ZoneInfo(configured_timezone)).strftime("%d.%m.%Y, %H:%M Uhr")
    return value.strftime("%d.%m.%Y")


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


def mail_line(sender: str, subject: str) -> str:
    return f"✉️ {sender_name(sender)} · {shorten(subject, SUBJECT_LIMIT)}"


def display_question(question: str) -> str:
    return QUESTION_DISPLAY.get(question, question)


def answer_example(question: str) -> str | None:
    """A short example answer that matches the kind of question."""
    words = set(re.findall(r"\w+", question.casefold()))
    if words & {"endet", "ende"}:
        return "„16:00“ oder „nach 2 Stunden“"
    if words & {"beginnt", "datum", "wann", "uhrzeit"}:
        return "„21.10.2026 14:00“"
    if words & {"zuständig", "belegt", "dennoch"}:
        return "„ja“ oder „nein“"
    if "ort" in words:
        return "„Raum 3“"
    return None


def split_message(text: str, limit: int = 4000) -> list[str]:
    if limit < 1:
        raise ValueError("limit muss positiv sein")
    return [text[index : index + limit] for index in range(0, len(text), limit)] or [""]


def numbered_message_parts(
    sender: str, subject: str, text: str, limit: int = 4000
) -> list[str]:
    """Split text and repeat a one-line mail context on every part.

    The part counter is shown only when the text really needs several messages.
    """
    if not sender or not subject:
        raise ValueError("Absender und Betreff werden benötigt")
    if limit < 32:
        raise ValueError("limit ist zu klein für eine sichere Zuordnung")
    header = mail_line(sender, subject)
    count = 1
    while True:
        prefix = f"{header} · Teil {count}/{count}\n" if count > 1 else f"{header}\n"
        chunks = split_message(text, limit - len(prefix))
        if len(chunks) == count:
            break
        count = len(chunks)
    if count == 1:
        return [f"{header}\n{chunks[0]}"]
    return [f"{header} · Teil {index}/{count}\n{part}" for index, part in enumerate(chunks, 1)]


def _when(proposal: Proposal, configured_timezone: str) -> str | None:
    """One line for the event time; None if nothing about it is known yet."""
    zone = ZoneInfo(configured_timezone)
    start = proposal.start or (
        proposal.known_temporal_facts.start if proposal.known_temporal_facts else None
    )
    end = proposal.end
    if proposal.all_day and isinstance(start, date) and not isinstance(start, datetime):
        last = end - timedelta(days=1) if isinstance(end, date) else None
        if last is not None and last != start:
            return f"{start:%d.%m.%Y} – {last:%d.%m.%Y}, ganztägig"
        return f"{start:%d.%m.%Y}, ganztägig"
    if isinstance(start, datetime):
        local_start = start.astimezone(zone)
        if isinstance(end, datetime):
            local_end = end.astimezone(zone)
            if local_end.date() == local_start.date():
                return f"{local_start:%d.%m.%Y, %H:%M}–{local_end:%H:%M} Uhr"
            return f"{local_start:%d.%m.%Y, %H:%M} Uhr – {local_end:%d.%m.%Y, %H:%M} Uhr"
        text = f"{local_start:%d.%m.%Y, %H:%M} Uhr"
        if proposal.duration_minutes:
            prefix = "höchstens " if proposal.duration_is_upper_bound else ""
            text += f" ({prefix}{proposal.duration_minutes} Min.)"
        return text
    facts = proposal.known_temporal_facts
    if facts is not None and facts.date is not None:
        text = f"{facts.date:%d.%m.%Y}"
        if facts.start_time:
            text += f", {facts.start_time:%H:%M} Uhr"
        return text
    return None


def _description(proposal: Proposal) -> str | None:
    """The description without the appended mail provenance, if it adds anything."""
    text = _PROVENANCE.sub("", proposal.description or "").strip()
    if not text:
        return None
    normalized = " ".join(text.split()).casefold()
    if normalized in {" ".join(proposal.title.split()).casefold(),
                      " ".join(proposal.evidence.split()).casefold()}:
        return None
    return shorten(text, DESCRIPTION_LIMIT)


def format_proposal(
    proposal: Proposal, configured_timezone: str, test_mode: bool = False
) -> str:
    """Render a compact card: title and time first, deviations and questions after."""
    event = proposal.kind == ProposalKind.EVENT
    version = f" (Version {proposal.version})" if proposal.version > 1 else ""
    lines = [f"{'📅 Termin' if event else '✅ Aufgabe'}{version}: {proposal.title}"]
    if event:
        when = _when(proposal, configured_timezone)
        if when:
            lines.append(f"🕒 {when}")
        if proposal.location:
            lines.append(f"📍 {proposal.location}")
        if proposal.video_link:
            lines.append(f"🔗 {proposal.video_link}")
    elif proposal.due is not None:
        lines.append(f"🕒 Fällig: {display_date(proposal.due, configured_timezone)}")
    if proposal.responsibility != "user":
        lines.append(f"Zuständig: {RESPONSIBILITY[proposal.responsibility]}")
    if proposal.certainty != "certain":
        lines.append(f"Sicherheit: {CERTAINTY[proposal.certainty]}")
    if proposal.classification != "new":
        lines.append(f"Einordnung: {CLASSIFICATION[proposal.classification]}")
    writable = proposal_is_writable(proposal)
    if not writable:
        lines.append("⚠️ Kann nicht automatisch angelegt werden – bitte manuell prüfen.")
    elif test_mode and proposal.kind == ProposalKind.TASK:
        lines.append("🧪 Testmodus: Die Aufgabe wird nur simuliert, nicht in Todoist angelegt.")
    if proposal.open_questions:
        lines.append("❓ Offen:")
        lines.extend(f"- {display_question(question)}" for question in proposal.open_questions)
    description = _description(proposal)
    if description:
        lines.append(f"📝 {description}")
    lines.append(f"Beleg: „{shorten(proposal.evidence, EVIDENCE_LIMIT)}“")
    return "\n".join(lines)


def clarification_prompt(proposal: Proposal, configured_timezone: str) -> str:
    """Ask exactly one question, with the known time and a fitting example."""
    if proposal.open_questions:
        question = proposal.open_questions[0]
        text = f"❓ {display_question(question)}"
        example = answer_example(question)
    else:
        text = f"✏️ Was soll an „{proposal.title}“ geändert werden?"
        example = "„Titel: Elternabend“ oder „Ort: Raum 3“"
    if proposal.open_questions:
        context = f"„{proposal.title}“"
        if proposal.kind == ProposalKind.EVENT:
            when = _when(proposal, configured_timezone)
            if when:
                context += f" · {when}"
        elif proposal.due is not None:
            context += f" · fällig {display_date(proposal.due, configured_timezone)}"
        text += f"\n{context}"
    hint = f"z. B. {example} · " if example else ""
    return f"{text}\n{hint}/abbrechen beendet die Bearbeitung"


def revision_summary(previous: Proposal, current: Proposal, configured_timezone: str) -> str:
    """List what the answer changed; a new version number alone is not an edit."""
    def lines(proposal: Proposal) -> list[str]:
        rendered = format_proposal(proposal, configured_timezone).splitlines()
        # The header carries the title, which can change; only its version is ignored.
        return [_VERSION.sub("", rendered[0]), *rendered[1:]]

    before, after = lines(previous), lines(current)
    if before == after:
        return "Übernommen – keine sichtbare Änderung."
    added = [line for line in after if line not in before and line != "❓ Offen:"]
    return "Übernommen" + (":\n" + "\n".join(added) if added else ".")
