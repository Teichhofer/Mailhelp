"""8.7 §4: customer mode – roles bound to sessions, deny by default, operator access at the host.

Abnahme 1, 2, 4–7, 16 and 18 with synthetic sessions only; the OpenRouter key never appears.
"""
from __future__ import annotations

import pytest

from mailhelp.config.configuration import AdminCommand, AdminKind, customer_may_change, file_hash
from mailhelp.review.results import ResultStatus
from mailhelp.runtime.instance_mode import InstanceMode, InstanceModeError, load_instance_mode
from mailhelp.runtime.lifecycle import StopRefused
from mailhelp.web.auth import PAIRING, SESSIONS
from mailhelp.web.factory import WebComponents
from mailhelp.web.local_pairing import issue, signature
from mailhelp.web.permissions import customer_may
from tests.fakes.customer_mode import session_of, signed_in
from tests.fakes.shared_web_actions import web  # noqa: F401  (fixture)
from tests.fakes.shared_web_auth import SECRET, Browser
from tests.fakes.shared_web_v12 import configure

OPERATOR_PAGES = ["/status", "/diagnose", "/auswertung", "/auswertung/aufrufe", "/einstellungen",
                  "/einstellungen/zugangsdaten", "/einstellungen/neustarten", "/einstellungen/beenden", "/abgleich",
                  "/einrichtung", "/api/einstellungen/suche"]


@pytest.fixture
def customer(web):
    web.auth.enter_customer_mode("kunde-a")
    return web


def test_acceptance_18_activation_revokes_role_less_sessions_and_codes(web):
    web.auth.issue_code()
    assert web.browser.request("GET", "/").status == 200
    assert web.auth.enter_customer_mode("kunde-a") == 1
    assert web.browser.request("GET", "/").status == 303  # the earlier session is not adopted as operator
    assert web.store.load(PAIRING)["codes"] == [] and web.store.load(SESSIONS)["sessions"] == []
    assert web.auth.enter_customer_mode("kunde-a") == 0  # every later start changes nothing more
    browser = signed_in(web)
    assert web.auth.enter_customer_mode("kunde-a") == 0 and browser.request("GET", "/").status == 200


def test_the_start_applies_customer_mode_and_makes_telegram_a_customer_channel(customer):
    from types import SimpleNamespace

    from mailhelp.app.composition import _apply_instance_mode
    operator = session_of(customer, signed_in(customer, "operator", "Support"))
    session_of(customer, signed_in(customer))
    application = SimpleNamespace(logger=customer.logger, dialog=SimpleNamespace(web_logout=None))
    components = SimpleNamespace(auth=customer.auth)
    _apply_instance_mode(application, components, InstanceMode())  # type: ignore[arg-type]
    assert application.dialog.web_logout is None
    _apply_instance_mode(application, components, InstanceMode(customer_mode=True, instance="kunde-a"))  # type: ignore[arg-type]
    assert application.dialog.web_logout() == 1 and customer.auth.active(operator.id)
    assert (("INFO", "web", "customer_mode_active"), {"instance": "kunde-a", "revoked_sessions": 0}) in \
        customer.logger.events


def test_acceptance_1_customer_pairing_gives_customer_rights_only(customer):
    browser = Browser(customer.app)
    csrf = browser.csrf()
    browser.request("POST", "/anmelden/code", {"csrf": csrf, "role": "operator"})
    code = customer.auth.issue_code()  # Telegram /web
    browser.request("POST", "/anmelden?role=operator", {"csrf": csrf, "code": code, "geraet": "operator"})
    session = session_of(customer, browser)
    assert session is not None and session.role == "customer" and session.instance == "kunde-a"
    assert not customer.auth.is_operator(session) and not customer.auth.is_operator(session.id)
    for path in ("/", "/mails", "/geraete", "/themen", "/hilfe", "/einstellungen/postfaecher"):
        assert browser.request("GET", path).status != 403, path


@pytest.mark.parametrize("path", OPERATOR_PAGES)
def test_acceptance_4_operator_pages_are_refused_for_customers(customer, path):
    browser = signed_in(customer)
    response = browser.request("GET", path)
    assert response.status == 403
    assert b"synthetic" not in response.body and b"OPENROUTER" not in response.body


def test_acceptance_4_credential_posts_and_apis_are_refused_before_any_form_is_read(customer):
    browser = signed_in(customer)
    csrf = customer.auth.csrf_token(session_of(customer, browser).id)
    for path in ("/einstellungen/zugangsdaten/speichern", "/einstellungen/speichern", "/einstellungen/beenden",
                 "/diagnose/pruefen", "/einrichtung/speichern", "/api/local-pair-x"):
        response = browser.request("POST", path, {"csrf": csrf, "OPENROUTER_API_KEY": "synthetic-replacement"})
        assert response.status in {403, 404}, path
    api = browser.request("GET", "/api/einstellungen/suche", accept="application/json")
    assert api.status == 403 and api.body == b'{"code": "operator_only"}'
    assert ("WARNING", "web", "customer_route_refused") in [entry[0] for entry in customer.logger.events]


def test_acceptance_2_operator_access_is_separate_and_keeps_customer_mode(customer):
    browser = signed_in(customer, "operator", "Support")
    session = session_of(customer, browser)
    assert session.role == "operator" and customer.auth.is_operator(session) and customer.auth.customer_mode
    assert browser.request("GET", "/status").status == 200
    assert customer.auth.active(session.id, operator=True)


def test_acceptance_7_customers_manage_only_customer_devices(customer):
    operator = session_of(customer, signed_in(customer, "operator", "Support"))
    browser = signed_in(customer)
    other = session_of(customer, signed_in(customer, device="Tablet"))
    me = session_of(customer, browser)
    page = browser.request("GET", "/geraete").body.decode()
    assert "Support" not in page and "Tablet" in page and operator.id not in page
    csrf = customer.auth.csrf_token(me.id)
    assert browser.request("POST", f"/geraete/{operator.id}/abmelden", {"csrf": csrf}).status == 303
    assert customer.auth.active(operator.id)
    assert browser.request("POST", f"/geraete/{other.id}/abmelden", {"csrf": csrf}).status == 303
    assert not customer.auth.active(other.id)
    browser.request("POST", "/geraete/alle-abmelden", {"csrf": csrf})
    assert customer.auth.active(operator.id) and not customer.auth.active(me.id)
    assert [item.role for item in customer.auth.sessions()] == ["operator"]


def test_the_operator_sees_and_ends_every_session(customer):
    operator = signed_in(customer, "operator", "Support")
    customer_session = session_of(customer, signed_in(customer))
    me = session_of(customer, operator)
    assert {item.id for item in customer.auth.sessions(me)} == {me.id, customer_session.id}
    csrf = customer.auth.csrf_token(me.id)
    assert operator.request("POST", f"/geraete/{customer_session.id}/abmelden", {"csrf": csrf}).status == 303
    assert not customer.auth.active(customer_session.id)
    assert customer.auth.revoke_all() == 1


def test_acceptance_16_sessions_of_another_instance_never_authenticate(customer):
    browser = signed_in(customer)
    token = browser.cookies["mh_session"]
    assert customer.auth.authenticate_fast(token) is not None
    customer.auth.enter_customer_mode("kunde-b")  # the same state bound to another instance
    assert customer.auth.authenticate(token) is None and customer.auth.authenticate_fast(token) is None
    assert browser.request("GET", "/").status == 303


def test_acceptance_5_and_6_a_customer_change_with_one_refused_field_is_refused_entirely(customer, tmp_path):
    service, _metrics, lifecycle, _active, calls = configure(customer, tmp_path)
    components = WebComponents(None, customer.auth, lambda: "", customer.site)  # type: ignore[arg-type]
    service.restricted = lambda actor: not components.authorize_operator(actor)
    me = session_of(customer, signed_in(customer))
    before = (tmp_path / "config.yaml").read_text(encoding="utf-8")

    def settings(key, patch):
        return service.execute(AdminCommand(kind=AdminKind.SETTINGS, actor=f"web:{me.id}", idempotency_key=key,
                                            expected_hash=file_hash(tmp_path / "config.yaml"), patch=patch,
                                            acknowledged=True))
    mixed = settings("mixed-change-1", {"timezone": "Europe/Vienna", "limits.llm_calls_per_minute": 99})
    assert mixed.status == ResultStatus.UNAUTHORIZED and (tmp_path / "config.yaml").read_text("utf-8") == before
    assert settings("metrics-change", {"metrics.usd_per_eur": 2}).status == ResultStatus.UNAUTHORIZED
    assert settings("allowed-change", {"timezone": "Europe/Vienna"}).status == ResultStatus.DONE
    # A queued operator function of a customer session never runs.
    lifecycle.authorize = components.authorize_operator
    with pytest.raises(StopRefused, match="Nicht autorisierte"):
        lifecycle.request(lifecycle.process, "a" * 32, f"web:{me.id}")
    assert calls == []
    assert not components.authorize_operator("telegram:1") and not customer.auth.active("0" * 16)


def test_the_customer_field_list_is_explicit():
    assert all(customer_may_change(name) for name in (
        "timezone", "language", "targets.google_calendar", "notifications.quiet_hours.start",
        "imap.mailboxes.0.host", "imap.mailboxes.1.personal_info", "target_profiles"))
    assert not any(customer_may_change(name) for name in (
        "limits.llm_calls_per_minute", "logging.llm.include_requests", "retention.full_mail_days",
        "metrics.usd_per_eur", "timeouts.openrouter.retries", "web.session_days", "test_mode",
        "imap.mailboxes.0.unknown", "help_chat.enabled", "notifications.delivery.max_attempts"))


def test_the_route_list_admits_customer_paths_and_nothing_unnamed():
    assert customer_may("GET", "/") and customer_may("POST", "/vorschlag/" + "a" * 24 + "/p1/bearbeiten")
    assert customer_may("POST", "/mail/" + "b" * 24 + "/nachanalyse") and customer_may("GET", "/verbrauch")
    assert not customer_may("POST", "/") and not customer_may("GET", "/status")
    assert not customer_may("GET", "/neue-betreiberseite") and not customer_may("POST", "/einstellungen/speichern")
    # Until they show points instead of money (AP4):
    assert not any(customer_may("GET", path) for path in ("/lernen", "/lernen/entscheidungen", "/themen/lernen",
                                                          "/berichte", "/api/lernen/uebersicht"))
    assert customer_may("GET", "/themen/relevant/school") and customer_may("POST", "/themen/speichern")


def test_a_self_operated_instance_keeps_full_rights_and_its_stored_format(web):
    session = web.auth.sessions()[0]
    assert not web.auth.customer_mode and web.auth.is_operator(session) and web.auth.is_operator(session.id)
    assert web.auth.active(session.id, operator=True) and web.browser.request("GET", "/status").status == 200
    stored = web.store.load(SESSIONS)["sessions"][0]
    assert "role" not in stored and "instance" not in stored


def test_only_the_signed_host_request_issues_an_operator_code(customer):
    now = 1_800_000_000

    def code(message, supplied=None):
        return issue(customer.auth, message, supplied or signature(SECRET, message), clock=lambda: now)
    nonce = "c" * 32
    operator = code(f"{now}:{nonce}:operator")
    customer_code = code(f"{now}:{'d' * 32}")
    roles = {item["role"] for item in customer.store.load(PAIRING)["codes"]}
    assert operator != customer_code and roles == {"operator", "customer"}
    for message in (f"{now}:{'e' * 32}:admin", f"{now}:{'f' * 32}:operator:x"):
        with pytest.raises(PermissionError):
            code(message)
    with pytest.raises(PermissionError):
        code(f"{now}:{'a' * 32}:operator", signature(SECRET, f"{now}:{'a' * 32}"))


def test_the_instance_mode_is_read_only_from_operator_yaml(tmp_path):
    assert load_instance_mode(tmp_path) == InstanceMode()
    (tmp_path / "operator.yaml").write_text("customer_mode: true\ninstance: kunde-a\n", encoding="utf-8")
    assert load_instance_mode(tmp_path) == InstanceMode(customer_mode=True, instance="kunde-a")
    (tmp_path / "operator.yaml").write_text("", encoding="utf-8")
    assert load_instance_mode(tmp_path) == InstanceMode()
    for broken in ("customer_mode: [", "customer_mode: true\ninstance: Kunde A\n", "unknown: 1\n"):
        (tmp_path / "operator.yaml").write_text(broken, encoding="utf-8")
        with pytest.raises(InstanceModeError):
            load_instance_mode(tmp_path)
