"""Local commands, called only after the controller authorizes the sender."""
from ..models import AnswerStatus, Proposal, ProposalStatus, ProposalClarificationState, TelegramDialogState
from .persistence import clarification_name, proposal_name


HELP = (
    "Mailhelp – Hilfe\n"
    "/hilfe – Befehle anzeigen\n"
    "/status – Aktuelle Warte- und Bearbeitungsstände\n"
    "/offen – Offene Entscheidungen anzeigen\n"
    "/abbrechen – Unbeantwortete Bearbeitung schließen und Vorschlag anzeigen\n"
    "Wähle „Ändern“ für Korrekturen oder beantworte die konkrete Rückfrage. "
    "Jede überarbeitete Version muss erneut per Schaltfläche bestätigt werden. "
    "Solange eine Entscheidung offen ist, wartet die weitere Mailverarbeitung."
)


class TelegramCommands:
    def __init__(self, store, repository, presenter, telegram, chat_id, relevance):
        self.store, self.repository, self.presenter = store, repository, presenter
        self.telegram, self.chat_id, self.relevance = telegram, chat_id, relevance

    def handle(self, command: str) -> None:
        if command in {"/hilfe", "/start"}:
            self.telegram.send(self.chat_id, HELP)
        elif command in {"/status", "/offen"}:
            self.overview()
        elif command == "/abbrechen":
            self.cancel()
        else:
            self.telegram.send(self.chat_id, "Unbekannter Befehl. Verfügbare Befehle: /hilfe")

    def overview(self) -> None:
        lines = []
        for dialog in self.relevance.open():
            mail = self.repository.load_mail(dialog.mail_id)
            subject = mail.display_headers.subject if mail and mail.display_headers else "Mail ohne Betreff"
            lines.append(f"Relevanzentscheidung: {subject} · Version {dialog.version}")
        for name in self.store.names("proposal-"):
            proposal = self.store.load_model(name, Proposal)
            if name != proposal_name(proposal.source_mail_id, proposal.id):
                continue
            if proposal.status not in {ProposalStatus.PENDING_CONFIRMATION, ProposalStatus.NEEDS_CLARIFICATION}:
                continue
            state = self.store.load_model(clarification_name(
                proposal.source_mail_id, proposal.id, proposal.version), ProposalClarificationState)
            if state is not None and state.authorized_answer is not None and state.answer_status != AnswerStatus.INVALID:
                status = ("Verarbeitung pausiert; Betreiber muss den gespeicherten Zustand prüfen"
                          if "paused" in {state.interpretation_status, state.proposal_revision_status}
                          else "Antwort gespeichert; Verarbeitung läuft oder wird automatisch fortgesetzt")
            else:
                status = ("Warte auf Rückfrage/Korrektur" if proposal.status == ProposalStatus.NEEDS_CLARIFICATION
                          else "Warte auf Bestätigung oder Verwerfen")
            lines.append(f"„{proposal.title}“ · Version {proposal.version}: {status}")
        self.telegram.send(self.chat_id, "\n".join(lines) if lines else "Keine offene Telegram-Entscheidung.")

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
        if dialog.retry_required or (state is not None and state.authorized_answer is not None and state.answer_status != AnswerStatus.INVALID):
            self.telegram.send(self.chat_id, "Die Antwort ist bereits gespeichert. Die Verarbeitung kann hier nicht abgebrochen werden. Status: /status")
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
