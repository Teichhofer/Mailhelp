"""8.8.3 (Planung 8.8 AP3, Abnahme 4 und 5): a notice on every page while saved values wait for a restart.

Until 8.8.2 only the operator's settings overview said that saved changes were not active yet, and a
customer could not restart at all (``/einstellungen/neustarten`` was operator only). Synthetic data only.
"""
from __future__ import annotations

import re

import pytest
import yaml

from mailhelp.config import Settings
from mailhelp.runtime.lifecycle import Lifecycle, StopRefused
from mailhelp.web.banners import SystemBanner, render_banners
from mailhelp.web.factory import WebComponents
from tests.fakes.customer_mode import signed_in

PAGES = ("/", "/mails", "/themen", "/einstellungen", "/verbrauch", "/einstellungen/allgemein")
RESTART = "/einstellungen/neustarten"


@pytest.fixture
def customer(profiled):
    web = profiled.web
    web.auth.enter_customer_mode("kunde-a")
    web.browser = signed_in(web)
    components = WebComponents(None, web.auth, lambda: "", web.site)  # type: ignore[arg-type]
    profiled.app.configuration.restricted = lambda actor: not components.authorize_operator(actor)
    profiled.stops = []
    # As in the composition: only the operator stops, every live session may restart.
    lifecycle = Lifecycle(lambda: profiled.stops.append("stop"), components.authorize_operator,
                          authorize_restart=components.authorize)
    web.site.lifecycle = web.site.archive.lifecycle = profiled.lifecycle = lifecycle
    return profiled


def save(profiled, **values):
    web = profiled.web
    fields = {**web.form("/einstellungen/allgemein", action="/einstellungen/allgemein"),
              **{f"setting:{name}": value for name, value in values.items()}}
    review = web.browser.request("POST", "/einstellungen/allgemein", fields).body.decode()
    hidden = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', review))
    assert web.browser.request("POST", "/einstellungen/allgemein", hidden).status == 303
    web.run()


def banner(profiled, path):
    return 'data-banner="restart"' in profiled.web.browser.request("GET", path).body.decode()


def test_regression_the_restart_notice_follows_the_customer_and_the_restart_is_theirs(customer):
    web = customer.web
    assert not any(banner(customer, path) for path in PAGES)
    save(customer, timezone="Europe/Vienna")  # applies at the next start
    for path in PAGES:
        page = web.browser.request("GET", path).body.decode()
        assert 'data-banner="restart"' in page and f'href="{RESTART}"' in page, path
    confirm = web.form(RESTART, action=RESTART)
    unconfirmed = {name: value for name, value in confirm.items() if name != "confirm"}
    assert web.browser.request("POST", RESTART, unconfirmed).status == 409
    requested = web.browser.request("POST", RESTART, {**confirm, "confirm": "yes"})
    assert requested.status == 202 and customer.lifecycle.state == "restart_requested"
    requested.after_send()
    assert customer.stops == ["stop"] and customer.lifecycle.restart_requested
    assert not banner(customer, "/")  # no notice while restarting
    # After the start the process uses the saved file: the notice is gone.
    customer.lifecycle.state = "running"
    customer.app.configuration.active = Settings.model_validate(
        yaml.safe_load((customer.tmp_path / "config.yaml").read_text(encoding="utf-8")))
    assert not any(banner(customer, path) for path in PAGES)


def test_live_values_need_no_restart_and_stopping_stays_with_the_operator(customer):
    web = customer.web
    save(customer, personal_info="Synthetische Angabe")
    assert not banner(customer, "/")
    assert web.browser.request("GET", "/einstellungen/beenden").status == 403
    me = web.auth.authenticate(web.browser.cookies["mh_session"])
    with pytest.raises(StopRefused, match="Nicht autorisierte"):
        customer.lifecycle.request(customer.lifecycle.process, "a" * 32, f"web:{me.id}")
    assert customer.stops == []


def test_a_restart_needs_a_live_session_when_it_runs(customer):
    web = customer.web
    me = web.auth.authenticate(web.browser.cookies["mh_session"])
    after = customer.lifecycle.request(customer.lifecycle.process, "b" * 32, f"web:{me.id}", restart=True)
    web.auth.revoke(me.id)  # signed out before the response was sent
    after()
    assert customer.stops == [] and customer.lifecycle.state == "running"


def test_no_notice_without_a_lifecycle_or_configuration(customer):
    save(customer, timezone="Europe/Vienna")
    site = customer.web.site
    site.lifecycle = None
    assert site.banners() == ()
    site.lifecycle = customer.lifecycle
    configuration, site.archive.configuration = site.archive.configuration, None
    assert site.banners() == ()
    site.archive.configuration = configuration
    assert site.banners()[0].action_href == RESTART


def test_start_differences_files_and_the_cache(customer, tmp_path):
    configuration = customer.app.configuration
    path = customer.tmp_path / "config.yaml"
    assert configuration.restart_pending() is False
    # A section that differed at the start (e.g. a start parameter) is no pending restart.
    from mailhelp.config.configuration import ConfigurationService
    started = configuration.active.model_copy(update={"poll_interval_seconds": 999})
    other = ConfigurationService(customer.tmp_path, customer.web.store, started, lambda actor: True, lambda s: None)
    assert other.restart_pending() is False
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["timezone"] = "Europe/Vienna"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert other.restart_pending() is True and other.restart_pending() is True  # second answer from the cache
    path.write_text("[kein: gültiges", encoding="utf-8")
    assert other.restart_pending() is False  # an unreadable file is no reason to restart
    path.unlink()
    assert other.restart_pending() is False
    missing = ConfigurationService(tmp_path / "fehlt", customer.web.store, started, lambda actor: True, lambda s: None)
    assert missing.restart_pending() is False


def test_banners_are_escaped_and_errors_are_alerts():
    html = render_banners((SystemBanner("x", "error", "<b>Text</b>", "/a?b=1&c=2", "Los"),
                           SystemBanner("y", "info", "Nur Text")))
    assert 'role="alert"' in html and "&lt;b&gt;Text&lt;/b&gt;" in html and 'href="/a?b=1&amp;c=2"' in html
    assert 'data-banner="y"' in html and html.count("<a ") == 1
