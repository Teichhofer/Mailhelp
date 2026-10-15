"""Credentials in the web interface, write-only (3.3.11): real sessions, CSRF, confirmation, idempotency."""
from __future__ import annotations

import re
from html import unescape

import pytest
import yaml

ROUTE = "/einstellungen/zugangsdaten"
SAVE = ROUTE + "/speichern"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ("IMAP_1_USERNAME", "IMAP_1_PASSWORD", "ISERV_1_PASSWORD", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def form_for(profiled, name: str) -> dict:
    html = profiled.web.browser.request("GET", ROUTE).body.decode()
    for block in re.findall(rf'<form method="post" action="{SAVE}"[^>]*>(.*?)</form>', html, re.S):
        fields = {key: unescape(value) for key, value in
                  re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', block)}
        if fields.get("name") == name:
            return fields
    raise AssertionError(f"kein Formular für {name}")


def save(profiled, secret: str, value: str, **changes):
    return profiled.web.browser.request("POST", SAVE, {**form_for(profiled, secret), "value": value,
                                                       "confirm": "yes", **changes})


def env(profiled) -> str:
    path = profiled.tmp_path / ".env"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_lists_needed_credentials_without_ever_showing_a_value(profiled):
    (profiled.tmp_path / ".env").write_text("# lokal\nIMAP_1_PASSWORD=streng-geheim\n", encoding="utf-8")
    page = profiled.web.browser.request("GET", ROUTE).body.decode()
    assert "Postfach 1" in page and "Postfach 2" in page and "OPENROUTER_API_KEY</strong> · fehlt" in page
    assert "IMAP_1_PASSWORD</strong> · hinterlegt" in page and "streng-geheim" not in page
    assert 'type="password" name="value" autocomplete="off"' in page and "MAILHELP_WEB_SECRET</strong>" not in page
    assert 'id="secret-imap-1-username" type="text"' in page


def test_saving_writes_only_the_line_redacts_and_logs_the_name(profiled):
    (profiled.tmp_path / ".env").write_text("# lokal\nOTHER=x\n", encoding="utf-8")
    profiled.app.logger.secrets = ()
    response = save(profiled, "OPENROUTER_API_KEY", "sk-synthetisch")
    assert response.status == 303 and response.headers["Location"] == ROUTE + "?gespeichert=OPENROUTER_API_KEY"
    assert env(profiled) == "# lokal\nOTHER=x\nOPENROUTER_API_KEY=sk-synthetisch\n"
    assert "sk-synthetisch" in profiled.app.logger.secrets
    assert (("INFO", "web", "secret_saved"), {"name": "OPENROUTER_API_KEY"}) in profiled.web.logger.events
    page = profiled.web.browser.request("GET", ROUTE + "?gespeichert=OPENROUTER_API_KEY").body.decode()
    assert "OPENROUTER_API_KEY gespeichert" in page and "OPENROUTER_API_KEY</strong> · hinterlegt" in page
    assert "sk-synthetisch" not in page
    assert "gespeichert" not in profiled.web.browser.request("GET", ROUTE + "?gespeichert=x%3Cy").body.decode()


def test_repeats_conflicts_and_invalid_requests_write_nothing(profiled):
    form = form_for(profiled, "IMAP_1_USERNAME")
    first = {**form, "value": "eltern@example.test", "confirm": "yes"}
    assert profiled.web.browser.request("POST", SAVE, first).status == 303
    assert profiled.web.browser.request("POST", SAVE, first).status == 303  # same key: no second write
    other = {**first, "name": "IMAP_1_PASSWORD"}
    assert profiled.web.browser.request("POST", SAVE, other).status == 409
    stale = {**form_for(profiled, "IMAP_1_PASSWORD"), "value": "x", "confirm": "yes", "expected_hash": "0" * 64}
    assert profiled.web.browser.request("POST", SAVE, stale).status == 409
    assert save(profiled, "IMAP_1_PASSWORD", "a\x01b").status == 422
    assert save(profiled, "IMAP_1_PASSWORD", "x", confirm="").status == 422
    assert save(profiled, "IMAP_1_PASSWORD", "x", key="kurz").status == 422
    assert save(profiled, "IMAP_1_PASSWORD", "x", name="PATH").status == 422
    assert save(profiled, "IMAP_1_PASSWORD", "x", name="MAILHELP_WEB_SECRET").status == 422
    assert env(profiled) == "IMAP_1_USERNAME=eltern@example.test\n"


def test_expired_sessions_and_read_only_files_are_reported(profiled, monkeypatch):
    form = {**form_for(profiled, "IMAP_1_PASSWORD"), "value": "x", "confirm": "yes"}
    monkeypatch.setattr(profiled.web.auth, "active", lambda session: False)
    assert profiled.web.browser.request("POST", SAVE, form).status == 403
    monkeypatch.undo()

    def read_only(path, content):
        raise PermissionError("read-only")
    monkeypatch.setattr("mailhelp.env_file.atomic_replace", read_only)
    assert profiled.web.browser.request("POST", SAVE, form).status == 503
    assert env(profiled) == ""


def test_draft_iserv_accounts_and_process_variables_are_shown(profiled, monkeypatch):
    raw = yaml.safe_load((profiled.tmp_path / "config.yaml").read_text(encoding="utf-8"))
    raw["iserv"] = {"accounts": [{"id": 1, "server": "https://schule.example", "enabled": False}]}
    raw["telegram"]["enabled"] = False
    raw["web"]["enabled"] = True
    (profiled.tmp_path / "config.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    monkeypatch.setenv("ISERV_1_PASSWORD", "aus-der-umgebung")
    page = profiled.web.browser.request("GET", ROUTE).body.decode()
    assert "IServ-Konto 1 (Elternbriefe)" in page and "ISERV_1_PASSWORD</strong> · hinterlegt" in page
    assert "In der Prozessumgebung gesetzt" in page and "aus-der-umgebung" not in page
    assert "TELEGRAM_BOT_TOKEN" not in page


def test_secret_page_needs_the_setup_service_and_is_linked(profiled):
    browser = profiled.web.browser
    assert 'href="/einstellungen/zugangsdaten"' in browser.request("GET", "/einrichtung").body.decode()
    form = form_for(profiled, "IMAP_1_PASSWORD")
    profiled.web.site.setup_page.runtime = None
    assert browser.request("GET", ROUTE).status == 503
    assert browser.request("POST", SAVE, {**form, "value": "x", "confirm": "yes"}).status == 503
