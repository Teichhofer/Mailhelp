"""IServ accounts through the authenticated draft (3.3.10): real sessions, CSRF, versions and approval."""
from __future__ import annotations

import re
from html import unescape
from uuid import uuid4

import pytest
import yaml

from mailhelp.setup import SetupService

ROUTE = "/einstellungen/iserv"
SAVE = ROUTE + "/speichern"


def config(profiled) -> dict:
    return yaml.safe_load((profiled.tmp_path / "config.yaml").read_text(encoding="utf-8"))


def submit(profiled, action: str, index: int = 0, **values):
    return profiled.web.browser.request("POST", SAVE, {**_form(profiled, action, index), **values})


def _form(profiled, action: str, index: int = 0) -> dict:
    """Hidden fields of the index-th save form with this action (its field is also named "action")."""
    html = profiled.web.browser.request("GET", ROUTE).body.decode()
    forms = []
    for block in re.findall(rf'<form method="post" action="{SAVE}"[^>]*>(.*?)</form>', html, re.S):
        fields = {name: unescape(value) for name, value in
                  re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', block)}
        if fields.get("action") == action:
            forms.append(fields)
    return forms[index]


def approve(profiled, diagnosed: bool = True):
    runtime, web = profiled.runtime, profiled.web
    runtime.update_profile_checks()
    if diagnosed:
        for name in runtime.diagnostics.checks:
            runtime.diagnostics.checks[name] = lambda _: ("ready", "")
            runtime.diagnostics.run(web.auth.sessions()[0].id, name, runtime.diagnostics.state().version,
                                    f"probe-{name.replace(':', '-')}-{uuid4().hex[:8]}")
    form = web.form(ROUTE, action="/einrichtung/uebernehmen")
    status = web.browser.request("POST", "/einrichtung/uebernehmen", {**form, "confirm": "yes"}).status
    web.run()
    return status


NEW = {"label": "Grundschule", "server": "https://Schule.example/", "mailbox": "2",
       "historical_start": "2026-10-01T00:00:00+02:00"}


@pytest.mark.parametrize(("start", "zone", "expected"), [
    ("01.09.2026", "Europe/Berlin", "2026-09-01T00:00:00+02:00"),
    ("2026-09-01", "Europe/Berlin", "2026-09-01T00:00:00+02:00"),
    (" 01.12.2026 ", "Europe/Berlin", "2026-12-01T00:00:00+01:00"),
    ("01.09.2026", "America/New_York", "2026-09-01T00:00:00-04:00"),
])
def test_regression_calendar_date_is_saved_as_local_midnight(profiled, start, zone, expected):
    """A calendar date used to fail with the generic draft/session error (HTTP 409)."""
    raw = config(profiled)
    raw["timezone"] = zone
    (profiled.tmp_path / "config.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    before = (profiled.tmp_path / "config.yaml").read_bytes()
    form = {**_form(profiled, "add"), **NEW, "historical_start": start}
    browser = profiled.web.browser
    assert browser.request("POST", SAVE, form).status == 303
    state = profiled.runtime.setup.state()
    assert state.patch["iserv.accounts"][0]["historical_start"] == expected
    # After a restart the saved draft remains intact; a repeated add creates no duplicate.
    profiled.runtime.setup = SetupService(profiled.app.configuration)
    assert browser.request("POST", SAVE, form).status == 409
    assert profiled.runtime.setup.state() == state
    assert (profiled.tmp_path / "config.yaml").read_bytes() == before
    assert approve(profiled) == 303
    assert config(profiled)["iserv"]["accounts"][0]["historical_start"] == expected
    assert submit(profiled, "update", **{**NEW, "historical_start": start}).status == 303
    assert profiled.runtime.setup.draft_settings().iserv.accounts[0].historical_start.isoformat() == expected


def test_add_change_deactivate_and_remove_an_account_only_after_approval(profiled):
    page = profiled.web.browser.request("GET", ROUTE).body.decode()
    assert "IServ-Konto hinzufügen" in page and "ISERV_1_USERNAME und ISERV_1_PASSWORD" in page
    before = (profiled.tmp_path / "config.yaml").read_bytes()
    assert submit(profiled, "add", **NEW).status == 303
    assert (profiled.tmp_path / "config.yaml").read_bytes() == before
    page = profiled.web.browser.request("GET", ROUTE).body.decode()
    assert "IServ-Konto 1 (Grundschule)" in page and "https://schule.example · Postfach 2 · aktiv" in page
    assert approve(profiled) == 303
    assert config(profiled)["iserv"]["accounts"] == [{
        "id": 1, "label": "Grundschule", "enabled": True, "server": "https://schule.example", "mailbox": 2,
        "historical_start": "2026-10-01T00:00:00+02:00"}]
    assert submit(profiled, "update", label="Gymnasium", server="https://schule.example", mailbox="1",
                  historical_start="").status == 303
    assert approve(profiled) == 303
    account = config(profiled)["iserv"]["accounts"][0]
    assert (account["label"], account["mailbox"], account["historical_start"]) == ("Gymnasium", 1, None)
    assert submit(profiled, "toggle").status == 303 and approve(profiled) == 303
    assert config(profiled)["iserv"]["accounts"][0]["enabled"] is False
    assert "Aktivieren" in profiled.web.browser.request("GET", ROUTE).body.decode()
    assert submit(profiled, "remove").status == 303
    assert "<dt>IServ-Konten</dt><dd>keine</dd>" in profiled.web.browser.request("GET", ROUTE).body.decode()
    assert approve(profiled) == 303 and config(profiled)["iserv"]["accounts"] == []


def test_connection_changes_need_a_current_diagnosis_but_removal_of_all_does_not(profiled):
    assert submit(profiled, "add", **NEW).status == 303
    assert approve(profiled, diagnosed=False) == 422
    assert config(profiled)["iserv"]["accounts"] == []
    runtime = profiled.runtime
    assert approve(profiled) == 303
    assert submit(profiled, "remove").status == 303
    session = profiled.web.auth.sessions()[0].id
    runtime.diagnostics.checks["iserv"] = runtime.iserv  # the real check again
    runtime.diagnostics.run(session, "iserv", runtime.diagnostics.state().version, "probe-disabled")
    assert runtime.diagnostics.state().results["iserv"].status == "disabled"
    assert approve(profiled, diagnosed=False) == 303 and config(profiled)["iserv"]["accounts"] == []


def test_invalid_or_stale_changes_keep_the_draft(profiled):
    for values in ({**NEW, "server": "http://schule.example"}, {**NEW, "mailbox": "7"},
                   {**NEW, "historical_start": "gestern"}):
        assert submit(profiled, "add", **values).status == 409
    assert submit(profiled, "add", **NEW).status == 303
    form = _form(profiled, "add")
    for changes in ({"id": "1"}, {"action": "rename"}, {"action": "update", "id": "9"}, {"action": "toggle", "id": "9"}):
        assert profiled.web.browser.request("POST", SAVE, {**form, **NEW, **changes}).status == 409
    assert profiled.runtime.setup.draft_settings().iserv.accounts[0].label == "Grundschule"


@pytest.mark.parametrize("start", ["31.09.2026", "2026-02-29", "01.09.26", "2026-09-01T12:00:00"])
def test_invalid_calendar_dates_and_naive_timestamps_keep_the_draft(profiled, start):
    before = profiled.runtime.setup.state()
    assert submit(profiled, "add", **{**NEW, "historical_start": start}).status == 409
    assert profiled.runtime.setup.state() == before
    assert config(profiled)["iserv"]["accounts"] == []


def test_calendar_date_changes_still_require_csrf_version_and_session(profiled, monkeypatch):
    web = profiled.web
    form = {**_form(profiled, "add"), **NEW, "historical_start": "01.09.2026"}
    before = profiled.runtime.setup.state()
    assert web.browser.request("POST", SAVE, {**form, "csrf": "invalid"}).status == 403
    assert web.browser.request("POST", SAVE, {**form, "version": "99"}).status == 409
    with monkeypatch.context() as patch:
        patch.setattr(web.auth, "active", lambda session: False)
        assert web.browser.request("POST", SAVE, form).status == 409
    assert profiled.runtime.setup.state() == before
    assert web.browser.request("POST", SAVE, form).status == 303
    state = profiled.runtime.setup.state()
    assert web.browser.request("POST", SAVE, {**form, "historical_start": "02.09.2026"}).status == 409
    assert profiled.runtime.setup.state() == state


def test_ten_accounts_fill_every_number_and_labels_default(profiled):
    raw = config(profiled)
    raw["iserv"] = {"accounts": [{"id": number, "server": f"https://s{number}.example"} for number in range(1, 10)]}
    (profiled.tmp_path / "config.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert submit(profiled, "add", label=" ", server="https://s10.example", mailbox="1", historical_start="").status == 303
    accounts = profiled.runtime.setup.draft_settings().iserv.accounts
    assert accounts[-1].id == 10 and accounts[-1].label == "Elternbriefe"
    assert "bereits zehn IServ-Konten" in profiled.web.browser.request("GET", ROUTE).body.decode()


def test_pages_are_linked_and_need_the_setup_service(profiled):
    browser = profiled.web.browser
    assert 'href="/einstellungen/iserv"' in browser.request("GET", "/einstellungen/postfaecher").body.decode()
    assert 'href="/einstellungen/iserv"' in browser.request("GET", "/einrichtung").body.decode()
    form = _form(profiled, "add")
    profiled.web.site.setup_page.runtime = None
    assert browser.request("GET", ROUTE).status == 503
    assert browser.request("POST", SAVE, {**form, **NEW}).status == 503


def test_regression_pages_stay_usable_after_an_approved_mailbox(profiled):
    """Regression: the approved draft stayed on the old file and the mailbox page failed afterwards."""
    web = profiled.web
    form = web.form("/einstellungen/postfaecher", action="/einstellungen/postfaecher/speichern")
    added = {**form, "id": "3", "label": "Verein", "host": "imap.example", "port": "993", "folders": "INBOX"}
    assert web.browser.request("POST", "/einstellungen/postfaecher/speichern", added).status == 303
    assert approve(profiled) == 303
    assert [box["id"] for box in config(profiled)["imap"]["mailboxes"]] == [1, 2, 3]
    assert profiled.runtime.setup.state().patch == {}
    for page in ("/einstellungen/postfaecher", ROUTE, "/einrichtung"):
        assert web.browser.request("GET", page).status == 200
    assert submit(profiled, "add", **NEW).status == 303
