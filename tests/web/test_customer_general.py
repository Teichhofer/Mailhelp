"""8.8.2 (Planung 8.8 AP2, Abnahme 3 und 6): a customer changes own personal values on ``/einstellungen/allgemein``.

Regression: until 8.8.1 these values were customer fields, but their only form posted to the operator route
``/einstellungen/speichern`` (403), so a customer session could not change them at all. Synthetic data only.
"""
from __future__ import annotations

import re

import pytest
import yaml

from mailhelp.config.configuration import SETTINGS_FIELDS, customer_may_change
from mailhelp.web.factory import WebComponents
from mailhelp.web.permissions import customer_may
from tests.fakes.customer_mode import signed_in

GENERAL = "/einstellungen/allgemein"


@pytest.fixture
def customer(profiled):
    web = profiled.web
    web.auth.enter_customer_mode("kunde-a")
    web.browser = signed_in(web)
    components = WebComponents(None, web.auth, lambda: "", web.site)  # type: ignore[arg-type]
    profiled.app.configuration.restricted = lambda actor: not components.authorize_operator(actor)
    return profiled


def config(profiled):
    return yaml.safe_load((profiled.tmp_path / "config.yaml").read_text(encoding="utf-8"))


def form(profiled):
    page = profiled.web.browser.request("GET", GENERAL)
    assert page.status == 200
    for action in re.findall(r'<form method="post" action="([^"]+)"', page.body.decode()):
        assert customer_may("POST", action), action
    return profiled.web.form(GENERAL, action=GENERAL)


def test_regression_a_customer_saves_own_values_with_review_and_confirmation(customer):
    web = customer.web
    fields = {**form(customer), "setting:timezone": "Europe/Vienna", "setting:language": "en",
              "setting:event_defaults.video_duration_minutes": "45",
              "setting:targets.calendar_reminder_enabled": "true", "setting:targets.calendar_reminder_minutes": "15"}
    review = web.browser.request("POST", GENERAL, fields)
    assert review.status == 200 and f'action="{GENERAL}"' in review.body.decode()
    assert config(customer)["timezone"] != "Europe/Vienna"  # nothing before the confirmation
    hidden = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', review.body.decode()))
    queued = web.browser.request("POST", GENERAL, hidden)
    assert queued.status == 303 and customer_may("GET", queued.headers["Location"])
    assert any(cookie.startswith("mailhelp_lang=en") for cookie in queued.cookies)
    web.run()
    saved = config(customer)
    assert saved["timezone"] == "Europe/Vienna" and saved["language"] == "en"
    assert saved["event_defaults"]["video_duration_minutes"] == 45
    assert saved["targets"]["calendar_reminder_enabled"] is True and saved["targets"]["calendar_reminder_minutes"] == 15
    assert web.writer.created == 0  # saving never writes to a calendar or task list
    again = web.browser.request("POST", GENERAL, hidden)  # repeated after the change: nothing left to take over
    assert again.status == 200 and "<h1>No change</h1>" in again.body.decode()
    web.run()
    assert config(customer) == saved


def test_acceptance_6_operator_fields_are_refused_before_any_command(customer):
    web = customer.web
    fields = form(customer)
    before = config(customer)
    for extra in ({"setting:dry_run": "true"}, {"setting:telegram.chat_id": "1"}, {"zuruecksetzen": "llm.model"},
                  {"name": "timezone", "value": "UTC"}):
        assert web.browser.request("POST", GENERAL, {**fields, **extra, "confirm": "yes"}).status == 403, extra
    assert web.browser.request("POST", "/einstellungen/speichern", {**fields, "confirm": "yes"}).status == 403
    web.run()
    assert config(customer) == before


def test_unchanged_invalid_and_unavailable(customer):
    web = customer.web
    fields = form(customer)
    unchanged = web.browser.request("POST", GENERAL, fields).body.decode()
    assert "Keine Änderung" in unchanged and f'href="{GENERAL}"' in unchanged
    invalid = web.browser.request("POST", GENERAL, {**fields, "setting:targets.calendar_reminder_minutes": "5000"})
    assert invalid.status == 422
    web.site.archive.configuration = None
    assert "Konfigurationsdienst nicht verfügbar" in web.browser.request("GET", GENERAL).body.decode()
    assert web.browser.request("POST", GENERAL, fields).status == 503


def test_the_overview_leads_to_the_page_and_every_field_is_a_customer_field(customer):
    from mailhelp.web.customer_settings import GENERAL_FIELDS

    overview = customer.web.browser.request("GET", "/einstellungen").body.decode()
    assert f'href="{GENERAL}"' in overview
    assert set(GENERAL_FIELDS) <= SETTINGS_FIELDS
    assert all(customer_may_change(name) for name in GENERAL_FIELDS)
    page = customer.web.browser.request("GET", GENERAL).body.decode()
    assert all(f'name="setting:{name}"' in page for name in GENERAL_FIELDS)
