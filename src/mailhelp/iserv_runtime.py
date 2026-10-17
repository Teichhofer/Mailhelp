"""Replace IServ adapters only between mail cycles, never during processing."""
from __future__ import annotations

from contextlib import ExitStack
from threading import Lock


class IServRuntime:
    def __init__(self, app, resources):
        self.app, self.resources = app, resources
        self.lock = Lock()
        self.pending = None

    def request(self, settings, secrets):
        with self.lock:
            self.pending = settings, secrets

    def apply_pending(self) -> None:
        with self.lock:
            pending, self.pending = self.pending, None
        if pending is None:
            return
        try:
            self._apply(pending)
        except Exception:
            with self.lock:
                if self.pending is None:
                    self.pending = pending
            self.app.logger.event("ERROR", "iserv", "activation_failed")

    def _apply(self, pending):
        from .composition import _build_iserv, _mailbox_labels
        from .iserv import IServRunService
        configured, secrets = pending
        app = self.app
        settings = app.settings.model_copy(update={"iserv": configured.iserv})
        with ExitStack() as resources:
            sources = _build_iserv(settings, secrets, resources)
            service = IServRunService(app.store, app.logger, sources, app._process_mail, app.stop_event)
            old = set(app.mailbox.resume_readers)
            numbers = {key: value for key, value in app.orchestrator.mailbox_numbers.items() if key not in old}
            numbers.update({source.reader.account_id: source.account.mailbox for source in sources})
            app.orchestrator.configure_mailboxes(settings, app.orchestrator.mailbox_prompts, numbers,
                                                app.orchestrator.mailbox_jev)
            app.orchestrator.always_relevant = frozenset(service.readers())
            app.settings = app.mailbox.settings = settings
            app.configuration.active = app.configuration.active.model_copy(update={"iserv": settings.iserv})
            app.iserv = service
            app.mailbox.resume_readers = service.readers()
            app.logger.metrics.mailbox_numbers = numbers
            app.dialog.presenter.mailbox_of = _mailbox_labels(
                app.store, app.sources, {source.reader.account_id: source.account.label for source in sources})
            previous = self.resources
            self.resources = resources.pop_all()
            previous.close()
        app.logger.event("INFO", "iserv", "accounts_activated", count=len(sources))

    def close(self):
        self.resources.close()
