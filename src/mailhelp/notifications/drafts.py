"""Versioned reply drafts; uncertain APPENDs are reconciled, never blindly retried."""
from __future__ import annotations

import hashlib
import imaplib
import re
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from email.errors import MessageError
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime, parseaddr
from threading import Lock
from typing import Any, NamedTuple, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field

from .. import state_names
from ..domain.prepared import MailHeaders, PreparedMail
from ..mailbox.draft_writer import ImapDraftWriter
from ..models import MailState
from ..storage import StateStore

# Reply intents offered on every mail page, with their German button labels.
INTENTS = {"accept": "Zusage", "decline": "Absage", "question": "Rückfrage"}
MAX_OPERATIONS = 50


class ReplyDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=1, max_length=8000)


# Reply markers of common mail programs (German, English, Nordic); forward markers stay.
_REPLY_PREFIX = re.compile(r"^(?:(?:re|aw|antw|antwort|sv|vs)(?:\[\d+\])?\s*:\s*)+", re.IGNORECASE)


def reply_subject(subject: str) -> str:
    """Exactly one "Re: " in front: "AW: Re: Angebot" becomes "Re: Angebot" (4.8, 19.2)."""
    return "Re: " + _REPLY_PREFIX.sub("", subject).strip()


def message(headers: MailHeaders, sender: str, text: str, message_id: str) -> bytes:
    result = EmailMessage(policy=SMTP)
    address = parseaddr(headers.reply_to or headers.sender)[1]
    local, _, domain = address.rpartition("@")
    if not local or not domain or any(c in address + sender for c in "\r\n\x00"):
        raise ValueError("Ungültiger Empfänger oder Absender")
    result["From"], result["To"] = sender, address
    # Untrusted subjects of older mail states may still contain line breaks; a header has one line.
    subject = " ".join(headers.subject.split())
    result["Subject"] = reply_subject(subject)
    parent = headers.message_id
    ids = re.findall(r"<[^<>\s]+@[^<>\s]+>", headers.references)[-20:]
    if re.fullmatch(r"<[^<>\s]+@[^<>\s]+>", parent):
        result["In-Reply-To"] = parent
        ids.append(parent)
    if ids:
        result["References"] = " ".join(dict.fromkeys(ids))
    result["Date"] = format_datetime(datetime.now(UTC))
    result["Message-ID"] = message_id
    result.set_content(text)
    try:
        return result.as_bytes()
    except MessageError as exc:
        raise ValueError("Ungültige Mailkopfzeilen; Entwurf nicht im Postfach gespeichert") from exc


Reply = tuple[str, ReplyDraft]


class DraftAnalyzer(Protocol):
    def draft_reply(self, mail: dict[str, Any], intent: str, personal_info: str, reason: str | None = ...) -> Reply: ...


AUTO_KEY = "automatic-draft"
AUTO_ACTOR = "system:auto-draft"


class DraftTarget(NamedTuple):
    """Where drafts of one mailbox are written: its own connection, sender and drafts folder."""

    connection: Callable[[], AbstractContextManager[imaplib.IMAP4]]
    sender: str
    folder: str


class DraftService:
    """One reply draft per mail, generated on request for a chosen reply intent."""

    def __init__(self, store: StateStore, authorize: Callable[[str], bool],
                 connection: Callable[[], AbstractContextManager[imaplib.IMAP4]], sender: str,
                 folder: str = "Drafts", test_mode: bool = False, analyzer: DraftAnalyzer | None = None,
                 personal_info: Callable[[], str] = lambda: "",
                 targets: Callable[[str], DraftTarget | None] | None = None,
                 mailbox_policy: Callable[[str], tuple[bool, str]] | None = None) -> None:
        self.store, self.authorize, self.connection = store, authorize, connection
        self.sender, self.folder, self.test_mode = sender, folder, test_mode
        # With several mailboxes (3.1): the target of the mailbox a mail came from, by account id.
        self.targets = targets
        self.mailbox_policy = mailbox_policy
        # 4.8: whether the mailbox of an account saves drafts without a click (auto_draft).
        self.auto_policy: Callable[[str], bool] = lambda account: False
        # Read on every click, so a changed setting applies without a restart.
        self.analyzer, self.personal_info = analyzer, personal_info
        # Serializes draft actions including the LLM and IMAP access, without the store lock.
        self._lock = Lock()

    def _target(self, source: MailState) -> DraftTarget:
        """The mailbox of the mail; never another one, so a reply cannot leave the wrong account."""
        if self.targets is None:
            return DraftTarget(self.connection, self.sender, self.folder)
        target = self.targets(source.imap.account_id)
        if target is None:
            raise ValueError("Das Postfach dieser Mail ist nicht mehr eingerichtet")
        return target

    def get(self, mail_id: str) -> dict[str, Any] | None:
        return cast(dict[str, Any] | None, self.store.load(state_names.draft(mail_id)))

    def available(self, mail_id: str) -> bool:
        """Replies need the mail text; retention removes it together with the draft text."""
        source = self.store.load_model(state_names.mail(mail_id), MailState)
        return (source is not None and source.mail is not None
                and (self.mailbox_policy is None or self.mailbox_policy(source.imap.account_id)[0]))

    def _save(self, mail_id: str, draft: dict[str, Any]) -> None:
        """Retention may have removed the mail meanwhile; its text never comes back."""
        with self.store.locked():
            source = self.store.load_model(state_names.mail(mail_id), MailState)
            if source is None or source.mail is None:
                draft["text"] = ""
            self.store.save(state_names.draft(mail_id), draft)

    @staticmethod
    def _remember(draft: dict[str, Any], key: str, digest: str) -> None:
        draft["operations"][key] = digest
        for old in list(draft["operations"])[:-MAX_OPERATIONS]:
            del draft["operations"][old]

    def _begin(self, actor: str, mail_id: str, version: int, key: str, digest: str,
               *, created: bool = False) -> tuple[MailState, dict[str, Any], bool]:
        """Authorize and load under the store lock; ``None`` means a finished replay."""
        if not re.fullmatch(r"[a-f0-9]{24}", mail_id) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", key):
            raise ValueError("Ungültige Identität")
        if not self.authorize(actor):
            raise PermissionError("Sitzung abgelaufen")
        source = self.store.load_model(state_names.mail(mail_id), MailState)
        if (
            source is not None
            and self.mailbox_policy is not None
            and not self.mailbox_policy(source.imap.account_id)[0]
        ):
            raise ValueError("Antwortentwürfe sind für dieses Postfach ausgeschaltet")
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

    def generate(self, actor: str, mail_id: str, version: int, key: str, intent: str) -> dict[str, Any]:
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
            call, reply = cast(DraftAnalyzer, self.analyzer).draft_reply(cast(dict[str, Any], source.mail),
                intent, self.personal_info() if self.mailbox_policy is None
                else self.mailbox_policy(source.imap.account_id)[1])
            if not self.authorize(actor):
                raise PermissionError("Sitzung abgelaufen")
            draft.update(version=version + 1, text=reply.text, intent=intent, status="editing",
                         call_id=call, error=None)
            self._remember(draft, key, digest)
            self._save(mail_id, draft)
            return draft

    def auto_draft(self, mail_id: str, reason: str | None) -> str:
        """Write a reply draft without a click (Planung 4.8, 19.4); returns the outcome.

        Only for a mailbox with ``smart_reply`` and ``auto_draft``. A draft the user has
        started is never replaced; a finished automatic one is not written again. An
        unclear earlier attempt is reconciled by its Message-ID before any new APPEND.
        """
        with self._lock:
            with self.store.locked():
                source = self.store.load_model(state_names.mail(mail_id), MailState)
                if source is None or source.mail is None:
                    return "skipped"
                account = source.imap.account_id
                allowed = self.mailbox_policy is None or self.mailbox_policy(account)[0]
                if not (allowed and self.auto_policy(account)):
                    return "skipped"
                draft = self.get(mail_id)
                if draft is not None and not (draft.get("auto") and draft["status"] == "uncertain"):
                    return "skipped"
            if draft is None:
                info = self.personal_info() if self.mailbox_policy is None else self.mailbox_policy(account)[1]
                call, reply = cast(DraftAnalyzer, self.analyzer).draft_reply(source.mail, "reply", info,
                                                                             reason=reason)
                draft = {"version": 1, "text": reply.text, "intent": "reply", "status": "editing",
                         "operations": {}, "auto": True, "call_id": call, "error": None}
                self._save(mail_id, draft)
            target = self._target(source)
            message_id = f"<mailhelp-{mail_id}-v1@draft.local>"
            content = message(cast(PreparedMail, source.prepared).headers, target.sender, draft["text"], message_id)
            digest = hashlib.sha256(repr((AUTO_ACTOR, "save", 1, draft["text"])).encode()).hexdigest()
            if self.test_mode:
                draft.update(status="simulated", error=None)
            else:
                with target.connection() as connection:
                    self._append(connection, target.folder, None, mail_id, AUTO_KEY, digest, draft, message_id,
                                 content, auto_account=account)
            self._remember(draft, AUTO_KEY, digest)
            self._save(mail_id, draft)
            return cast(str, draft["status"])

    def cancel(self, actor: str, mail_id: str, version: int, key: str) -> dict[str, Any]:
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

    def act(self, actor: str, mail_id: str, version: int, key: str, text: str) -> dict[str, Any]:
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
                target = self._target(source)
                message_id = f"<mailhelp-{mail_id}-v{version}@draft.local>"
                content = message(cast(PreparedMail, source.prepared).headers, target.sender, text, message_id)
                if self.test_mode:
                    draft.update(status="simulated", error=None)
                    self._remember(draft, key, digest)
                    self.store.save(state_names.draft(mail_id), draft)
                    return draft
            with target.connection() as connection:
                self._append(connection, target.folder, actor, mail_id, key, digest, draft, message_id, content)
            self._remember(draft, key, digest)
            self._save(mail_id, draft)
            return draft

    def _append(self, connection: imaplib.IMAP4, drafts_folder: str, actor: str | None, mail_id: str, key: str,
                digest: str, draft: dict[str, Any], message_id: str, content: bytes,
                *, auto_account: str | None = None) -> None:
        def checkpoint() -> None:
            self._remember(draft, key, digest)
            self._save(mail_id, draft)

        def authorized() -> bool:
            if actor is not None and not self.authorize(actor):
                raise PermissionError("Sitzung abgelaufen")
            return auto_account is None or self.auto_policy(auto_account)

        ImapDraftWriter().append(connection, drafts_folder, message_id, content, draft, checkpoint, authorized)
