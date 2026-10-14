"""1.2 behaviour that was implemented but not yet verified by a test."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Event
from types import SimpleNamespace

import pytest
import yaml
from shared_application import Log, Orch
from shared_application import settings as app_settings
from shared_review import command
from shared_web_actions import web  # noqa: F401  (fixture)
from shared_web_v12 import configure
from web_scenario import mail_id, proposal

from mailhelp.application import Application
from mailhelp.configuration import AdminCommand, AdminKind, file_hash
from mailhelp.decision_test import ComparisonRecorder
from mailhelp.metrics import MetricsRecorder, MetricsSettings, server_electricity
from mailhelp.models import MailState, ProcessingError, RelevanceDialog
from mailhelp.review.archive import record_event, record_relevance
from mailhelp.review.commands import CommandKind
from mailhelp.review.editing import ProposalEditPatch, edit_proposal
from mailhelp.review.results import ResultStatus

# Since 2.3 the writers are built in mailhelp.external.providers.
MOVED_WRITERS = ("HttpWriter", "GoogleOAuthTokenProvider")


def test_exchange_rate_needs_its_date():
    assert MetricsSettings().usd_per_eur == 1.1
    assert MetricsSettings(usd_per_eur=1.08).usd_per_eur == 1.08
    with pytest.raises(ValueError, match="konfigurierten Wechselkurs"):
        MetricsSettings(usd_per_eur=None, exchange_rate_date="2026-10-01")
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
    assert datetime.fromisoformat(runtime["next_poll"]) > datetime.now(UTC)
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
    assert app.mailbox.settings is changed
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
    now = datetime.now(UTC)
    state = web.store.load_model(f"mail-{mail_id(2)}", MailState)
    web.store.save(f"mail-{mail_id(2)}", state.model_copy(update={
        "error": ProcessingError(code="llm_rate_limited", stage="relevance", occurred_at=now, retryable=True),
        "deferred_until": now + timedelta(hours=2)}).model_dump(mode="json"))
    page = web.browser.request("GET", "/status").body.decode()
    assert "wird automatisch wiederholt · nächster Versuch:" in page


def test_relevance_history_is_skipped_when_the_mail_record_is_gone(web, monkeypatch):
    """The decision stands even if retention removed the mail record meanwhile."""
    monkeypatch.setattr(web.dialog, "decide_relevance", lambda decision, offset: "ok")
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
    from shared_application import settings as app_settings

    from mailhelp.application import build_logger
    from mailhelp.config import Secrets
    from mailhelp.logging import JsonlLogger
    secrets = Secrets(imap={1: {"username": "u", "password": "p"}}, openrouter_api_key="o", telegram_bot_token="t",
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
    from zoneinfo import ZoneInfo

    from mailhelp.web.status_pages import RUNTIME_STAGES, ServiceInfo, _runtime_section
    assert "Aktuelle Verarbeitung" not in web.browser.request("GET", "/status").body.decode()
    plain = json.loads(web.browser.request("GET", "/api/stand?seite=status", accept="application/json").body)
    assert len(plain["fingerprint"]) == 16
    info = ServiceInfo(version="1", test_mode=False, started_at=datetime.now(UTC),
                       now=datetime.now(UTC), address="x", devices=0, llm_calls_per_minute=None,
                       commands={}, runtime={"stage": "event_extraction", "elapsed": 5, "contacts":
                                             {"Sonderdienst": "2026-10-11T10:00:00+00:00"}},
                       services=("IMAP-Postfach",))
    html = _runtime_section(info, ZoneInfo("UTC"))
    assert "Terminerkennung" in html and "Sonderdienst" in html and "unbekannt" in html
    other = _runtime_section(info.__class__(**{**info.__dict__, "runtime": {"stage": "neu", "elapsed": 0,
                                                                            "contacts": {}}}), ZoneInfo("UTC"))
    assert "<dd>neu</dd>" in other and RUNTIME_STAGES["idle"].startswith("Leerlauf")


# --- R3: metrics location, no double counting, readable report --------------------

def test_legacy_metrics_move_once_with_their_aggregates(tmp_path):
    from mailhelp.metrics import adopt_legacy, sibling
    legacy = tmp_path / "data" / "production" / "metrics" / "llm.jsonl"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"id": "a"}\n', encoding="utf-8")
    legacy.with_name("daily.json").write_text("{}", encoding="utf-8")
    target = tmp_path / "logs" / "metrics" / "llm.jsonl"
    assert adopt_legacy(legacy, target)
    assert target.read_text(encoding="utf-8") == '{"id": "a"}\n'
    assert sibling(target, "daily").exists() and not sibling(target, "compaction").exists()
    assert not legacy.exists()
    # A later legacy file never overwrites the adopted data.
    legacy.write_text('{"id": "b"}\n', encoding="utf-8")
    assert not adopt_legacy(legacy, target) and target.read_text(encoding="utf-8") == '{"id": "a"}\n'
    assert not adopt_legacy(tmp_path / "fehlt.jsonl", tmp_path / "neu.jsonl")


def attempt(metrics, call, model="deepseek", **response):
    metrics.observe("request_started", {"call_id": call, "model": model, "stage": "summary"})
    metrics.observe("response_received", {"call_id": call, **response})


def test_a_restart_or_a_repeated_line_never_counts_an_attempt_twice(tmp_path):
    path = tmp_path / "llm.jsonl"
    first = MetricsRecorder(path, MetricsSettings())
    attempt(first, "c1", reported_cost=0.01)
    # Crash recovery or log replay may write the same attempt again.
    line = path.read_text(encoding="utf-8")
    path.write_text(line + line, encoding="utf-8")
    restarted = MetricsRecorder(path, MetricsSettings())
    attempt(restarted, "c2", reported_cost=0.02)
    report = restarted.report()
    assert report["count"] == 2 and Decimal(report["usd"]) == Decimal("0.03")
    assert restarted.report()["count"] == 2


def test_production_and_decision_tests_are_reported_separately(web, tmp_path):
    _, metrics, *_ = configure(web, tmp_path)
    metrics.comparison = MetricsRecorder(tmp_path / "decision-tests.jsonl", MetricsSettings(), "decision_test")
    attempt(metrics, "prod", reported_cost=0.5)
    for call in ("t1", "t2"):
        attempt(metrics.comparison, call)
    production = web.browser.request("GET", "/auswertung").body.decode()
    assert "<dt>Aufrufe (einzelne Versuche)</dt><dd>1</dd>" in production
    assert "<dt>Gemeldete Cloudkosten</dt><dd>0,5000 USD</dd>" in production
    tests = web.browser.request("GET", "/auswertung?mode=decision_test").body.decode()
    assert "<dt>Aufrufe (einzelne Versuche)</dt><dd>2</dd>" in tests
    assert "<dt>Cloudaufrufe ohne Kostenangabe</dt><dd>2</dd>" in tests
    assert '<option value="decision_test" selected>' in tests


def test_statistics_page_labels_rates_and_incomplete_capture(web, tmp_path):
    _, metrics, *_ = configure(web, tmp_path)
    page = web.browser.request("GET", "/auswertung").body.decode()
    assert "Für diese Auswahl gibt es keine erfassten Aufrufe." in page
    assert "<dd>0,0000 EUR</dd>" in page and "<dd>— / — / —</dd>" in page
    assert web.browser.request("GET", "/auswertung?mode=unbekannt").status == 422
    metrics.settings = MetricsSettings(usd_per_eur=1.25, exchange_rate_date="2026-10-01")
    attempt(metrics, "c1", model="openrouter/deepseek", reported_cost=2.5)
    metrics.failures = 1
    with metrics.path.open("a", encoding="utf-8") as stream:
        stream.write("kaputt\n")
    page = web.browser.request("GET", "/auswertung?model=openrouter/deepseek").body.decode()
    assert "<dd>2,0000 EUR (Wechselkurs vom 2026-10-01)</dd>" in page
    assert "<dd>1 beschädigte Zeilen, 1 Erfassungsfehler</dd>" in page
    assert "<th>$Cent</th>" in page
    assert '<td title="openrouter/deepseek">deepseek</td>' in page
    assert '<td title="2,5000 USD">250,00</td>' in page
    assert '<option value="openrouter/deepseek" selected>' in page and "<th>Modell</th>" in page
    assert "<dt>Geschätzte Stromkosten Ollama</dt><dd>0,0000 EUR</dd>" in page
    metrics.settings = MetricsSettings(usd_per_eur=None)
    page_no_rate = web.browser.request("GET", "/auswertung").body.decode()
    assert "kein Wechselkurs hinterlegt" in page_no_rate


def test_application_writes_metrics_into_the_log_directory(tmp_path, monkeypatch):
    from shared_core import prompt_config

    from mailhelp.application import build_application
    from mailhelp.config import Secrets, Topic

    class Resource:
        def __init__(self, *args, **kwargs): pass
        def close(self): pass

    for name in ("ImapReader", "OpenRouterClient", "DecisionClient", "TelegramClient",
                 "HttpWriter", "GoogleOAuthTokenProvider"):
        monkeypatch.setattr(f"mailhelp.{'external.providers' if name in MOVED_WRITERS else 'composition'}.{name}", Resource)
    cfg = app_settings(tmp_path)
    cfg.logging.file.enabled = cfg.logging.console.enabled = False
    legacy = tmp_path / "data" / "test" / "metrics" / "llm.jsonl"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("", encoding="utf-8")
    secrets = Secrets(imap={1: {"username": "u", "password": "p"}}, openrouter_api_key="o", telegram_bot_token="t",
                      todoist_token="d", todoist_client_id="ti", todoist_client_secret="ts",
                      google_oauth_client_id="i", google_oauth_client_secret="s", google_oauth_refresh_token="r")
    with build_application(cfg, secrets, [Topic(id="x", name="x", enabled=True, description="x")],
                           prompt_config(), "f" * 64, base_directory=tmp_path) as made:
        logs = tmp_path / "logs" / "metrics"
        assert made.logger.metrics.path == logs / "llm.jsonl"
        assert made.logger.metrics.comparison.path == logs / "decision-tests.jsonl"
        assert (logs / "llm.jsonl").exists() and not legacy.exists()
        # Former fingerprints of this configuration are registered as equivalent.
        registered = made.store.names("processing-topics-")
        assert len(registered) == 3
        assert all(made.store.load(name)["policy"] == made.orchestrator.topic_policy for name in registered)


# --- R4: settings page ---------------------------------------------------------------

def test_effective_models_name_their_source_without_prompt_texts():
    from shared_core import prompt_config

    from mailhelp.configuration import effective_models
    prompts = prompt_config()
    standard = effective_models(prompts, "typesafe/jev", None)
    assert standard[0] == ("Relevanz", "typesafe/jev", "unklare Fälle: Rückfall auf das Relevanzmodell",
                           "decisions_prompts.yaml")
    assert all(source == "prompts.yaml" for *_, source in standard[1:])
    assert ("Zusammenfassung" in {step for step, *_ in standard})
    local = effective_models(prompts, None, "gemma3:12b")
    assert local[0] == ("Alle Schritte", "gemma3:12b", "", "Startparameter --ollama")
    assert all(source == "Startparameter --ollama ersetzt" for *_, source in local[1:])
    legacy = effective_models(prompts, None, None)
    assert all(source == "prompts.yaml" for *_, source in legacy)
    rendered = " ".join(str(value) for row in standard for value in row)
    assert "system_prompt" not in rendered and "Du bist" not in rendered


def test_settings_page_groups_values_and_marks_pending_restarts(web, tmp_path):
    service, *_ = configure(web, tmp_path)
    path = tmp_path / "config.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["timeouts"]["imap"]["retries"] = 7
    data["targets"]["google_calendar"] = "familie@group.calendar.google.com"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    page = web.browser.request("GET", "/einstellungen").body.decode()
    for title in ("Mailabruf und Betrieb", "Ziele", "Zeitlimits und Wiederholungen", "Aufbewahrung",
                  "Protokollierung", "Kosten und Messung"):
        assert f"<h2>{title}</h2>" in page
    assert "<span>IMAP: Wiederholungen</span><strong>0</strong>" in page
    assert "Gespeichert: 7 · gespeichert – wirkt erst nach einem Neustart" in page
    assert "<strong>c…</strong>" not in page and "fam…com" in page
    assert '<option value="true"' in page and '<option value="INFO" selected>' in page
    assert 'type="number" step="any" name="value" value="5"' in page
    assert "<span>Wechselkurs (USD je EUR)</span><strong>1.1</strong>" in page
    assert "<span>Wechselkurs vom</span><strong>nicht gesetzt</strong>" in page
    web.site.archive.configuration = None
    unavailable = web.browser.request("GET", "/einstellungen").body.decode()
    assert "Konfigurationsdienst nicht verfügbar." in unavailable and "<h2>Modelle (nur lesend)</h2>" in unavailable


def test_live_settings_saved_but_not_yet_taken_over(web, tmp_path):
    service, *_ = configure(web, tmp_path)
    path = tmp_path / "config.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["poll_interval_seconds"] = 33
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    page = web.browser.request("GET", "/einstellungen").body.decode()
    assert "Gespeichert: 33 · gespeichert – wird an der nächsten sicheren Stelle übernommen" in page


def test_settings_page_shows_the_model_table_or_says_there_is_none(web, tmp_path):
    from shared_core import prompt_config

    from mailhelp.configuration import effective_models
    configure(web, tmp_path)
    assert "Keine Modellangaben verfügbar." in web.browser.request("GET", "/einstellungen").body.decode()
    web.site.archive.models = effective_models(prompt_config(), "typesafe/jev", None)
    page = web.browser.request("GET", "/einstellungen").body.decode()
    assert "<td>Relevanz</td><td>typesafe/jev</td>" in page and "<td>decisions_prompts.yaml</td>" in page


def test_no_secret_appears_in_any_web_page_or_answer(web, tmp_path):
    secret_values = ("imap-geheim-123", "sk-or-geheim-456", "bot-geheim-789")
    service, metrics, *_ = configure(web, tmp_path)
    path = tmp_path / "config.yaml"
    # Secrets must never be in config.yaml; even a misplaced one is not echoed by a refused field.
    form = web.form("/einstellungen", action="/einstellungen/speichern", name="timezone")
    refused = web.browser.request("POST", "/einstellungen/speichern",
                                  {**form, "name": "imap_password", "value": secret_values[0], "confirm": "yes"})
    assert refused.status == 422 and secret_values[0] not in refused.body.decode()
    (tmp_path / ".env").write_text("\n".join(f"KEY{i}={value}" for i, value in enumerate(secret_values)),
                                   encoding="utf-8")
    for route in ("/", "/mails", "/verlauf", "/status", "/auswertung", "/einstellungen", "/themen",
                  "/einstellungen/beenden", "/api/stand", "/api/stand?seite=status"):
        body = web.browser.request("GET", route).body.decode()
        assert not any(value in body for value in secret_values), route
    assert secret_values[0] not in path.read_text(encoding="utf-8")


def test_a_lower_call_limit_keeps_the_counted_budget(web, tmp_path):
    service, *_ = configure(web, tmp_path)
    web.store.save("llm-budget", {"calls": [1.0, 2.0, 3.0]})
    form = web.form("/einstellungen", action="/einstellungen/speichern", name="limits.llm_calls_per_minute")
    response = web.browser.request("POST", "/einstellungen/speichern", {**form, "value": "1", "confirm": "yes"})
    assert response.status == 303
    web.run()
    assert web.store.load("llm-budget") == {"calls": [1.0, 2.0, 3.0]}
    assert yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))["limits"]["llm_calls_per_minute"] == 1


def test_shorter_retention_is_not_saved_without_explicit_confirmation(web, tmp_path):
    service, *_ = configure(web, tmp_path)
    form = web.form("/einstellungen", action="/einstellungen/speichern", name="retention.full_mail_days")
    preview = web.browser.request("POST", "/einstellungen/speichern", {**form, "value": "1"})
    assert preview.status == 200 and "unwiderruflich" in preview.body.decode()
    web.run()
    saved = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert saved["retention"]["full_mail_days"] == 30
    assert web.commands.queued() == []


# --- R5: controlled stop -------------------------------------------------------------

def test_stop_states_are_logged_and_end_in_stopped():
    from mailhelp.lifecycle import Lifecycle
    log, calls = [], []
    life = Lifecycle(lambda: calls.append("stop"), lambda actor: True, lambda state, process: log.append(state))
    after = life.request(life.process, "a" * 32, "web:x")
    after()
    after()  # a second delivery of the answer does not stop twice
    life.finished()
    life.finished()
    assert log == ["stop_requested", "stopping", "stopped"] and calls == ["stop"]
    # A signal stops without a web request and still ends in "stopped".
    signal_log = []
    by_signal = Lifecycle(lambda: None, lambda actor: True, lambda state, process: signal_log.append(state))
    by_signal.finished()
    assert signal_log == ["stopped"] and by_signal.state == "stopped"


def test_the_run_loop_reports_its_end_to_the_lifecycle(tmp_path):
    from shared_application import Imap, Telegram, app

    from mailhelp.lifecycle import Lifecycle
    service = app(tmp_path, Imap([]), Telegram([]), Orch())
    service.lifecycle = Lifecycle(service.stop, lambda actor: True)
    service.stop_event.set()
    service.run()
    assert service.lifecycle.state == "stopped"


def test_after_a_stop_request_web_commands_wait_and_run_after_a_restart(web, tmp_path):
    from mailhelp.lifecycle import Lifecycle
    from mailhelp.review.inbox import CommandStatus
    _, _, lifecycle, _, calls = configure(web, tmp_path)
    web.dialog.stop_requested = lambda: lifecycle.state != "running"
    queued = web.submit(web.form("/", kind="reject", proposal_id="formular"))
    entry_id = queued.headers["Location"].rsplit("/", 1)[1]
    form = web.form("/einstellungen/beenden", action="/einstellungen/beenden")
    answer = web.browser.request("POST", "/einstellungen/beenden", form)
    assert answer.status == 202 and lifecycle.state == "stop_requested"
    web.run()  # the main thread no longer executes anything
    assert web.commands.get(entry_id).status == CommandStatus.QUEUED
    answer.after_send()
    assert calls == ["stop"] and lifecycle.state == "stopping"
    # New process: a fresh lifecycle; the stored command is checked again and runs once.
    restarted = Lifecycle(lambda: calls.append("again"), web.dialog.review.web_authorizer)
    web.dialog.stop_requested = lambda: restarted.state != "running"
    web.run()
    assert web.commands.get(entry_id).status == CommandStatus.DONE
    assert calls == ["stop"] and restarted.state == "running"
    assert web.store.load(f"proposal-{mail_id(1)}-formular")["status"] == "rejected"


def test_a_parallel_learning_run_wins_over_an_open_topic_form(web, tmp_path):
    from mailhelp.config import Topic
    from mailhelp.learning import save_topics
    from mailhelp.models import LearnedCategory
    configure(web, tmp_path)
    form = web.form("/themen", action="/themen/speichern", original_id="")
    # The learning mode adds a topic while the form is open in the browser.
    existing = [Topic.model_validate(item) for item in
                yaml.safe_load((tmp_path / "topics.yaml").read_text(encoding="utf-8"))["topics"]]
    save_topics(tmp_path / "topics.yaml", existing,
                [LearnedCategory(name="Verein", description="Vereinspost", examples=["Training"])])
    learned = (tmp_path / "topics.yaml").read_text(encoding="utf-8")
    data = {**form, "id": "sport", "name": "Sport", "description": "Sport", "enabled": "true",
            "examples": "", "exclusions": "", "confirm": "yes"}
    assert web.browser.request("POST", "/themen/speichern", data).status == 409
    web.run()
    assert (tmp_path / "topics.yaml").read_text(encoding="utf-8") == learned


@pytest.mark.parametrize("swapped", [False, True])
def test_crash_before_or_after_the_atomic_topic_swap(web, tmp_path, swapped):
    from mailhelp.config import Topic
    from mailhelp.configuration import AdminCommand, AdminKind, file_hash
    from mailhelp.learning import topics_document
    service, *_ = configure(web, tmp_path)
    path = tmp_path / "topics.yaml"
    command = AdminCommand(kind=AdminKind.TOPICS, actor=f"web:{web.auth.sessions()[0].id}",
                           idempotency_key="key-topic-crash", expected_hash=file_hash(path), acknowledged=True,
                           patch={"id": "sport", "name": "Sport", "description": "Sport", "enabled": True})
    candidate = service.candidate(command)
    content = service.render(command, candidate)
    import hashlib
    web.store.save("configuration-key-topic-crash", {
        "schema_version": 1, "command": command.model_dump(mode="json"),
        "candidate_hash": hashlib.sha256(content.encode()).hexdigest(), "status": "prepared"})
    if swapped:
        path.write_text(content, encoding="utf-8", newline="\n")
    result = service.reconcile(command)
    assert result.status == (ResultStatus.DONE if swapped else ResultStatus.FAILED)
    topics = [Topic.model_validate(item) for item in yaml.safe_load(path.read_text(encoding="utf-8"))["topics"]]
    assert ("sport" in {topic.id for topic in topics}) is swapped
    # After the swap the file is exactly the journaled candidate, never a mixture.
    assert (topics_document(topics) == path.read_text(encoding="utf-8")) is swapped


# --- R6: mail list readability ---------------------------------------------------------

def test_mail_list_shows_readable_entries_filters_and_paging(web):
    from mailhelp.models import ProcessingError
    now = datetime.now(UTC)
    state = web.store.load_model(f"mail-{mail_id(2)}", MailState)
    web.store.save(f"mail-{mail_id(2)}", state.model_copy(update={
        "error": ProcessingError(code="internal_error", stage="summary", occurred_at=now)}).model_dump(mode="json"))
    page = web.browser.request("GET", "/mails").body.decode()
    assert "<details class=\"filter-box\"><summary>Filter</summary>" in page
    assert ">Klassenleitung 4b · " in page and "&lt;klasse4b" not in page
    assert '<span class="badge warn">wartet auf dich</span>' in page
    assert '<span class="badge danger">Fehler</span>' in page
    assert "× Wartet auf Bestätigung" in page and "nicht mehr bekannt" in page
    assert "beschädigt" not in page
    filtered = web.browser.request("GET", "/mails?state=waiting&sort=updated").body.decode()
    assert '<details class="filter-box" open>' in filtered
    assert '<option value="waiting" selected>' in filtered and '<option value="updated" selected>' in filtered
    second = web.browser.request("GET", "/mails?size=1&page=2").body.decode()
    assert "Vorherige Seite" in second and "Nächste Seite" in second
    none = web.browser.request("GET", "/mails?q=gibtsnicht").body.decode()
    assert "Keine gespeicherte Mail passt zu dieser Suche." in none
    (web.store.directory / f"mail-{'e' * 24}.json").write_text("{", encoding="utf-8")
    web.store.archive_revision += 1  # the next regular state change rebuilds the index
    assert "1 gespeicherte Datensätze sind beschädigt" in web.browser.request("GET", "/mails").body.decode()
