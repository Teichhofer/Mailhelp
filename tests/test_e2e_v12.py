"""Version 1.2 end to end: a real fixture mail through analysis, web pages and actions.

External services and the LLM are simulated; nothing leaves the process.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from mailhelp.analysis import Analyzer
from mailhelp.config import PromptConfig, PromptStep, Settings, TargetSettings, Topic
from mailhelp.imap import FetchedMail
from mailhelp.orchestrator import Orchestrator
from mailhelp.review.inbox import CommandStatus
from mailhelp.storage import JsonStore
from test_e2e_simulated import NachholterminRouter
from test_web_actions import Web
from test_web_v12 import configure

FIXTURE = Path(__file__).parent / "fixtures" / "nachholtermin_bildungsplannovellierung.eml"
STEPS = ("relevance", "summary", "action_router", "task_extraction", "event_extraction",
         "mail_question_resolution", "telegram_answer_interpretation", "telegram_answer_clarification",
         "proposal_revision", "learning_classification", "learning_abstraction", "calendar_duplicate")


class TopicRouter(NachholterminRouter):
    """Answers relevance with the first configured topic it is given."""

    def __init__(self):
        super().__init__()
        self.topics = []

    def complete(self, model, parameters, system, payload, **metadata):
        if system == "relevance":
            data = payload if isinstance(payload, dict) else json.loads(payload)
            ids = [topic["id"] for topic in data["topics"]]
            self.topics.append(ids)
            self.calls.append(system)
            return "relevance-call", {"decision": "relevant", "topic_ids": ids[:1],
                                      "reason": "Ein konkreter Termin ist enthalten."}
        return super().complete(model, parameters, system, payload, **metadata)


def another_mail() -> bytes:
    """The fixture as a different message (new ID and subject)."""
    return (FIXTURE.read_bytes()
            .replace(b"nachholtermin-20260923@", b"zweiter-termin-20260930@")
            .replace(b"Subject: Nachholtermin:", b"Subject: Zweiter Termin:"))


class NoActionRouter(NachholterminRouter):
    """A relevant mail with a summary but nothing to create."""

    def complete(self, model, parameters, system, payload, **metadata):
        if system == "action_router":
            self.calls.append(system)
            return "router-call", {"action_state": "none", "task_count": 0, "event_count": 0,
                                   "reason": "Nur zur Information."}
        return super().complete(model, parameters, system, payload, **metadata)


def analyse(store, router, uid=23, topics=None):
    prompts = PromptConfig(defaults={"model": "fake", "parameters": {}},
                           prompts={step: PromptStep(system_prompt=step) for step in STEPS})
    web = Web(store)
    orchestrator = Orchestrator(
        Analyzer(router, prompts), store, web.dialog, 2,
        topics or [Topic(id="arbeit", name="Arbeit", enabled=True, description="Beruf")], 100_000,
        targets=TargetSettings(todoist_project="project", google_calendar="calendar"),
        user_timezone="Europe/Berlin")
    fetched = FetchedMail("INBOX", 7, uid, FIXTURE.read_bytes(), "1" * 24,
                          datetime(2026, 9, 22, 7, 15, tzinfo=timezone.utc))
    return web, orchestrator, orchestrator.process(fetched)


def fields(web, path, action, **match):
    html = web.browser.request("GET", path).body.decode()
    for target, block in re.findall(r'<form method="post" action="([^"]+)"[^>]*>(.*?)</form>', html, re.S):
        values = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', block))
        if target == action and all(values.get(key) == value for key, value in match.items()):
            return values
    raise AssertionError(f"Formular {action} {match} fehlt")


def test_a_relevant_mail_without_action_is_found_with_its_summary(tmp_path):
    with JsonStore(tmp_path) as store:
        web, _, result = analyse(store, NoActionRouter())
        mail_id = result.state["id"]
        assert result.state["proposals"] == []
        listing = web.browser.request("GET", "/mails?state=no_action&relevance=relevant").body.decode()
        assert "1 gespeicherte Vorgänge" in listing and f"/mail/{mail_id}" in listing
        detail = web.browser.request("GET", f"/mail/{mail_id}").body.decode()
        assert "Ein synthetischer Nachholtermin wurde angekündigt." in detail
        assert "Arbeit" in detail and "Ein konkreter Termin ist enthalten." in detail


def test_a_proposal_edited_in_the_form_is_written_only_after_its_own_confirmation(tmp_path):
    with JsonStore(tmp_path) as store:
        web, _, result = analyse(store, NachholterminRouter())
        proposal = result.state["proposals"][0]
        mail_id, proposal_id = proposal["source_mail_id"], proposal["id"]
        edit = f"/vorschlag/{mail_id}/{proposal_id}/bearbeiten"
        form = fields(web, edit, edit)
        saved = web.browser.request("POST", edit, {**form, "title": "Auftakt Bildungsplan (Raum 4)"})
        assert saved.status == 303
        web.run()
        current = store.load(f"proposal-{mail_id}-{proposal_id}")
        assert (current["version"], current["title"]) == (2, "Auftakt Bildungsplan (Raum 4)")
        assert web.writer.created == 0, "Speichern allein darf nichts anlegen"
        # The old version is history and read only; the new one needs its own confirmation.
        old = web.browser.request("GET", f"/vorschlag/{mail_id}/{proposal_id}/version/1").body.decode()
        assert "Historische Version" in old and 'action="/aktion"' not in old
        confirm = fields(web, "/", "/aktion", kind="confirm", proposal_id=proposal_id)
        assert confirm["version"] == "2"
        web.submit(confirm)
        web.run()
        assert web.writer.created == 1 and web.writer.versions == [2]
        history = web.browser.request("GET", "/verlauf").body.decode()
        assert "Version 2" in history and "web" in history


def test_topics_saved_in_the_web_apply_only_to_new_mails(tmp_path):
    router = TopicRouter()
    with JsonStore(tmp_path / "data") as store:
        web, orchestrator, first = analyse(store, router)
        service, *_ = configure(web, tmp_path)
        service.activate_topics = orchestrator.change_topics
        old_proposal = store.load(f"proposal-{first.state['id']}-{first.state['proposals'][0]['id']}")
        form = fields(web, "/themen", "/themen/speichern", original_id="")
        response = web.browser.request("POST", "/themen/speichern", {
            **form, "id": "verein", "name": "Verein", "description": "Vereinspost", "enabled": "true",
            "examples": "", "exclusions": "", "confirm": "yes"})
        assert response.status == 303
        web.run()
        assert [topic.id for topic in orchestrator.topics] == ["school", "verein"]
        assert store.load(f"analysis-{first.state['id']}")["topics"] == {"arbeit": "Arbeit"}
        second = orchestrator.process(FetchedMail("INBOX", 7, 24, another_mail(), "1" * 24,
                                                  datetime(2026, 9, 29, 8, tzinfo=timezone.utc)))
        assert second.state["duplicate"]["outcome"] == "new"
        # The first mail was analysed with the old topics, the new mail with the new ones.
        assert router.topics[0] == ["arbeit"] and router.topics[1] == ["school", "verein"]
        assert store.load(f"analysis-{second.state['id']}")["topics"] == {"school": "Schule", "verein": "Verein"}
        assert store.load(f"analysis-{first.state['id']}")["topics"] == {"arbeit": "Arbeit"}
        assert store.load(f"proposal-{first.state['id']}-{first.state['proposals'][0]['id']}") == old_proposal


def test_settings_saved_then_stopped_and_taken_over_after_a_restart(tmp_path):
    with JsonStore(tmp_path / "data") as store:
        web, *_ = analyse(store, NachholterminRouter())
        service, metrics, lifecycle, active, calls = configure(web, tmp_path)
        live = fields(web, "/einstellungen", "/einstellungen/speichern", name="poll_interval_seconds")
        web.browser.request("POST", "/einstellungen/speichern", {**live, "value": "45", "confirm": "yes"})
        web.run()
        later = fields(web, "/einstellungen", "/einstellungen/speichern", name="timeouts.imap.timeout_seconds")
        web.browser.request("POST", "/einstellungen/speichern", {**later, "value": "55", "confirm": "yes"})
        web.run()
        assert active[-1].poll_interval_seconds == 45
        assert service.active.timeouts.imap.timeout_seconds != 55
        page = web.browser.request("GET", "/einstellungen").body.decode()
        assert "Gespeichert: 55 · gespeichert – wirkt erst nach einem Neustart" in page
        stop = fields(web, "/einstellungen/beenden", "/einstellungen/beenden")
        answer = web.browser.request("POST", "/einstellungen/beenden", stop)
        answer.after_send()
        assert calls == ["stop"] and lifecycle.state == "stopping"
        # Restart: the saved file is the new configuration, the stop is not repeated.
        restarted = Settings.model_validate(yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8")))
        assert (restarted.poll_interval_seconds, restarted.timeouts.imap.timeout_seconds) == (45, 55)
        assert calls == ["stop"] and web.writer.created == 0
        assert all(entry.status == CommandStatus.DONE for entry in web.commands._entries())
