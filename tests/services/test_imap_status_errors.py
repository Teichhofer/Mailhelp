"""Folder failures must remain visible even when no mail reached the pipeline."""
import json
from types import SimpleNamespace

import pytest
from shared_web_actions import web  # noqa: F401
from shared_web_v12 import configure

from mailhelp.mailbox_run import MailboxRunService
from mailhelp.metrics import MetricsRecorder, MetricsSettings


def failure(metrics, *, account="a" * 24, folder="Gesendet", event="optional_folder_failed", error="private secret"):
    metrics.observe(event, {"service": "imap", "account_id": account, "mailbox": 1, "folder": folder,
                            "error": error})


def test_failed_folder_is_visible_and_refreshes_status_without_a_failed_mail(web, tmp_path):
    _, metrics, *_ = configure(web, tmp_path)
    before = web.browser.request("GET", "/api/stand?seite=status", accept="application/json").body
    failure(metrics)
    after = web.browser.request("GET", "/api/stand?seite=status", accept="application/json").body
    assert before != after
    page = web.browser.request("GET", "/status").body.decode()
    assert "Aktuelle IMAP-Abruffehler" in page and "Gesendet" in page
    assert "Durchlauf kann deshalb unvollständig sein" in page
    assert "private secret" not in page
    assert metrics.runtime()["imap_errors"][0]["required"] is False
    metrics.observe("messages_discovered", {"service": "imap", "account_id": "a" * 24, "folder": "Gesendet",
                                           "available_count": 0})
    assert metrics.runtime()["imap_errors"] == []
    assert "Aktuelle IMAP-Abruffehler" not in web.browser.request("GET", "/status").body.decode()
    assert web.writer.created == 0


def test_folder_errors_are_isolated_repeated_and_cleared_by_success(tmp_path):
    metrics = MetricsRecorder(tmp_path / "metrics.jsonl", MetricsSettings(enabled=False))
    failure(metrics)
    failure(metrics, error="IMAP-Ordner nicht lesbar: Gesendet")
    assert len(metrics.runtime()["imap_errors"]) == 1
    assert metrics.runtime()["imap_errors"][0]["cause"] == "Ordner nicht lesbar"
    metrics.observe("messages_discovered", {"service": "imap", "account_id": "b" * 24, "folder": "Gesendet"})
    assert len(metrics.runtime()["imap_errors"]) == 1
    snapshot = metrics.runtime()
    snapshot["imap_errors"][0]["folder"] = "changed"
    assert metrics.runtime()["imap_errors"][0]["folder"] == "Gesendet"
    assert MetricsRecorder(tmp_path / "metrics.jsonl", MetricsSettings()).runtime()["imap_errors"] == []


@pytest.mark.parametrize("event", ["poll_failed", "optional_folder_failed"])
def test_folder_failure_logging_preserves_mailbox_identity_and_escapes_names(web, tmp_path, event):
    _, metrics, *_ = configure(web, tmp_path)
    logger = SimpleNamespace(event=lambda level, service, name, **context:
                             metrics.observe(name, {"service": service, **context}))
    folder = '<script>alert("unsafe")</script>'
    source = SimpleNamespace(account_id="a" * 24, mailbox=SimpleNamespace(id=1, primary_folder=
                              folder if event == "poll_failed" else "INBOX"))
    MailboxRunService._folder_failed(SimpleNamespace(logger=logger), source, folder, RuntimeError("secret"))
    page = web.browser.request("GET", "/status").body.decode()
    assert "&lt;script&gt;" in page and folder not in page and "secret" not in page
    assert ("Hauptordner" in page) is (event == "poll_failed")
    assert ("zusätzlicher Ordner" in page) is (event == "optional_folder_failed")
    assert metrics.runtime()["imap_errors"][0]["account_id"] == "a" * 24
    assert json.loads(web.browser.request("GET", "/api/stand?seite=status", accept="application/json").body)


@pytest.mark.parametrize("context", [{"service": "other", "folder": "INBOX"}, {"service": "imap"},
                                      {"service": "imap", "folder": None}])
def test_unrelated_or_incomplete_error_events_are_not_mailbox_failures(tmp_path, context):
    metrics = MetricsRecorder(tmp_path / "metrics.jsonl", MetricsSettings())
    metrics.observe("optional_folder_failed", context)
    metrics.observe("unknown_event", {"service": "imap", "folder": "INBOX"})
    assert metrics.runtime()["imap_errors"] == []
