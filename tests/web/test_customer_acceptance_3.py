"""8.7 §10 Abnahme 3 (8.7.15): a customer session changes its own mailbox, targets, notifications and topics.

Regression: until 8.7.14 a customer could save a mailbox draft but never approve it. The preview posted to
the operator route ``/einrichtung/uebernehmen`` (403), and every ``imap.`` field, even a quiet hour, needed
an IMAP diagnosis on ``/diagnose``, which customers cannot open. Synthetic data, simulated checks only.
"""
from __future__ import annotations

import re

import pytest
import yaml

from mailhelp.config.configuration import AdminCommand, AdminKind, customer_command_allowed
from mailhelp.runtime.setup import DIAGNOSED, changes_connection
from mailhelp.web.factory import WebComponents
from mailhelp.web.permissions import customer_may
from tests.fakes.customer_mode import signed_in

MAILBOX = "/einstellungen/postfaecher"
APPLY, CHECK = MAILBOX + "/uebernehmen", MAILBOX + "/pruefen"


@pytest.fixture
def customer(profiled):
    web = profiled.web
    web.auth.enter_customer_mode("kunde-a")
    profiled.operator = signed_in(web, "operator", "Support")
    web.browser = signed_in(web)
    # As in composition: a customer command carries customer fields only, checked again before writing.
    components = WebComponents(None, web.auth, lambda: "", web.site)  # type: ignore[arg-type]
    profiled.app.configuration.restricted = lambda actor: not components.authorize_operator(actor)
    profiled.checked = []
    for name in profiled.runtime.diagnostics.checks:
        profiled.runtime.diagnostics.checks[name] = lambda actor, name=name: profiled.checked.append(name) or (
            "ready", "")
    return profiled


def config(profiled):
    return yaml.safe_load((profiled.tmp_path / "config.yaml").read_text(encoding="utf-8"))


def save(profiled, tab, field, value):
    web = profiled.web
    form = web.form(f"{MAILBOX}/2?tab={tab}", action=MAILBOX + "/speichern", field=field)
    assert web.browser.request("POST", MAILBOX + "/speichern", {**form, "value": value}).status == 303


def approve(profiled):
    web = profiled.web
    page = web.browser.request("GET", MAILBOX).body.decode()
    for action in re.findall(r'<form method="post" action="([^"]+)"', page):
        assert customer_may("POST", action), action  # every offered step works in this session
    form = web.form(MAILBOX, action=APPLY)
    assert web.browser.request("POST", APPLY, form).status == 422  # not confirmed: nothing queued
    response = web.browser.request("POST", APPLY, {**form, "confirm": "yes"})
    assert response.status == 303 and customer_may("GET", response.headers["Location"].split("?")[0])
    assert web.browser.request("POST", APPLY, {**form, "confirm": "yes"}).status in (303, 409)  # same key again
    web.run()
    return config(profiled)


def test_regression_a_customer_approves_own_mailbox_settings_without_operator_routes(customer):
    save(customer, "notifications", "notifications.quiet_hours.enabled", "true")
    save(customer, "replies", "personal_info", "Synthetische Signatur")
    assert customer.runtime.setup.missing_checks() == []  # policies change no connection
    assert APPLY in customer.web.browser.request("GET", MAILBOX).body.decode()
    box = approve(customer)["imap"]["mailboxes"][1]
    assert box["notifications"]["quiet_hours"]["enabled"] is True
    assert box["personal_info"] == "Synthetische Signatur"
    assert customer.checked == [] and customer.web.writer.created == 0
    assert customer.runtime.setup.state().patch == {}


def test_acceptance_3_targets_need_a_read_only_check_the_customer_can_run(customer):
    web = customer.web
    save(customer, "targets", "target_profile", "1")
    missing = customer.runtime.setup.missing_checks()
    assert missing == ["calendar", "todoist"]
    page = web.browser.request("GET", MAILBOX).body.decode()
    assert all(f'value="{name}"' in page for name in missing)
    form = web.form(MAILBOX, action=APPLY)
    assert web.browser.request("POST", APPLY, {**form, "confirm": "yes"}).status == 409  # check missing
    for name in missing:
        check = web.form(MAILBOX, action=CHECK, name=name)
        assert web.browser.request("POST", CHECK, check).status == 303
    assert customer.checked == missing and customer.runtime.setup.missing_checks() == []
    assert approve(customer)["imap"]["mailboxes"][1]["target_profile"] == 1
    assert web.writer.created == 0  # a check reads only; nothing is created


def test_acceptance_3_topics_of_an_own_mailbox(customer):
    web = customer.web
    form = web.form(f"{MAILBOX}/2?tab=topics", action=MAILBOX + "/thema", scope="exclude", category="relevant")
    assert web.browser.request("POST", MAILBOX + "/thema", form).status == 303
    approve(customer)
    topics = yaml.safe_load((customer.tmp_path / "topics.yaml").read_text(encoding="utf-8"))["topics"]
    assert topics[0]["mailboxes"] == [1]


def test_a_customer_runs_only_read_only_checks_of_own_connections(customer):
    web = customer.web
    save(customer, "targets", "target_profile", "1")
    check = web.form(MAILBOX, action=CHECK, name="calendar")
    for name in ("llm_test", "telegram_test", "push_test", "iserv", "filesystem", "llm", "calendar:100", ""):
        assert web.browser.request("POST", CHECK, {**check, "name": name}).status == 409, name
    assert web.browser.request("POST", CHECK, {**check, "version": "x"}).status == 409
    assert customer.checked == []
    approval = web.form(MAILBOX, action=APPLY)
    web.site.setup_page.runtime = None
    assert web.browser.request("POST", CHECK, check).status == 503
    assert web.browser.request("POST", APPLY, {**approval, "confirm": "yes"}).status == 503


def test_connection_fields_still_need_their_diagnosis():
    imap = DIAGNOSED["imap"]
    for field in ("imap.host", "imap.mailboxes", "imap.mailboxes.1.host", "imap.mailboxes.0.folders",
                  "imap.mailboxes.1.enabled", "imap.mailboxes.1.connection_mode"):
        assert changes_connection(field, imap), field
    for field in ("imap.mailboxes.1.label", "imap.mailboxes.1.personal_info",
                  "imap.mailboxes.0.notifications.quiet_hours.start", "imap.mailboxes.1.target_profile",
                  "personal_info", "targets.google_calendar"):
        assert not changes_connection(field, imap), field
    assert changes_connection("targets.google_calendar", DIAGNOSED["calendar"])


def test_a_customer_cannot_approve_an_operator_draft(customer):
    web, runtime = customer.web, customer.runtime
    operator = web.auth.authenticate(customer.operator.cookies["mh_session"])
    runtime.setup.save(f"web:{operator.id}", runtime.setup.state().version, "operator-draft", 6, {"push.subject": "mailto:support@example.invalid"})
    before = (customer.tmp_path / "config.yaml").read_text(encoding="utf-8")
    form = web.form(MAILBOX, action=APPLY)
    assert web.browser.request("POST", APPLY, {**form, "confirm": "yes"}).status == 303
    web.run()
    assert (customer.tmp_path / "config.yaml").read_text(encoding="utf-8") == before
    assert runtime.setup.state().patch == {"push.subject": "mailto:support@example.invalid"}  # left for the operator


def test_own_mailboxes_may_be_added_and_removed_but_operator_fields_stay_closed(customer):
    current = customer.app.configuration.configured_mailboxes()
    def allowed(patch, boxes=current):
        return customer_command_allowed(AdminCommand(kind=AdminKind.SETUP, actor="web:" + "a" * 16,
                                                     idempotency_key="mailboxes-1", expected_hash="0" * 64,
                                                     patch=patch, acknowledged=True), boxes)
    assert allowed({"imap.mailboxes": current[:1]})  # removed
    assert allowed({"imap.mailboxes": [*current, {**current[0], "id": 3}]})  # added
    assert allowed({"imap.mailboxes": [{**current[0], "label": "Neu"}, current[1]]})
    assert not allowed({"imap.mailboxes": [{**current[0], "unknown": 1}, current[1]]})
    assert not allowed({"imap.mailboxes": current}, None)  # never without the current list
    assert not allowed({"imap.mailboxes": current, "telegram.enabled": False})
    assert allowed({"timezone": "Europe/Vienna"}, None)


def test_a_mailbox_list_counts_by_its_differing_leaves():
    from mailhelp.config.configuration import changed_fields
    before = [{"id": 1, "label": "A", "retention": {"full_mail_days": 30}, "notifications": None}]
    after = [{"id": 1, "label": "A", "retention": "disabled",
              "notifications": {"quiet_hours": {"enabled": True, "start": None}}}]
    assert changed_fields({"imap.mailboxes": after, "timezone": "UTC"}, before) == [
        "timezone", "imap.mailboxes.0.notifications.quiet_hours.enabled", "imap.mailboxes.0.retention"]
    assert changed_fields({"imap.mailboxes": before}, before) == []
    assert changed_fields({"imap.mailboxes": []}, before) == ["imap.mailboxes"]
