"""Pure Telegram message splitting and proposal rendering."""

from __future__ import annotations

from datetime import date, datetime, timedelta
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


def display_date(value: date | datetime | None, configured_timezone: str) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        local = value.astimezone(ZoneInfo(configured_timezone))
        return local.strftime("%d.%m.%Y · %H:%M Uhr (UTC%z)")
    return value.strftime("%d.%m.%Y")


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
    lines = [f"Titel: {proposal.title}",
             f"Typ: {'Aufgabe' if proposal.kind == ProposalKind.TASK else 'Termin'}"]
    if proposal.kind == ProposalKind.TASK:
        lines.append(
            f"Fälligkeit: {display_date(proposal.due, configured_timezone)}"
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
                f"Beginn: {display_date(display_start, configured_timezone)}",
                (f"Letzter Tag: {display_date(proposal.end - timedelta(days=1), configured_timezone)}"
                 if proposal.all_day and proposal.end else
                 f"Ende: {display_date(proposal.end, configured_timezone)}"),
                f"Dauer: {duration}",
                f"Ganztägig: {'Ja' if proposal.all_day else 'Nein'}",
                f"Konfigurierte Zeitzone: {configured_timezone}",
                f"Ort: {proposal.location or missing}",
                f"Videolink: {proposal.video_link or missing}",
            ]
        )
        if proposal.known_temporal_facts:
            facts = proposal.known_temporal_facts
            lines.append(f"Bekanntes Datum: {display_date(facts.date, configured_timezone)}")
            if facts.start_time:
                lines.append(f"Bekannte Uhrzeit: {facts.start_time.strftime('%H:%M')} Uhr")
    lines.extend([
        f"Ziel: {proposal.target}",
        f"Vorschlagsversion: {proposal.version} · Noch nicht zur Anlage freigegeben",
        f"Zuständigkeit: {RESPONSIBILITY[proposal.responsibility]}",
        f"Sicherheit: {CERTAINTY[proposal.certainty]}",
        f"Einordnung: {CLASSIFICATION[proposal.classification]}",
        f"Extern anlegbar: {external_status}",
        f"Offene Fragen:{questions_display}",
        f"Beschreibung: {proposal.description or missing}",
        f"Belegstelle: {proposal.evidence}",
    ])
    return "\n".join(lines)


def clarification_prompt(proposal: Proposal, configured_timezone: str) -> str:
    """Show the actual question alongside known facts, without changing its meaning."""
    question = (proposal.open_questions[0] if proposal.open_questions
                else "Welche Änderung soll übernommen werden?")
    example = ("Antworte konkret, z. B. bei einer Uhrzeit mit „19:30 Uhr“ oder bei einem Ort mit „Raum 3“."
               if proposal.open_questions else
               "Antworte z. B. mit „Ändere den Titel in Elternabend“. Dies ist nur ein Beispiel.")
    context = (f"Fälligkeit: {display_date(proposal.due, configured_timezone)}"
               if proposal.kind == ProposalKind.TASK else
               f"Beginn: {display_date(proposal.start or (proposal.known_temporal_facts.start if proposal.known_temporal_facts else None), configured_timezone)}")
    if proposal.known_temporal_facts:
        facts = proposal.known_temporal_facts
        context += f"\nBekanntes Datum: {display_date(facts.date, configured_timezone)}"
        if facts.start_time:
            context += f"\nBekannte Uhrzeit: {facts.start_time.strftime('%H:%M')} Uhr"
    return (f"Rückfrage zu „{proposal.title}“ · Version {proposal.version}\n"
            f"{context}\nZiel: {proposal.target}\n\n"
            f"Bitte beantworten: {question}\n{example}\n"
            "Mit /abbrechen zur Vorschlagsansicht zurückkehren.")


def revision_summary(previous: Proposal, current: Proposal, configured_timezone: str) -> str:
    """Compare rendered business fields; versions and workflow state are not edits."""
    before = format_proposal(previous, configured_timezone).splitlines()
    after = format_proposal(current, configured_timezone).splitlines()
    # Include full changed lines, including multi-line descriptions/questions.
    changes = [line for line in after if line not in before
               and not line.startswith("Vorschlagsversion:")]
    removed = [line for line in before if line not in after
               and not line.startswith("Vorschlagsversion:")]
    if not changes and not removed:
        return "Überarbeitet: Keine inhaltlichen Änderungen. Bitte aktuelle Version prüfen."
    return "Geändert seit Version " + str(previous.version) + ":\n" + "\n".join(
        [f"Bisher: {line}" for line in removed] + [f"Jetzt: {line}" for line in changes])
