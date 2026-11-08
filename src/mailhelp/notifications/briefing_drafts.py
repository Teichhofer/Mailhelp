"""Capture one briefing snapshot and append only to its durably bound IMAP account."""
from __future__ import annotations

from collections.abc import Callable
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime, parseaddr

from ..config import Settings
from ..mailbox.draft_writer import ImapDraftWriter
from ..review.views import ReviewViews
from ..storage import JsonStore
from .briefing_aggregate import BriefingAggregator
from .briefing_scheduler import BriefingRun, Outcome, target_mailbox
from .briefing_template import render_briefing
from .drafts import DraftTarget


def briefing_message(snapshot: dict[str, str], sender: str, run: BriefingRun) -> bytes:
    address = parseaddr(sender)[1]
    local, _, domain = address.rpartition("@")
    if not local or not domain or any(char in sender for char in "\r\n\x00"):
        raise ValueError("Ungültige eigene Postfachadresse")
    message = EmailMessage(policy=SMTP)
    message["From"], message["To"] = sender, address
    message["Subject"] = snapshot["subject"]
    message["Message-ID"] = f"<mailhelp-briefing-{run.id}@draft.local>"
    message["Date"] = format_datetime(run.scheduled_at)
    message.set_content(snapshot["text"])
    message.add_alternative(snapshot["html"], subtype="html")
    return message.as_bytes()


class BriefingDraftService:
    def __init__(self, store: JsonStore, settings: Callable[[], Settings], views: ReviewViews,
                 target: Callable[[int], tuple[str, DraftTarget] | None], base_url: Callable[[], str]):
        self.settings, self.target, self.base_url = settings, target, base_url
        self.aggregate = BriefingAggregator(store, views)
        self.writer = ImapDraftWriter()

    def _target(self, run: BriefingRun) -> tuple[Settings, str, DraftTarget]:
        cfg = self.settings()
        if (not cfg.briefings.enabled or not cfg.web.enabled or run.label not in cfg.briefings.times
                or run.mailbox != target_mailbox(cfg)):
            raise PermissionError("Briefing-Ablage inzwischen ausgeschaltet oder Ziel geändert")
        target = self.target(run.mailbox)
        if target is None:
            raise ValueError("Briefing-Postfach nicht mehr verfügbar")
        account, destination = target
        if run.account is not None and run.account != account:
            raise ValueError("Briefing-Postfachbindung hat sich geändert; kein erneuter Schreibzugriff")
        return cfg, account, destination

    def deliver(self, run: BriefingRun, checkpoint: Callable[[], None]) -> Outcome:
        cfg, account, target = self._target(run)
        if run.snapshot is None:
            content = self.aggregate.collect(run.window_start, run.scheduled_at)
            if cfg.briefings.skip_empty and content.empty:
                return "skipped_empty"
            run.snapshot = render_briefing(content, run.label, cfg.timezone, self.base_url())
        run.account = account
        checkpoint()
        content_bytes = briefing_message(run.snapshot, target.sender, run)
        if cfg.test_mode:
            return "simulated"
        def authorized() -> bool:
            self._target(run)  # Recheck current settings and account immediately before APPEND.
            return True
        with target.connection() as connection:
            outcome = self.writer.append(connection, target.folder, f"<mailhelp-briefing-{run.id}@draft.local>",
                                         content_bytes, run.draft, checkpoint, authorized)
        if outcome == "saved":
            return "saved"
        return "uncertain" if outcome == "uncertain" else "failed"
