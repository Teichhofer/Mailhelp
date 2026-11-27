"""8.8.1 (Planung 8.8 AP1): a customer session connects its own targets and mailboxes through Inboxstride.

Regression: until 8.7.16 every hosted route (``/google/*``, ``/microsoft/*``, ``/notion/*``, ``/postfach/oauth*``,
``/auth/status/<id>``) answered 403 for customers and the flows ended on the operator setup. A mailbox activation
(sign-in or password) used a copy of the configuration service without the customer's field limits, so a customer
could change operator fields of a mailbox; the limits are now checked before ``.env`` is written. Synthetic data only.
"""
from __future__ import annotations

import re
from types import SimpleNamespace as NS

import pytest
import yaml

from mailhelp.app import mailbox_accounts as module
from mailhelp.config import Secrets, Settings
from mailhelp.web.factory import WebComponents
from mailhelp.web.hosted_google_site import HostedGoogleSite, HostedProfiles
from mailhelp.web.hosted_targets_site import HostedTargetContext, HostedTargetsSite
from mailhelp.web.mailbox_oauth_site import BASE, RETURN, MailboxOAuthContext, MailboxOAuthSite
from mailhelp.web.permissions import customer_may
from tests.fakes.customer_mode import signed_in
from tests.fakes.hosted_web import Profiles, central, connect, fields  # noqa: F401
from tests.fakes.shared_web_actions import web  # noqa: F401  (fixture)

TARGETS = "/einstellungen/zielprofile"


@pytest.fixture
def hosted(web, central):
    profiles = Profiles()
    client = central.client("anna")
    HostedGoogleSite(web.site, web.store, lambda: client, HostedProfiles(profiles.draft, profiles.save, profiles.target),
                     "/einrichtung", transport=central.transport("anna"))
    web.auth.enter_customer_mode("kunde-a")
    web.browser = signed_in(web)
    web.profiles, web.central = profiles, central
    yield web
    client.close()


def test_regression_a_customer_connects_google_and_lands_on_own_target_profiles(hosted):
    web = hosted
    assert web.browser.request("GET", "/google/verbinden?profile=1").status == 200  # 403 until 8.7.16
    returned = connect(web)
    redeemed = web.browser.request("POST", "/einrichtung/google/abschluss",
                                   fields(returned.body.decode(), "/einrichtung/google/abschluss"))
    assert redeemed.headers["Location"] == "/google/kalender"
    choose = web.browser.request("GET", "/google/kalender").body.decode()
    adopted = web.browser.request("POST", "/google/kalender",
                                  {**fields(choose, "/google/kalender"), "calendar": "familie@group.calendar.google.com"})
    assert adopted.status == 303 and adopted.headers["Location"] == TARGETS and customer_may("GET", TARGETS)
    assert web.profiles.saved[0][0].startswith("web:") and web.profiles.saved[0][1] == 1  # a draft, nothing written
    other = web.browser.request("GET", "/google/kalender/wechseln?profile=1").body.decode()
    changed = web.browser.request("POST", "/google/kalender/wechseln", {**fields(other, "/google/kalender/wechseln"),
                                                                        "calendar": "familie@group.calendar.google.com"})
    assert changed.headers["Location"] == TARGETS
    offer = web.browser.request("GET", "/google/verbinden?profile=1").body.decode()
    ended = web.browser.request("POST", "/google/trennen", fields(offer, "/google/trennen"))
    assert ended.status == 303 and ended.headers["Location"] == TARGETS


def test_the_operator_still_continues_in_the_setup(hosted):
    web = hosted
    operator = web.auth.authenticate(signed_in(web, "operator", "Support").cookies["mh_session"])
    customer = web.auth.authenticate(web.browser.cookies["mh_session"])
    assert web.site.setup_return(operator, "/einrichtung") == "/einrichtung"
    assert web.site.setup_return(customer, "/einrichtung") == TARGETS


def test_microsoft_and_notion_steps_reach_their_handlers_and_return_to_target_profiles(web):
    saved = []
    context = HostedTargetContext(lambda profile, field: ("c" * 32 if field.endswith("connection") else "", 3),
                                  lambda *args: saved.append(args), lambda profile: f"profile:{profile}")
    client = NS(post=lambda path, body: saved.append((path, body)) or {"providers": ["microsoft_targets", "notion"]})
    HostedTargetsSite(web.site, web.store, lambda: client, context, "/einrichtung")  # type: ignore[arg-type]
    web.auth.enter_customer_mode("kunde-a")
    web.browser = signed_in(web)
    csrf = web.auth.csrf_token(web.auth.authenticate(web.browser.cookies["mh_session"]).id)
    for provider in ("microsoft", "notion"):
        assert web.browser.request("GET", f"/{provider}/verbinden?profile=1").status == 200
        assert web.browser.request("GET", f"/{provider}/ziele").status != 403
        assert web.browser.request("POST", f"/{provider}/ziele", {"csrf": csrf}).status != 403
        assert web.browser.request("POST", f"/einrichtung/{provider}/abschluss", {"csrf": csrf}).status != 403
        ended = web.browser.request("POST", f"/{provider}/trennen",
                                    {"csrf": csrf, "profile": "1", "version": "3", "key": "k" * 32})
        assert ended.status == 303 and ended.headers["Location"] == TARGETS
    assert [entry[0] for entry in saved if entry[0] == "/intern/disconnect"] == ["/intern/disconnect"] * 2


def test_mailbox_sign_in_routes_are_open_to_customers(web, central):
    calls = []
    context = MailboxOAuthContext(lambda number: (_ for _ in ()).throw(ValueError("none")),
                                  lambda *args: calls.append(args), lambda *args: [])
    MailboxOAuthSite(web.site, web.store, lambda: None, context, "/einstellungen/postfaecher")
    web.auth.enter_customer_mode("kunde-a")
    web.browser = signed_in(web)
    csrf = web.auth.csrf_token(web.auth.authenticate(web.browser.cookies["mh_session"]).id)
    for method, path in (("GET", BASE + "?provider=gmail&mailbox=1"), ("POST", BASE), ("GET", BASE + "/ordner"),
                         ("POST", BASE + "/ordner"), ("POST", BASE + "/trennen"), ("POST", RETURN)):
        response = web.browser.request(method, path.split("?")[0] if method == "POST" else path, {"csrf": csrf})
        assert response.status != 403, path  # the handler decides; nothing was configured here
    assert web.browser.request("GET", "/auth/status/" + "a" * 64).status != 403
    assert calls == []


def test_every_registered_sign_in_route_is_a_customer_route(web, central):
    HostedGoogleSite(web.site, web.store, lambda: None, HostedProfiles(*(lambda *a: None,) * 3), "/einrichtung")
    HostedTargetsSite(web.site, web.store, lambda: None, HostedTargetContext(*(lambda *a: None,) * 3), "/einrichtung")
    MailboxOAuthSite(web.site, web.store, lambda: None, MailboxOAuthContext(*(lambda *a: None,) * 3), "/x")
    signed = re.compile(r"/(?:google|microsoft|notion|postfach)/|/auth/status/|/einrichtung/(?:\w+)/abschluss")
    sample = {r"(?P<identity>[a-f0-9]{64})": "a" * 64}
    found = 0
    for method, pattern, _handler in web.app._routes:
        path = pattern.pattern
        for regex, value in sample.items():
            path = path.replace(regex, value)
        if signed.match(path) and not (method == "GET" and path.endswith("/abschluss")):  # public returns
            found += 1
            assert customer_may(method, path), (method, path)
    assert found >= 20
    for refused in ("/einrichtung", "/einrichtung/speichern", "/einrichtung/start", "/einrichtung/postfach/x",
                    "/google/x", "/postfach/oauth/x", "/auth/status/" + "a" * 63):
        assert not customer_may("POST", refused) and not customer_may("GET", refused), refused


@pytest.fixture
def running(profiled, monkeypatch):
    """The running mailbox sign-in with the real configuration transaction, in a customer session."""
    from tests.fakes.hosted_google import settings as hosted_settings
    from tests.fakes.shared_decision_test import secrets

    ctx = profiled
    cfg = ctx.cfg.model_copy(update={"hosted_auth": hosted_settings()})
    ctx.app.settings = ctx.app.configuration.active = cfg
    (ctx.tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
    ctx.runtime.secrets = Secrets.model_validate(secrets().model_dump())
    ctx.activated = []
    ctx.app.mailbox_runtime = NS(request=lambda cfg, keys: ctx.activated.append(cfg))
    monkeypatch.setattr(module.ReconnectActivation, "probe", lambda self, cfg, box, keys: None)
    captured = {}
    monkeypatch.setattr(module, "MailboxOAuthSite", lambda site, store, client, context, back: captured.update(
        context=context))
    module.attach_running_mailbox(ctx.app, ctx.web.site, lambda: cfg)
    web = ctx.web
    web.auth.enter_customer_mode("kunde-a")
    web.browser = signed_in(web)
    components = WebComponents(None, web.auth, lambda: "", web.site)  # type: ignore[arg-type]
    ctx.app.configuration.restricted = lambda actor: not components.authorize_operator(actor)
    ctx.context = captured["context"]
    ctx.actor = "web:" + web.auth.authenticate(web.browser.cookies["mh_session"]).id
    ctx.env = ctx.tmp_path / ".env"
    return ctx


def test_a_customer_signs_in_an_own_mailbox_through_inboxstride(running):
    box, version, revision = running.context.read(1)
    candidate = box.model_copy(update={"host": "imap.gmail.com", "auth_method": "gmail", "oauth_connection": "c" * 32})
    running.context.save(running.actor, candidate, "synthetic@example.test", version, "oauth-save-0001", revision)
    saved = Settings.model_validate(yaml.safe_load((running.tmp_path / "config.yaml").read_text(encoding="utf-8")))
    assert saved.imap.mailbox(1).oauth_connection == "c" * 32 and len(running.activated) == 1
    assert "IMAP_1_USERNAME=" in running.env.read_text(encoding="utf-8")


def test_regression_an_activation_keeps_the_customer_field_limits_before_writing_credentials(running):
    before = running.env.read_text(encoding="utf-8") if running.env.exists() else None
    box, version, revision = running.context.read(1)
    candidate = box.model_copy(update={"host": "imap.gmail.com", "auth_method": "gmail", "oauth_connection": "c" * 32,
                                       "own_addresses": ["fremd@example.test"]})  # an operator field
    with pytest.raises(PermissionError):
        running.context.save(running.actor, candidate, "synthetic@example.test", version, "oauth-save-0002", revision)
    after = running.env.read_text(encoding="utf-8") if running.env.exists() else None
    assert after == before and running.activated == []
