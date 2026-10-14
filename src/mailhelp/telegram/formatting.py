"""Pure Telegram message splitting and proposal rendering.

Proposals are rendered as a compact card built from the channel-neutral card
content (:mod:`mailhelp.review.cards`), so Telegram and the web show the same
information.  The complete data stays in the stored proposal and is written to
Todoist or Google Calendar unchanged.
"""

from __future__ import annotations

import re

from ..models import Proposal, ProposalKind
from ..review.cards import (
    CERTAINTY,
    CLASSIFICATION,
    DESCRIPTION_LIMIT,
    EVIDENCE_LIMIT,
    QUESTION_DISPLAY,
    RESPONSIBILITY,
    SUBJECT_LIMIT,
    answer_example,
    card_content,
    display_date,
    display_question,
    event_time,
    sender_name,
    shorten,
)

_VERSION = re.compile(r" \(Version \d+\)")


def mail_line(sender: str, subject: str, mailbox: str = "") -> str:
    """One line of mail context; *mailbox* is the label shown with several mailboxes (3.1)."""
    prefix = f"[{mailbox}] " if mailbox else ""
    return f"✉️ {prefix}{sender_name(sender)} · {shorten(subject, SUBJECT_LIMIT)}"


def split_message(text: str, limit: int = 4000) -> list[str]:
    if limit < 1:
        raise ValueError("limit muss positiv sein")
    return [text[index : index + limit] for index in range(0, len(text), limit)] or [""]


def numbered_message_parts(
    sender: str, subject: str, text: str, limit: int = 4000, mailbox: str = ""
) -> list[str]:
    """Split text and repeat a one-line mail context on every part.

    The part counter is shown only when the text really needs several messages.
    """
    if not sender or not subject:
        raise ValueError("Absender und Betreff werden benötigt")
    if limit < 32:
        raise ValueError("limit ist zu klein für eine sichere Zuordnung")
    header = mail_line(sender, subject, mailbox)
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


def format_proposal(
    proposal: Proposal, configured_timezone: str, test_mode: bool = False
) -> str:
    """Render a compact card: title and time first, deviations and questions after."""
    card = card_content(proposal, configured_timezone, test_mode)
    event = card.kind == ProposalKind.EVENT
    version = f" (Version {card.version})" if card.version > 1 else ""
    lines = [f"{'📅 Termin' if event else '✅ Aufgabe'}{version}: {card.title}"]
    if card.when:
        lines.append(f"🕒 {card.when}")
    if card.location:
        lines.append(f"📍 {card.location}")
    if card.video_link:
        lines.append(f"🔗 {card.video_link}")
    if card.due:
        lines.append(f"🕒 Fällig: {card.due}")
    if card.responsibility:
        lines.append(f"Zuständig: {card.responsibility}")
    if card.certainty:
        lines.append(f"Sicherheit: {card.certainty}")
    if card.classification:
        lines.append(f"Einordnung: {card.classification}")
    if proposal.target_event_id is not None:
        if proposal.is_cancellation:
            lines.append("❌ Status: Bestehender Termin soll abgesagt werden")
        elif proposal.time_changes:
            lines.append(f"🔄 Terminänderung gegenüber Kalender ({', '.join(proposal.time_changes)})")
        else:
            lines.append("🔄 Terminänderung gegenüber Kalender")
    if not card.writable:
        lines.append("⚠️ Kann nicht automatisch angelegt werden – bitte manuell prüfen.")
    elif test_mode:
        lines.append("🧪 Testmodus: Der Eintrag wird nur simuliert, nicht extern angelegt.")
    if card.questions:
        lines.append("❓ Offen:")
        lines.extend(f"- {question}" for question in card.questions)
    if card.description:
        lines.append(f"📝 {card.description}")
    lines.append(f"Beleg: „{card.evidence}“")
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
            when = event_time(proposal, configured_timezone)
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
    new_questions = [f"- {display_question(question)}" for question in current.open_questions
                     if question not in previous.open_questions]
    added = [line for line in after if line not in before
             and line != "❓ Offen:" and line not in new_questions]
    text = "Übernommen" + (":\n" + "\n".join(added) if added else ".")
    if new_questions:
        text += "\nNeu offen:\n" + "\n".join(new_questions)
    return text


__all__ = [
    "CERTAINTY", "CLASSIFICATION", "DESCRIPTION_LIMIT", "EVIDENCE_LIMIT",
    "QUESTION_DISPLAY", "RESPONSIBILITY", "SUBJECT_LIMIT", "answer_example",
    "clarification_prompt", "display_date", "display_question", "format_proposal",
    "mail_line", "numbered_message_parts", "revision_summary", "sender_name",
    "shorten", "split_message",
]
