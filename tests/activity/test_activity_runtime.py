"""Composition of activity reports in the 2.0 runtime: only with switch and both prompts, read-only IMAP."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from activity_fakes import Model, activity_prompts
from pydantic import SecretStr
from shared_application import Log, settings

from mailhelp.analysis import Analyzer
from mailhelp.config import ImapCredentials, Secrets
from mailhelp.experience import ExperienceRuntime
from mailhelp.imap import ListedMailbox

SECRETS = Secrets.model_construct(imap={1: ImapCredentials(username="me@test", password=SecretStr("fake"))})


def application(web, tmp_path, prompts):
    cfg = settings(tmp_path)
    cfg.activity_report.enabled = True
    cfg.imap.folders = ["INBOX", "Papierkorb", "Schule"]
    configuration = activity_prompts()
    configuration.prompts = {name: value for name, value in configuration.prompts.items() if name in prompts}
    return NS(settings=cfg, store=web.store, logger=Log(), calendar=None, todoist=None,
              telegram=NS(send=lambda *a: None), analyzer=Analyzer(Model(), configuration))


@pytest.mark.parametrize("prompts", [[], ["activity_relevance"], ["activity_events"]])
def test_reports_stay_off_without_both_prompts(web, tmp_path, prompts):
    runtime = ExperienceRuntime(application(web, tmp_path, prompts), NS(site=web.site, auth=web.auth), SECRETS)
    assert runtime.activity is None and web.site.activity.service is None
    runtime.tick()


def test_runtime_runs_reports_and_suggests_folders_from_a_closed_session(web, tmp_path, monkeypatch):
    sessions = []

    class Reader:
        def __init__(self, *args, **kwargs):
            sessions.append(self)
            self.closed = False

        def list_folders(self):
            return [ListedMailbox("INBOX", frozenset()), ListedMailbox("Papierkorb", frozenset(), "trash"),
                    ListedMailbox("Schule", frozenset())]

        def close(self):
            self.closed = True

    monkeypatch.setattr("mailhelp.experience.ImapReader", Reader)
    app = application(web, tmp_path, ["activity_relevance", "activity_events"])
    app.settings.activity_report.export_mails_without_events = False
    runtime = ExperienceRuntime(app, NS(site=web.site, auth=web.auth), SECRETS)
    pages = web.site.activity
    assert runtime.activity is not None and pages.service is runtime.activity.service
    assert pages.with_unscheduled is False
    assert pages.suggest_folders() == ["INBOX", "Schule"] and sessions[0].closed
    # Changed settings reach the running report with the next minute tick.
    changed = app.settings.model_copy(deep=True)
    changed.activity_report.max_mails = 5
    changed.activity_report.export_mails_without_events = True
    app.settings = changed
    runtime.tick()
    assert runtime.activity.settings.activity_report.max_mails == 5 and pages.with_unscheduled is True
    assert runtime.activity.llm_calls_per_minute() == changed.limits.llm_calls_per_minute
    assert pages.available_folders() == ["INBOX", "Papierkorb", "Schule"]
    assert runtime.activity.analyzer.personal_info() == changed.personal_info
    runtime.activity.tick = lambda: False
    runtime.tick = runtime.stop_event.set
    runtime.start()
    runtime.stop()
    assert runtime.activity.stop_event.is_set() and not runtime.activity.thread.is_alive()
