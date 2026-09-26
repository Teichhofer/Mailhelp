"""Pure Telegram message splitting and proposal rendering."""

from __future__ import annotations


from ..integrations import proposal_is_writable
from ..models import Proposal, ProposalKind


def split_message(text: str, limit: int = 4000) -> list[str]:
    if limit < 1:
        raise ValueError("limit muss positiv sein")
    return [text[index : index + limit] for index in range(0, len(text), limit)] or [""]


def numbered_message_parts(
    sender: str, subject: str, text: str, limit: int = 4000
) -> list[str]:
    """Split text while repeating its human-readable mail context on every part."""
    if not sender or not subject:
        raise ValueError("Absender und Betreff werden benötigt")
    if limit < 32:
        raise ValueError("limit ist zu klein für eine sichere Zuordnung")
    count = 1
    while True:
        prefix = f"[Absender: {sender} · Teil {count}/{count}]\nBetreff: {subject}\n"
        chunks = split_message(text, limit - len(prefix))
        if len(chunks) == count:
            break
        count = len(chunks)
    return [
        f"[Absender: {sender} · Teil {index}/{count}]\nBetreff: {subject}\n{part}"
        for index, part in enumerate(chunks, 1)
    ]


def format_proposal(
    proposal: Proposal, configured_timezone: str, test_mode: bool = False
) -> str:
    """Render every decision-relevant field in one stable, human-readable order."""
    missing = "—"
    questions = "\n".join(f"- {question}" for question in proposal.open_questions)
    questions_display = f"\n{questions}" if questions else " Keine"
    externally_creatable = proposal_is_writable(proposal)
    if externally_creatable and test_mode and proposal.kind == ProposalKind.TASK:
        external_status = "Nein – Simulation (Testmodus, keine Todoist-Anlage)"
    else:
        external_status = "Ja" if externally_creatable else "Nein – manuell prüfen"
    lines = [
        f"Vorschlagsversion: {proposal.version}",
        f"Typ: {'Aufgabe' if proposal.kind == ProposalKind.TASK else 'Termin'}",
        f"Zuständigkeit: {proposal.responsibility.value}",
        f"Sicherheit: {proposal.certainty.value}",
        f"Einordnung: {proposal.classification.value}",
        f"Extern anlegbar: {external_status}",
        f"Titel: {proposal.title}",
        f"Beschreibung: {proposal.description or missing}",
        f"Belegstelle: {proposal.evidence}",
        f"Offene Fragen:{questions_display}",
        f"Ziel: {proposal.target}",
    ]
    if proposal.kind == ProposalKind.TASK:
        lines.append(
            f"Fälligkeit: {proposal.due.isoformat() if proposal.due else missing}"
        )
    else:
        display_start = proposal.start or (
            proposal.known_temporal_facts.start
            if proposal.known_temporal_facts
            else None
        )
        duration = (
            f"{'höchstens ' if proposal.duration_is_upper_bound else ''}"
            f"{proposal.duration_minutes} Minuten"
            if proposal.duration_minutes
            else missing
        )
        lines.extend(
            [
                f"Beginn: {display_start.isoformat() if display_start else missing}",
                f"Ende: {proposal.end.isoformat() if proposal.end else missing}",
                f"Dauer: {duration}",
                f"Ganztägig: {'Ja' if proposal.all_day else 'Nein'}",
                f"Konfigurierte Zeitzone: {configured_timezone}",
                f"Ort: {proposal.location or missing}",
                f"Videolink: {proposal.video_link or missing}",
            ]
        )
    return "\n".join(lines)
