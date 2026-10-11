"""1.2 behaviour that was implemented but not yet verified by a test."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Event
from types import SimpleNamespace

import pytest
import yaml

from mailhelp.application import Application
from mailhelp.configuration import AdminCommand, AdminKind, file_hash
from mailhelp.decision_test import ComparisonRecorder
from mailhelp.metrics import MetricsRecorder, MetricsSettings, server_electricity
from mailhelp.models import MailState, ProcessingError, RelevanceDialog
from mailhelp.review.archive import record_event, record_relevance
from mailhelp.review.commands import CommandKind
from mailhelp.review.editing import ProposalEditPatch, edit_proposal
from mailhelp.review.results import ResultStatus
from test_application import Log, Orch, settings as app_settings
from test_review import command
from test_web_actions import web  # noqa: F401  (fixture)
from test_web_v12 import configure
from web_scenario import mail_id, proposal


def test_exchange_rate_needs_its_date():
    with pytest.raises(ValueError, match="gemeinsam"):
        MetricsSettings(usd_per_eur=1.08)
    assert MetricsSettings(usd_per_eur=1.08, exchange_rate_date="2026-10-01").usd_per_eur == 1.08


def test_server_electricity_charges_overlapping_calls_once():
    """Parallel calls share the server: overlapping seconds are charged once, at the newest assumption."""
    rows = [
        {"start": 0, "end": 3600, "power_watts": 300, "electricity_price": 0.30},
        {"start": 1800, "end": 5400, "power_watts": 600, "electricity_price": 0.30},
        {"start": 10, "end": 10, "power_watts": 9999, "electricity_price": 9},  # no duration
    ]
    # 0–1800 s at 300 W, 1800–5400 s at 600 W (newest active call), 0.30 EUR/kWh.
    assert server_electricity(rows) == Decimal("0.045") + Decimal("0.18")
    assert server_electricity([]) == 0


def test_runtime_snapshot_follows_processing_steps(tmp_path):
    changes = []
    metrics = MetricsRecorder(tmp_path / "llm.jsonl", MetricsSettings())
    metrics.changed = lambda: changes.append(metrics.runtime()["stage"])
    metrics.observe("processing_started", {"mail_id": "a" * 24})
    metrics.observe("state_persisted", {"mail_id": "a" * 24, "state": {"preparation": "completed",
                                                                        "relevance": "pending"}})
    metrics.observe("state_persisted", {"mail_id": "a" * 24, "state": {"relevance": "pending"}})
    metrics.observe("state_persisted", {"mail_id": "a" * 24, "awaiting_relevance": True, "state": {}})
    metrics.observe("state_persisted", {"mail_id": "a" * 24, "failed": True, "state": {}})
    metrics.observe("state_persisted", {"mail_id": "a" * 24, "state": {"completion": "completed"}})
    metrics.observe("request_completed", {"service": "imap"})
    metrics.observe("request_completed", {})
    metrics.observe("idle_started", {"delay_seconds": 60})
    runtime = metrics.runtime()
    assert changes == ["preparation", "relevance", "waiting_for_user", "failed", "idle", "idle"]
    assert runtime["stage"] == "idle" and runtime["elapsed"] >= 0
    assert datetime.fromisoformat(runtime["next_poll"]) > datetime.now(timezone.utc)
    # Only known success events count; an event without a service is not a contact.
    assert set(runtime["contacts"]) == {"IMAP-Postfach"}


def test_comparison_metrics_failures_are_counted_not_raised(tmp_path):
    recorder = ComparisonRecorder(tmp_path / "vergleich.jsonl", ("geheim",))

    class Broken:
        failures = 0

        def observe(self, event, context):
            raise OSError("voll")

    recorder.metrics = Broken()
    recorder.event("INFO", "decisions", "request_started", call_id="x")
    assert recorder.metrics.failures == 1 and recorder.entries


def test_live_settings_reach_both_metric_recorders(tmp_path):
    configured = app_settings(tmp_path)
    comparison = SimpleNamespace(settings=None)
    logger = Log()
    logger.metrics = SimpleNamespace(settings=None, comparison=comparison)
    app = Application(configured, object(), logger, object(), object(), object(), object(), object(),
                      object(), Orch(), Event())
    changed = configured.model_copy(update={"poll_interval_seconds": 30})
    app.apply_settings(changed)
    assert app.settings.poll_interval_seconds == 30
    assert logger.metrics.settings is comparison.settings is changed.metrics


def test_settings_file_changed_while_queued_is_stale(web, tmp_path):
    service, *_ = configure(web, tmp_path)
    session = web.auth.sessions()[0]
    queued = AdminCommand(kind=AdminKind.SETTINGS, actor=f"web:{session.id}", idempotency_key="key-settings-1",
                          expected_hash=file_hash(tmp_path / "config.yaml"),
                          patch={"poll_interval_seconds": 10}, acknowledged=True)
    # Edited by hand after the command was queued and before it ran.
    path = tmp_path / "config.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["poll_interval_seconds"] = 20
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    result = service.execute(queued)
    assert (result.status, result.message) == (ResultStatus.STALE, "Datei inzwischen geändert; bitte neu laden.")
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["poll_interval_seconds"] == 20


def test_relevance_history_needs_a_decision(web):
    state = web.store.load_model(f"mail-{mail_id(7)}", MailState)
    record_relevance(web.store, state, "web", "key-open-question")
    assert web.store.peek(f"history-{mail_id(7)}") is None
    decided = state.model_copy(update={"relevance_dialog": RelevanceDialog(
        mail_id=mail_id(7), status="decided", decision="irrelevant", telegram_offset=3)})
    record_relevance(web.store, decided, "web", "key-decided")
    assert web.store.peek(f"history-{mail_id(7)}")["events"][0]["status"] == "irrelevant"
    no_dialog = state.model_copy(update={"relevance_dialog": None, "awaiting_relevance": False})
    record_relevance(web.store, no_dialog, "web", "key-none")


def test_relevance_command_for_a_removed_mail_records_nothing(web):
    actor = f"web:{web.auth.sessions()[0].id}"
    entry, _ = web.commands.submit(command(CommandKind.RELEVANCE, mail_id="e" * 24, decision="relevant",
                                           actor=actor))
    web.run()
    assert web.commands.get(entry.id).result.status == ResultStatus.STALE
    assert web.store.peek("history-" + "e" * 24) is None


def test_https_video_link_is_kept_as_url():
    event = proposal(1, "termin", kind="event", start="2026-10-21T10:00:00+02:00",
                     end="2026-10-21T11:00:00+02:00", target="Familie")
    edited = edit_proposal(event, ProposalEditPatch(video_link="https://meet.test/raum"), "Europe/Berlin",
                           {"Familie"})
    assert str(edited.video_link) == "https://meet.test/raum" and edited.version == 2


def test_history_filters_paging_and_first_version(web):
    item = proposal(1, "formular")
    for version, kind in ((1, "edit"), (2, "reject")):
        item = item.model_copy(update={"version": version})
        web.store.save(f"proposal-{item.source_mail_id}-{item.id}-v{version}", item.model_dump(mode="json"))
        record_event(web.store, item, kind, "web", f"key-{version}")
    by_kind = web.browser.request("GET", "/verlauf?kind=reject").body.decode()
    assert "1 Ereignisse" in by_kind
    by_status = web.browser.request("GET", "/verlauf?status=created").body.decode()
    assert "0 Ereignisse" in by_status
    by_type = web.browser.request("GET", "/verlauf?proposal_kind=event").body.decode()
    assert "0 Ereignisse" in by_type
    second = web.browser.request("GET", "/verlauf?size=1&page=2").body.decode()
    assert "Vorherige Seite" in second
    first = web.browser.request("GET", f"/vorschlag/{mail_id(1)}/formular/version/1").body.decode()
    assert "Vorherige Version nicht vorhanden." in first


def test_error_list_names_the_next_attempt(web):
    now = datetime.now(timezone.utc)
    state = web.store.load_model(f"mail-{mail_id(2)}", MailState)
    web.store.save(f"mail-{mail_id(2)}", state.model_copy(update={
        "error": ProcessingError(code="llm_rate_limited", stage="relevance", occurred_at=now, retryable=True),
        "deferred_until": now + timedelta(hours=2)}).model_dump(mode="json"))
    page = web.browser.request("GET", "/status").body.decode()
    assert "wird automatisch wiederholt · nächster Versuch:" in page


def test_relevance_history_is_skipped_when_the_mail_record_is_gone(web, monkeypatch):
    """The decision stands even if retention removed the mail record meanwhile."""
    monkeypatch.setattr(web.dialog, "_decide_relevance", lambda decision, offset: "ok")
    actor = f"web:{web.auth.sessions()[0].id}"
    result = web.dialog.review.execute(command(CommandKind.RELEVANCE, mail_id="e" * 24,
                                               decision="irrelevant", actor=actor))
    assert result.status == ResultStatus.DONE
    assert web.store.peek("history-" + "e" * 24) is None


@pytest.mark.parametrize(("mode", "llm"), [("standard", "KI-Modelle (OpenRouter)"), ("local", "Ollama")])
def test_successful_contacts_per_service_from_logged_events(tmp_path, mode, llm):
    metrics = MetricsRecorder(tmp_path / "llm.jsonl", MetricsSettings(), mode)
    for service, event in (("todoist", "create_completed"), ("google_calendar", "duplicate_updated"),
                           ("google_oauth", "token_credentials_accepted"), ("decisions", "jev_relevance_completed"),
                           ("todoist", "create_failed"), ("google_calendar", "target_access_failed")):
        metrics.observe(event, {"service": service})
    metrics.observe("response_received", {"call_id": "c1"})
    contacts = metrics.runtime()["contacts"]
    assert set(contacts) == {"Todoist", "Google Kalender", "Google-Anmeldung", "Jev (Relevanz)", llm}
    services = metrics.expected_services()
    assert services[0] == "IMAP-Postfach" and llm in services
    assert ("Jev (Relevanz)" in services) is (mode == "standard")


def test_telegram_messages_count_as_contacts_without_content(tmp_path):
    from mailhelp.logging import JsonlLogger
    from test_application import settings as app_settings
    from mailhelp.application import build_logger
    from mailhelp.config import Secrets
    secrets = Secrets(imap_username="u", imap_password="p", openrouter_api_key="o", telegram_bot_token="t",
                      todoist_token="d", todoist_client_id="ti", todoist_client_secret="ts",
                      google_oauth_client_id="i", google_oauth_client_secret="s", google_oauth_refresh_token="r")
    logger = build_logger(app_settings(tmp_path), secrets, tmp_path)
    assert isinstance(logger, JsonlLogger)
    seen = []
    logger.metrics = SimpleNamespace(observe=lambda event, context: seen.append((event, context)))
    logger.telegram_event("sent", chat_id=2, text="geheimer Inhalt")
    assert seen == [("message_sent", {"service": "telegram"})]


def test_status_page_shows_runtime_contacts_and_its_own_refresh_signal(web, tmp_path):
    _, metrics, *_ = configure(web, tmp_path)
    metrics.observe("processing_started", {"mail_id": mail_id(1)})
    metrics.observe("request_completed", {"service": "imap"})
    page = web.browser.request("GET", "/status").body.decode()
    assert "<dt>Schritt</dt><dd>Aufbereitung</dd>" in page
    assert f'href="/mail/{mail_id(1)}">Bearbeitete Mail öffnen</a>' in page
    assert "<dt>IMAP-Postfach</dt><dd>zuletzt erfolgreich" in page
    assert "<dt>Telegram</dt><dd>unbekannt</dd>" in page
    assert 'data-state-url="/api/stand?seite=status"' in page
    first = json.loads(web.browser.request("GET", "/api/stand?seite=status", accept="application/json").body)
    metrics.observe("idle_started", {"delay_seconds": 120})
    second = json.loads(web.browser.request("GET", "/api/stand?seite=status", accept="application/json").body)
    assert first["fingerprint"] != second["fingerprint"]
    assert first["fingerprint"] in page
    # A contact alone does not reload the page every poll.
    metrics.observe("request_completed", {"service": "imap"})
    third = json.loads(web.browser.request("GET", "/api/stand?seite=status", accept="application/json").body)
    assert third == second
    idle = web.browser.request("GET", "/status").body.decode()
    assert "<dt>Nächster Mailabruf</dt>" in idle and "Bearbeitete Mail öffnen" not in idle
    overview = json.loads(web.browser.request("GET", "/api/stand", accept="application/json").body)
    assert overview["fingerprint"] != second["fingerprint"]


def test_status_without_metrics_and_unknown_stage(web, tmp_path):
    from mailhelp.web.review_pages import RUNTIME_STAGES, ServiceInfo, _runtime_section
    from zoneinfo import ZoneInfo
    assert "Aktuelle Verarbeitung" not in web.browser.request("GET", "/status").body.decode()
    plain = json.loads(web.browser.request("GET", "/api/stand?seite=status", accept="application/json").body)
    assert len(plain["fingerprint"]) == 16
    info = ServiceInfo(version="1", test_mode=False, started_at=datetime.now(timezone.utc),
                       now=datetime.now(timezone.utc), address="x", devices=0, llm_calls_per_minute=None,
                       commands={}, runtime={"stage": "event_extraction", "elapsed": 5, "contacts":
                                             {"Sonderdienst": "2026-10-11T10:00:00+00:00"}},
                       services=("IMAP-Postfach",))
    html = _runtime_section(info, ZoneInfo("UTC"))
    assert "Terminerkennung" in html and "Sonderdienst" in html and "unbekannt" in html
    other = _runtime_section(info.__class__(**{**info.__dict__, "runtime": {"stage": "neu", "elapsed": 0,
                                                                            "contacts": {}}}), ZoneInfo("UTC"))
    assert "<dd>neu</dd>" in other and RUNTIME_STAGES["idle"].startswith("Leerlauf")
