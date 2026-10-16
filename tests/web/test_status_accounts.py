"""Configured accounts remain visible before contact, after failures and across restarts."""
import json

import pytest
import yaml

from mailhelp.config import Settings
from mailhelp.metrics import MetricsRecorder, MetricsSettings


def configure_accounts(profiled):
    raw = yaml.safe_load((profiled.tmp_path / "config.yaml").read_text(encoding="utf-8"))
    raw["iserv"] = {"accounts": [
        {"id": 1, "label": "Grundschule", "server": "https://schule.example", "mailbox": 1},
        {"id": 2, "label": "Gymnasium", "server": "https://andere.example", "mailbox": 2},
        {"id": 3, "label": "Pausiert", "server": "https://pause.example", "enabled": False}]}
    profiled.app.configuration.active = Settings.model_validate(raw)
    (profiled.tmp_path / "config.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    metrics = MetricsRecorder(profiled.tmp_path / "metrics.jsonl", MetricsSettings(enabled=False))
    profiled.web.site.archive.metrics = metrics
    return metrics


def test_regression_status_lists_every_configured_account_before_any_contact(profiled):
    configure_accounts(profiled)
    page = profiled.web.browser.request("GET", "/status").body.decode()
    for name in ("IMAP 1 · Privat", "IMAP 2 · Arbeit", "IServ 1 · Grundschule", "IServ 2 · Gymnasium",
                 "IServ 3 · Pausiert", "Kalender · Standard (1)", "Aufgaben · Arbeit (2)"):
        assert name in page
    assert "noch nicht geprüft" in page and "deaktiviert" in page


def test_account_failures_and_recovery_are_isolated_and_refresh_the_page(profiled):
    metrics = configure_accounts(profiled)
    browser = profiled.web.browser
    def signal():
        return json.loads(browser.request("GET", "/api/stand?seite=status").body)["fingerprint"]
    first = signal()
    metrics.observe("access_check_failed", {"service": "iserv", "account": 1, "error": "secret"})
    failed = signal()
    assert failed != first
    page = browser.request("GET", "/status").body.decode()
    assert "IServ 1 · Grundschule</dt><dd>Fehler" in page
    assert "IServ 2 · Gymnasium</dt><dd>noch nicht geprüft" in page
    assert "secret" not in page
    metrics.observe("letters_listed", {"service": "iserv", "account": 1})
    ready = signal()
    assert ready != failed
    assert "IServ 1 · Grundschule</dt><dd>zuletzt erfolgreich" in browser.request("GET", "/status").body.decode()
    metrics.observe("letters_listed", {"service": "iserv", "account": 1})
    assert signal() == ready  # Successful polls alone must not reload the page each time.
    profiled.web.site.archive.metrics = MetricsRecorder(metrics.path, metrics.settings)
    assert signal() == first
    assert profiled.web.writer.created == 0


@pytest.mark.parametrize("enabled", [True, False])
def test_saved_connection_changes_show_restart_and_drafts_are_not_accounts(profiled, enabled):
    metrics = configure_accounts(profiled)
    browser = profiled.web.browser
    metrics.observe("letters_listed", {"service": "iserv", "account": 1})
    before = browser.request("GET", "/api/stand?seite=status").body
    path = profiled.tmp_path / "config.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["iserv"]["accounts"][0].update(server="https://neu.example", enabled=enabled)
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert browser.request("GET", "/api/stand?seite=status").body != before
    assert "IServ 1 · Grundschule</dt><dd>Neustart erforderlich" in browser.request("GET", "/status").body.decode()
    # No connection check and no approval: draft-only accounts stay out of the inventory.
    profiled.web.store.save("setup-state", {"patch": {"iserv.accounts": [{"id": 9, "server": "https://draft.example"}]}})
    assert "IServ 9" not in browser.request("GET", "/status").body.decode()
    profiled.app.configuration.active = Settings.model_validate(raw)
    page = browser.request("GET", "/status").body.decode()
    assert "Neustart erforderlich" not in page


def test_account_inventory_survives_missing_metrics_and_invalid_configuration(profiled):
    configure_accounts(profiled)
    profiled.web.site.archive.metrics = None
    path = profiled.tmp_path / "config.yaml"
    path.write_text("iserv: invalid", encoding="utf-8")
    assert "IServ 1 · Grundschule" in profiled.web.browser.request("GET", "/status").body.decode()
    path.unlink()
    assert "noch nicht geprüft" in profiled.web.browser.request("GET", "/status").body.decode()


def test_disabled_unused_and_escaped_accounts_with_folder_failures(profiled):
    metrics = configure_accounts(profiled)
    cfg = profiled.app.configuration.active.model_dump(mode="json")
    cfg["imap"]["mailboxes"][1]["enabled"] = False
    cfg["iserv"]["accounts"][1]["enabled"] = False
    cfg["iserv"]["accounts"][0]["label"] = "<img src=x>"
    cfg["telegram"]["enabled"] = False
    cfg["web"]["enabled"] = True
    profiled.app.configuration.active = Settings.model_validate(cfg)
    (profiled.tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    metrics.observe("optional_folder_failed", {"service": "imap", "mailbox": 1, "folder": "Gesendet"})
    metrics.observe("messages_discovered", {"service": "imap", "mailbox": 1, "folder": "INBOX"})
    page = profiled.web.browser.request("GET", "/status").body.decode()
    assert "IMAP 1 · Privat</dt><dd>Fehler" in page
    assert "IMAP 2 · Arbeit</dt><dd>deaktiviert" in page
    assert "nicht verwendet" in page and "Telegram</dt><dd>deaktiviert" in page
    assert "&lt;img src=x&gt;" in page and "<img src=x>" not in page


@pytest.mark.parametrize(("service", "context", "key"), [
    ("imap", {"account_id": "a" * 24}, "imap:1"),
    ("imap", {"mailbox": 2}, "imap:2"),
    ("iserv", {"account": 2}, "iserv:2"),
    ("todoist", {"profile": 2}, "todoist:2"),
    ("google_calendar", {}, "google_calendar:1"),
    ("telegram", {}, "telegram"),
])
def test_account_metrics_keep_failure_success_and_snapshots_separate(tmp_path, service, context, key):
    metrics = MetricsRecorder(tmp_path / "metrics.jsonl", MetricsSettings(enabled=False))
    metrics.mailbox_numbers = {"a" * 24: 1}
    metrics.observe("access_check_failed", {"service": service, **context, "error": "private"})
    assert metrics.runtime()["accounts"][key]["status"] == "failed"
    metrics.observe("access_confirmed", {"service": service, **context})
    # IMAP access is normally observed through discovery rather than a start-up check.
    if service == "imap":
        metrics.observe("messages_discovered", {"service": service, **context})
    snapshot = metrics.runtime()
    assert snapshot["accounts"][key]["status"] == "ready"
    snapshot["accounts"][key]["status"] = "mutated"
    assert metrics.runtime()["accounts"][key]["status"] == "ready"
    metrics.observe("unknown_event", {"service": service, **context})
    assert "private" not in str(metrics.runtime())
