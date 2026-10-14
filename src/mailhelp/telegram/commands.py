"""Local commands, called only after the controller authorizes the sender."""

from __future__ import annotations

from .. import state_names
from ..models import AnswerStatus, Proposal, ProposalClarificationState, ProposalStatus, TelegramDialogState
from .formatting import clarification_prompt
from .persistence import clarification_name, proposal_name

HELP = (
    "Mailhelp – Befehle\n"
    "/offen – aktuelle Entscheidung erneut zeigen\n"
    "/status – alle offenen Vorgänge auflisten\n"
    "/abbrechen – laufende Rückfrage beenden\n"
    "/web – Link und Code für die Weboberfläche\n"
    "/web_abmelden – alle Geräte der Weboberfläche abmelden\n"
    "/hilfe – diese Übersicht\n\n"
    "Vorschläge kommen einzeln nacheinander. Rückfragen beantwortest du einfach mit "
    "einer Nachricht; die nächste offene Frage folgt automatisch. Angelegt wird erst, "
    "wenn du „Im Kalender anlegen“ bzw. „Als Aufgabe anlegen“ drückst."
)
STARTUP = "👋 Mailhelp gestartet. Befehle: /hilfe"


class TelegramCommands:
    def __init__(self, store, repository, presenter, telegram, chat_id, relevance,
                 outbox=None, web_logout=None, web_invite=None):
        self.store, self.repository, self.presenter = store, repository, presenter
        self.telegram, self.chat_id, self.relevance = telegram, chat_id, relevance
        self.outbox, self.web_logout, self.web_invite = outbox, web_logout, web_invite

    def handle(self, command: str) -> None:
        if command in {"/hilfe", "/start"}:
            self.telegram.send(self.chat_id, HELP)
        elif command in {"/status", "/offen"}:
            self.overview(interactive=command == "/offen")
        elif command == "/abbrechen":
            self.cancel()
        elif command == "/web_abmelden":
            self.web_signout()
        elif command == "/web":
            self.web_link()
        else:
            self.telegram.send(self.chat_id, "Unbekannter Befehl. Verfügbare Befehle: /hilfe")

    def overview(self, *, interactive: bool = False, compact: bool = False) -> None:
        """List open decisions; *compact* counts held-back proposals instead of listing them."""
        lines = []
        profiles = self.presenter.profiles_status()
        if profiles:
            lines.append(profiles)
        presentations = []
        active_prompt = None
        labels = {}
        active = self.store.load_model("telegram-dialog", TelegramDialogState)
        current_key = None
        queued = self.outbox.queued_proposals() if self.outbox is not None else set()
        held_back = 0
        # With sequential questions only the current decision gets buttons.
        sequential = self.outbox is not None and self.outbox.enabled
        current = self.outbox.current_decision() if sequential else None
        for dialog in self.relevance.open():
            mail = self.repository.load_mail(dialog.mail_id)
            subject = mail.display_headers.subject if mail and mail.display_headers else "Mail ohne Betreff"
            labels[(dialog.mail_id, None)] = f"Relevanz „{subject}“ · Version {dialog.version}"
            lines.append(f"Relevanzentscheidung: {subject} · Version {dialog.version}")
        for name in self.store.names(state_names.PROPOSAL_PREFIX):
            proposal = self.store.load_model(name, Proposal)
            if name != proposal_name(proposal.source_mail_id, proposal.id):
                continue
            if proposal.status not in {ProposalStatus.PENDING_CONFIRMATION, ProposalStatus.NEEDS_CLARIFICATION}:
                continue
            state = self.store.load_model(clarification_name(
                proposal.source_mail_id, proposal.id, proposal.version), ProposalClarificationState)
            editing = active is not None and (active.mail_id, active.proposal_id, active.version) == (
                proposal.source_mail_id, proposal.id, proposal.version)
            saved = (state is not None and state.authorized_answer is not None
                     and state.answer_status != AnswerStatus.INVALID)
            key = (proposal.source_mail_id, proposal.id)
            labels[key] = f"„{proposal.title}“ · Version {proposal.version}"
            if editing:
                current_key = key
            if (proposal.source_mail_id, proposal.id, proposal.version) in queued:
                # Not shown yet: it follows once the current decision is resolved.
                if compact:
                    held_back += 1
                    continue
                status = "Noch nicht gesendet – folgt nach Erledigung der aktuellen Entscheidung"
            elif saved:
                status = ("Verarbeitung pausiert; Betreiber muss den gespeicherten Zustand prüfen"
                          if "paused" in {state.interpretation_status, state.proposal_revision_status}
                          else "Antwort gespeichert; Verarbeitung läuft oder wird automatisch fortgesetzt")
            elif editing and active.retry_required:
                status = "Antwort gespeichert; Verarbeitung wird automatisch fortgesetzt"
            else:
                clarify = ("Klärung erforderlich – bitte „Klären“ bzw. „Ändern“ oder „Manuell prüfen“ wählen")
                status = ("Warte auf Antwort zur angezeigten Frage" if editing else
                          clarify if proposal.status == ProposalStatus.NEEDS_CLARIFICATION
                          else "Warte auf Bestätigung oder Verwerfen")
                if interactive:
                    if editing:
                        active_prompt = clarification_prompt(proposal, self.presenter.configured_timezone)
                    else:
                        mail = self.repository.load_mail(proposal.source_mail_id)
                        sender = mail.display_headers.sender if mail and mail.display_headers else "—"
                        subject = mail.display_headers.subject if mail and mail.display_headers else "—"
                        presentations.append((key, self.presenter.present(proposal, sender, subject)))
            lines.append(f"„{proposal.title}“ · Version {proposal.version}: {status}")
        if current_key is None and current is not None:
            current_key = (current.mail_id, current.proposal_id)
        if sequential:
            presentations = [item for item in presentations if item[0] == current_key]
            if current_key in labels:
                lines.append(f"Aktuelle Entscheidung: {labels[current_key]}")
        if held_back:
            lines.append(f"{held_back} weitere Vorschläge folgen nacheinander.")
        held = self.outbox.held_count() if self.outbox is not None else 0
        if held and not compact:
            lines.append(f"Zurückgehaltene Nachrichten bis zur Erledigung der aktuellen Entscheidung: {held}")
        self.telegram.send(self.chat_id, "\n".join(lines) if lines else "Keine offene Telegram-Entscheidung.")
        for _, presentation in presentations:
            for part in presentation.parts[:-1]:
                self.telegram.send(self.chat_id, part)
            self.telegram.send(self.chat_id, presentation.parts[-1], presentation.reply_markup)
        # Keep the uniquely assigned question last; never assign free text by list order.
        if active_prompt is not None:
            self.telegram.send(self.chat_id, active_prompt)

    def web_link(self) -> None:
        if self.web_invite is None:
            self.telegram.send(self.chat_id, "Die Weboberfläche ist nicht aktiviert.")
            return
        from ..web.auth import PairingLimited

        try:
            text = self.web_invite()
        except PairingLimited as exc:
            text = str(exc)
        self.telegram.send(self.chat_id, text)

    def web_signout(self) -> None:
        if self.web_logout is None:
            self.telegram.send(self.chat_id, "Die Weboberfläche ist nicht aktiviert.")
            return
        count = self.web_logout()
        self.telegram.send(self.chat_id, f"🔐 Alle Geräte der Weboberfläche wurden abgemeldet ({count}).")

    def cancel(self) -> None:
        dialog = self.store.load_model("telegram-dialog", TelegramDialogState)
        if dialog is None or dialog.proposal_id is None:
            self.telegram.send(self.chat_id, "Keine aktive Bearbeitung. Offene Entscheidungen: /offen")
            return
        proposal = self.repository.load_current(dialog.mail_id, dialog.proposal_id)
        if (proposal is None or proposal.version != dialog.version or
                proposal.status not in {ProposalStatus.PENDING_CONFIRMATION, ProposalStatus.NEEDS_CLARIFICATION}):
            self.store.save("telegram-dialog", TelegramDialogState().model_dump(mode="json"))
            self.telegram.send(self.chat_id, "Die Bearbeitung ist nicht mehr aktuell. Offene Entscheidungen: /offen")
            return
        state = self.store.load_model(clarification_name(
            dialog.mail_id, dialog.proposal_id, dialog.version), ProposalClarificationState)
        if dialog.retry_required or (state is not None and state.authorized_answer is not None
                                     and state.answer_status != AnswerStatus.INVALID):
            self.telegram.send(self.chat_id, "Die Antwort ist bereits gespeichert. Die Verarbeitung kann hier "
                                             "nicht abgebrochen werden. Status: /status")
            return
        # Only the editing mode changes. Questions, content and version are preserved.
        snapshot = self.repository.load_version(dialog.mail_id, dialog.proposal_id, dialog.version)
        if snapshot is not None:
            proposal = proposal.model_copy(update={"status": snapshot.status})
        self.repository.save_revision(proposal)
        mail = self.repository.load_mail(proposal.source_mail_id)
        sender = mail.display_headers.sender if mail and mail.display_headers else "—"
        subject = mail.display_headers.subject if mail and mail.display_headers else "—"
        presentation = self.presenter.present(proposal, sender, subject)
        self.telegram.send(self.chat_id, "Bearbeitung geschlossen. Vorschlag unverändert; bitte erneut auswählen.")
        for part in presentation.parts[:-1]:
            self.telegram.send(self.chat_id, part)
        self.telegram.send(self.chat_id, presentation.parts[-1], presentation.reply_markup)
        self.store.save("telegram-dialog", TelegramDialogState().model_dump(mode="json"))
