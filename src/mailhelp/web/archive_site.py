"""Shared state of the archive, history, editing, settings and stop pages (Planung 3.3, pillar 2).

Each area has its own site class; this one holds what they share: the configuration
service, metrics, the stop handshake, the model overview, the archive queries and the
command queue.
"""
from __future__ import annotations

from urllib.parse import parse_qs

from ..review.inbox import CommandConflict, CommandInboxFull
from ..review.queries import ArchiveQueries
from .history_site import HistorySite
from .http import Response
from .mail_archive_site import MailArchiveSite
from .proposal_edit_site import ProposalEditSite
from .settings_site import SettingsSite
from .shutdown_site import ShutdownSite


class ArchiveSite:
    def __init__(self, site, configuration=None, metrics=None, lifecycle=None, models=None):
        self.site, self.configuration, self.metrics, self.lifecycle = site, configuration, metrics, lifecycle
        self.models = models or []
        self.queries = ArchiveQueries(site.views.store, site.configured_timezone)
        self.mail_archive = MailArchiveSite(self)
        self.history = HistorySite(self)
        self.proposal_edit = ProposalEditSite(self)
        self.settings = SettingsSite(self)
        self.shutdown = ShutdownSite(self)

    def parameters(self, request):
        values = parse_qs(request.query, max_num_fields=20)
        if any(len(value) != 1 for value in values.values()):
            raise ValueError("Doppelte Filter")
        return {key: value[0] for key, value in values.items()}

    def queue(self, request, command):
        try:
            entry, _ = self.site.commands.submit(command)
        except (CommandConflict, CommandInboxFull):
            return self.site._reply(request, 409, "Bereits anders eingereicht oder Warteschlange voll.")
        return Response.redirect(f"/aktion/{entry.id}")
