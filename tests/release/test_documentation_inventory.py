"""5.3 H1: the documentation inventory is generated from the code and kept current."""
import runpy
import sys

import pytest

from devtools import inventory
from tests.fakes.shared_web_actions import web as web  # noqa: F401 - the fixture

TECHNICAL = ("/api/", "/static/", "/health", "/(?P<name>manifest")


def test_the_committed_inventory_is_current():
    assert inventory.main(["--check"]) == 0


def test_every_setting_has_a_way_to_change_it_and_every_option_is_listed():
    rows = inventory.settings_rows(inventory.REFERENCE.read_text(encoding="utf-8"))
    assert len(rows) > 200 and len({row.key for row in rows}) == len(rows)
    assert {row.path for row in rows} == {"Weboberfläche", "Einrichtung", "Datei"}
    keys = {row.key for row in rows}
    assert {"poll_interval_seconds", "write_verification.max_attempts", "imap.mailboxes[].host",
            "imap.mailboxes[].retention.full_mail_days", "iserv.accounts[].server"} <= keys
    options = dict(inventory.cli_rows())
    assert "--prepare-rollback" in options and "--clear" in options and "-h, --help" not in options


def test_an_outdated_inventory_is_detected_and_rewritten(tmp_path, monkeypatch, capsys):
    report, reference = tmp_path / "bericht.md", tmp_path / "referenz.md"
    report.write_text(f"Kopf\n{inventory.START}\nalt\n{inventory.END}\nFuß\n", encoding="utf-8")
    reference.write_text("`poll_interval_seconds`", encoding="utf-8")
    monkeypatch.setattr(inventory, "REPORT", report)
    monkeypatch.setattr(inventory, "REFERENCE", reference)
    assert inventory.main(["--check"]) == 1 and "veraltet" in capsys.readouterr().err
    assert inventory.main([]) == 0
    text = report.read_text(encoding="utf-8")
    assert text.startswith("Kopf\n") and text.endswith("\nFuß\n") and "| `poll_interval_seconds` |" in text
    assert inventory.main(["--check"]) == 0
    monkeypatch.setattr(sys, "argv", ["inventory", "--check"])
    with pytest.raises(SystemExit) as stop:
        runpy.run_module("devtools.inventory", run_name="__main__")
    assert stop.value.code == 0


def test_every_page_of_the_web_interface_is_inventoried(web):
    report = inventory.REPORT.read_text(encoding="utf-8")
    pages = {pattern.pattern.split("(?P")[0].rstrip("/") or "/" for method, pattern, _ in web.app._routes
             if method == "GET" and not pattern.pattern.startswith(TECHNICAL)}
    missing = [page for page in sorted(pages) if f"| `{page}" not in report]
    assert missing == []


def test_a_forward_reference_is_resolved_in_the_module_of_its_model():
    import typing

    from mailhelp.config.models import MailboxSettings, Settings
    resolved = inventory._resolved(typing.ForwardRef("Settings | None"), MailboxSettings)
    assert set(typing.get_args(resolved)) == {Settings, type(None)}
    assert inventory._resolved(int, MailboxSettings) is int
