"""Shared state of the archive, history, editing, settings and stop pages (Planung 3.3, pillar 2).

Each area has its own site class; this one holds what they share: the configuration
service, metrics, the stop handshake, the model overview, the archive queries and the
command queue.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qs

from ..configuration import AdminCommand, ConfigurationService
from ..review.commands import ReviewCommand
from ..review.inbox import CommandConflict, CommandInboxFull
from ..review.queries import ArchiveQueries
from ..runtime.lifecycle import Lifecycle
from ..runtime.metrics import MetricsRecorder
from .history_site import HistorySite
from .http import Request, Response
from .mail_archive_site import MailArchiveSite
from .proposal_edit_site import ProposalEditSite
from .settings_site import SettingsSite
from .shutdown_site import ShutdownSite

if TYPE_CHECKING:
    from .site import MailhelpSite


class ArchiveSite:
    def __init__(self, site: MailhelpSite, configuration: ConfigurationService | None = None,
                 metrics: MetricsRecorder | None = None, lifecycle: Lifecycle | None = None,
                 models: list[tuple[str, str, str, str]] | None = None):
        self.site, self.configuration, self.metrics, self.lifecycle = site, configuration, metrics, lifecycle
        self.models = models or []
        self.queries = ArchiveQueries(site.views.store, site.configured_timezone)
        self.mail_archive = MailArchiveSite(self)
        self.history = HistorySite(self)
        self.proposal_edit = ProposalEditSite(self)
        self.settings = SettingsSite(self)
        from .help_site import HelpSite
        self.help = HelpSite(self.site)
        self.shutdown = ShutdownSite(self)

    def parameters(self, request: Request) -> dict[str, str]:
        values = parse_qs(request.query, max_num_fields=20)
        if any(len(value) != 1 for value in values.values()):
            raise ValueError("Doppelte Filter")
        return {key: value[0] for key, value in values.items()}

    def queue(self, request: Request, command: ReviewCommand | AdminCommand) -> Response:
        try:
            entry, _ = self.site.commands.submit(command)
        except (CommandConflict, CommandInboxFull):
            return self.site._reply(request, 409, "Bereits anders eingereicht oder Warteschlange voll.")
        return Response.redirect(f"/aktion/{entry.id}")
