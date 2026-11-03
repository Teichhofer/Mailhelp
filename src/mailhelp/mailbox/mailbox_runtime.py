"""Add activated IMAP mailboxes between mail cycles (3.5); running mailboxes stay untouched."""
from __future__ import annotations

from contextlib import ExitStack

from ..config import ImapSettings
from .connection_runtime import PendingConnections


class MailboxRuntime(PendingConnections):
    area = "imap"

    def __init__(self, app, resources, secrets):
        super().__init__(app, resources)
        # The credentials shared with diagnostics, drafts and activity reports of this process.
        self.secrets = secrets

    def _apply(self, pending):
        from ..llm.adapter import RetryPolicy
        from ..runtime.composition import _mailbox_labels
        from .imap import ImapReader, mailbox_account_id, reader_arguments
        from .mailbox_run import MailboxSource
        configured, secrets = pending
        app = self.app
        running = {source.mailbox.id for source in app.sources}
        added = [box for box in configured.imap.enabled_mailboxes() if box.id not in running]
        current = app.settings.imap
        imap = ImapSettings.model_validate({
            "batch_size": current.batch_size, "global_newest_first": current.global_newest_first,
            "mailboxes": [box.model_dump() for box in (*current.configured_mailboxes(), *added)]})
        settings = app.settings.model_copy(update={"imap": imap})
        timeouts = settings.timeouts.imap
        with ExitStack() as resources:
            sources = []
            for mailbox in added:
                credentials = secrets.imap_credentials(mailbox.id)
                address, options = reader_arguments(mailbox, credentials)
                policy = RetryPolicy(timeouts.retries, timeouts.initial_backoff_seconds,
                                     timeouts.max_backoff_seconds, app.stop_event.wait)
                # Connects and signs in here; a failure leaves the running mailboxes as they are.
                reader = ImapReader(*address, timeouts.timeout_seconds, **options, policy=policy,
                                    logger=app.logger, batch_size=imap.batch_size)
                resources.callback(reader.close)
                sources.append(MailboxSource(mailbox, reader))
            numbers = {**app.orchestrator.mailbox_numbers,
                       **{source.account_id: source.mailbox.id for source in sources}}
            app.orchestrator.configure_mailboxes(settings, app.orchestrator.mailbox_prompts, numbers,
                                                app.orchestrator.mailbox_jev)
            self.secrets.imap.update({box.id: secrets.imap_credentials(box.id) for box in added})
            app.sources.extend(sources)
            app.settings = app.mailbox.settings = settings
            app.configuration.active = app.configuration.active.model_copy(update={"imap": imap})
            app.logger.metrics.mailbox_numbers = {
                **app.logger.metrics.mailbox_numbers,
                **{mailbox_account_id(source.mailbox, self.secrets.imap_credentials(source.mailbox.id)):
                   source.mailbox.id for source in sources}}
            iserv = app.iserv.sources if app.iserv is not None else []
            app.dialog.presenter.mailbox_of = _mailbox_labels(
                app.store, app.sources, {source.reader.account_id: source.account.label for source in iserv})
            if app.experience is not None:
                app.experience.add_mailboxes(settings, self.secrets)
            self.resources.enter_context(resources.pop_all())
        app.logger.event("INFO", "imap", "mailboxes_activated", count=len(sources))


__all__ = ["MailboxRuntime"]
