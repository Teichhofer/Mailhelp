"""Versioned reply drafts; uncertain APPENDs are reconciled, never blindly retried."""
from __future__ import annotations
import hashlib
import imaplib
import re
from datetime import datetime, timezone
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime, parseaddr
from threading import Lock
from pydantic import BaseModel, ConfigDict, Field
from .imap import _mailbox_argument
from .models import MailState
from . import state_names


# Reply intents offered on every mail page, with their German button labels.
INTENTS = {"accept": "Zusage", "decline": "Absage", "question": "Rückfrage"}
MAX_OPERATIONS = 50


class ReplyDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=1, max_length=8000)


def message(headers, sender, text, message_id):
    result = EmailMessage(policy=SMTP)
    address = parseaddr(headers.get("reply_to") or headers.get("from", ""))[1]
    if not address or "@" not in address or any(c in address + sender for c in "\r\n\x00"):
        raise ValueError("Ungültiger Empfänger oder Absender")
    result["From"], result["To"] = sender, address
    subject = headers.get("subject", "")
    result["Subject"] = subject if subject.lower().startswith("re:") else "Re: " + subject
    parent = headers.get("message_id", "")
    ids = re.findall(r"<[^<>\s]+@[^<>\s]+>", headers.get("references", ""))[-20:]
    if re.fullmatch(r"<[^<>\s]+@[^<>\s]+>", parent):
        result["In-Reply-To"] = parent
        ids.append(parent)
    if ids:
        result["References"] = " ".join(dict.fromkeys(ids))
    result["Date"] = format_datetime(datetime.now(timezone.utc))
    result["Message-ID"] = message_id
    result.set_content(text)
    return result.as_bytes()


class DraftService:
    """One reply draft per mail, generated on request for a chosen reply intent."""

    def __init__(self, store, authorize, connection, sender, folder="Drafts", test_mode=False, analyzer=None,
                 personal_info=lambda: ""):
        self.store, self.authorize, self.connection = store, authorize, connection
        self.sender, self.folder, self.test_mode = sender, folder, test_mode
        # Read on every click, so a changed setting applies without a restart.
        self.analyzer, self.personal_info = analyzer, personal_info
        # Serializes draft actions including the LLM and IMAP access, without the store lock.
        self._lock = Lock()

    def get(self, mail_id):
        return self.store.load(state_names.draft(mail_id))

    def available(self, mail_id):
        """Replies need the mail text; retention removes it together with the draft text."""
        source = self.store.load_model(state_names.mail(mail_id), MailState)
        return source is not None and source.mail is not None

    def _save(self, mail_id, draft):
        """Retention may have removed the mail meanwhile; its text never comes back."""
        with self.store.locked():
            source = self.store.load_model(state_names.mail(mail_id), MailState)
            if source is None or source.mail is None:
                draft["text"] = ""
            self.store.save(state_names.draft(mail_id), draft)

    @staticmethod
    def _remember(draft, key, digest):
        draft["operations"][key] = digest
        for old in list(draft["operations"])[:-MAX_OPERATIONS]:
            del draft["operations"][old]

    def _begin(self, actor, mail_id, version, key, digest, *, created=False):
        """Authorize and load under the store lock; ``None`` means a finished replay."""
        if not re.fullmatch(r"[a-f0-9]{24}", mail_id) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", key):
            raise ValueError("Ungültige Identität")
        if not self.authorize(actor):
            raise PermissionError("Sitzung abgelaufen")
        source = self.store.load_model(state_names.mail(mail_id), MailState)
        draft = self.get(mail_id)
        if draft is None and created:
            draft = {"version": 0, "text": "", "status": "discarded", "operations": {}}
        if source is None or source.mail is None or draft is None:
            raise ValueError("Mail oder Entwurf nicht vorhanden")
        operation = draft["operations"].get(key)
        if operation is not None and operation != digest:
            raise ValueError("Idempotenzkonflikt")
        if operation is not None and draft["status"] != "uncertain":
            return source, draft, True
        if draft["version"] != version:
            raise ValueError("Veraltete Entwurfsversion")
        return source, draft, False

    def generate(self, actor, mail_id, version, key, intent):
        """One LLM call per click; a replayed click returns the stored draft."""
        if intent not in INTENTS:
            raise ValueError("Unbekannte Antwortart")
        digest = hashlib.sha256(repr((actor, "generate", version, intent)).encode()).hexdigest()
        with self._lock:
            with self.store.locked():
                source, draft, replay = self._begin(actor, mail_id, version, key, digest, created=True)
                if replay:
                    return draft
                if draft["status"] == "uncertain":
                    raise ValueError("Schreibresultat unklar; zuerst den Entwurf erneut speichern")
            # The paid call runs without the store lock; the session is checked again afterwards.
            call, reply = self.analyzer.draft_reply(source.mail, intent, self.personal_info())
            if not self.authorize(actor):
                raise PermissionError("Sitzung abgelaufen")
            draft.update(version=version + 1, text=reply.text, intent=intent, status="editing",
                         call_id=call, error=None)
            self._remember(draft, key, digest)
            self._save(mail_id, draft)
            return draft

    def cancel(self, actor, mail_id, version, key):
        """Discard the open draft locally; nothing was written to the mailbox."""
        digest = hashlib.sha256(repr((actor, "cancel", version)).encode()).hexdigest()
        with self._lock, self.store.locked():
            _, draft, replay = self._begin(actor, mail_id, version, key, digest)
            if replay:
                return draft
            if draft["status"] != "editing":
                raise ValueError("Nur ein offener Entwurf kann verworfen werden")
            draft.update(version=version + 1, text="", status="discarded", error=None)
            self._remember(draft, key, digest)
            self.store.save(state_names.draft(mail_id), draft)
            return draft

    def act(self, actor, mail_id, version, key, text):
        """Save exactly the submitted text of this version as a draft in the mailbox."""
        ReplyDraft(text=text)
        if not text.strip():
            raise ValueError("Leerer Entwurf")
        digest = hashlib.sha256(repr((actor, "save", version, text)).encode()).hexdigest()
        with self._lock:
            with self.store.locked():
                source, draft, replay = self._begin(actor, mail_id, version, key, digest)
                if replay:
                    return draft
                if draft["status"] == "discarded":
                    raise ValueError("Entwurf wurde verworfen")
                if draft["status"] in {"saved", "simulated"}:
                    if text != draft["text"]:
                        raise ValueError("Diese Version liegt bereits im Postfach")
                    return draft
                if draft["status"] == "uncertain" and text != draft["text"]:
                    raise ValueError("Schreibresultat unklar; den Text unverändert erneut speichern")
                # An unwritten version may still change: a refused APPEND wrote nothing.
                # Kept before the mailbox access so a failure never loses the edits.
                draft["text"] = text
                self.store.save(state_names.draft(mail_id), draft)
                message_id = f"<mailhelp-{mail_id}-v{version}@draft.local>"
                content = message(source.mail["headers"], self.sender, text, message_id)
                if self.test_mode:
                    draft.update(status="simulated", error=None)
                    self._remember(draft, key, digest)
                    self.store.save(state_names.draft(mail_id), draft)
                    return draft
            with self.connection() as connection:
                self._append(connection, actor, mail_id, key, digest, draft, message_id, content)
            self._remember(draft, key, digest)
            self._save(mail_id, draft)
            return draft

    def _append(self, connection, actor, mail_id, key, digest, draft, message_id, content):
        """Reconcile first; append only if the draft is provably missing from the folder."""
        folder = _mailbox_argument(self.folder)
        status, _ = connection.select(folder, readonly=True)
        if status != "OK":
            raise ValueError("Entwurfsordner nicht verfügbar")
        status, matches = connection.uid("search", None, "HEADER", "Message-ID", message_id)
        if status != "OK":
            raise ValueError("Entwurfsabgleich nicht möglich")
        if any(matches):
            draft.update(status="saved", error=None)
            return
        draft.update(status="uncertain", error=None)
        self._remember(draft, key, digest)
        self._save(mail_id, draft)
        if not self.authorize(actor):
            raise PermissionError("Sitzung abgelaufen")
        try:
            status, _ = connection.append(folder, r"(\Draft \Seen)", None, content)
        except (OSError, EOFError, imaplib.IMAP4.abort):
            return
        except imaplib.IMAP4.error:
            status = "BAD"
        if status == "OK":
            draft["status"] = "saved"
        else:
            # A definite refusal wrote nothing; the user may correct the folder and confirm again.
            draft.update(status="editing", error="Der Mailserver hat das Speichern abgelehnt.")
