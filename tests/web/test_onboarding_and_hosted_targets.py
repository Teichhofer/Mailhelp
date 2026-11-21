"""8.2: tests for central Microsoft/Notion target OAuths and guided 3-step self-service onboarding."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx
import pytest
import yaml
from pydantic import SecretStr, ValidationError

from inboxstride_auth import __main__ as auth_cli
from inboxstride_auth.ca import create_ca, fingerprint, issue
from inboxstride_auth.google import Client, TokenAnswer
from inboxstride_auth.http_api import public
from inboxstride_auth.microsoft import MicrosoftTokens
from inboxstride_auth.models import MAIL_SCOPES
from inboxstride_auth.notion import CALLBACK as NOTION_CALLBACK
from inboxstride_auth.notion import NotionTokens
from inboxstride_auth.secret_store import SecretStore, create_key
from inboxstride_auth.service import AuthService, Refused
from inboxstride_auth.state_file import StateFile
from mailhelp.app import bootstrap, browser_accounts
from mailhelp.config import Settings, TargetProfileSettings, TargetSettings, WebSettings
from mailhelp.config.loader import provider_secret_names
from mailhelp.external.hosted_oauth import HostedAuthClient, HostedRefused, HostedTokenProvider, HostedUnavailable
from mailhelp.external.providers import build_writers
from mailhelp.logging import NullLogger
from mailhelp.runtime.onboarding import (
    STARTER_PRESETS,
    DryRunPreview,
    OnboardingService,
    OnboardingState,
    starter_topics,
)
from mailhelp.support.connection_health import ConnectionProblem
from mailhelp.web.connection_warnings import connection_warnings
from mailhelp.web.hosted_targets_site import PENDING, HostedTargetContext, HostedTargetsSite
from mailhelp.web.initial_pages import hosted_target_boxes, initial_page
from mailhelp.web.onboarding_site import OnboardingSite
from tests.fakes.hosted_google import Central
from tests.fakes.hosted_google import settings as hosted_settings
from tests.fakes.hosted_web import fields
from tests.fakes.initial_harness import InitialHarness
from tests.fakes.shared_web_actions import web as web  # noqa: F401


def test_notion_tokens_and_central_target_purposes(tmp_path):
    with pytest.raises(ValueError, match="Invalid Notion callback"):
        NotionTokens(Client("id", "sec", "http://evil.example/auth/notion/callback"))

    def responder(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://api.notion.com/v1/oauth/token")
        return httpx.Response(200, json={
            "access_token": "ntn_access", "token_type": "bearer", "expires_in": 3600,
            "refresh_token": "ntn_refresh", "scope": "notion"})

    tokens = NotionTokens(Client("nid", "nsec", NOTION_CALLBACK), transport=httpx.MockTransport(responder))
    url = tokens.authorize("st", "ch", ("notion",))
    assert url.startswith("https://api.notion.com/v1/oauth/authorize?") and "owner=user" in url
    answer = tokens.exchange("code1", "ver1")
    assert answer.access_token == "ntn_access" and answer.scope == "notion"
    tokens.close()

    ms = MicrosoftTokens(
        Client("mid", "msec", "https://auth.inboxstride.de/auth/microsoft/callback"),
        scopes=MAIL_SCOPES["microsoft_targets"],
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json={
            "access_token": "ms_acc", "token_type": "Bearer", "expires_in": 3600,
            "refresh_token": "ms_ref",
            "scope": " ".join((*MAIL_SCOPES["microsoft_targets"], "offline_access"))})))
    assert "Calendars.ReadWrite" in ms.authorize("st", "ch", MAIL_SCOPES["microsoft_targets"])
    assert "Calendars.ReadWrite" in ms.exchange("c", "v").scope
    ms.close()


def _central(tmp_path) -> Central:
    folder = tmp_path / "central"
    folder.mkdir(exist_ok=True)
    central = Central(folder)
    central.service.mail_providers["microsoft_targets"] = MicrosoftTokens(
        Client("mid", "synthetic-client-secret", "https://auth.inboxstride.de/auth/microsoft/callback"),
        scopes=MAIL_SCOPES["microsoft_targets"],
        transport=httpx.MockTransport(central.google),
    )
    central.service.mail_providers["notion"] = NotionTokens(
        Client("nid", "synthetic-client-secret", NOTION_CALLBACK),
        transport=httpx.MockTransport(central.google),
    )
    return central


def test_central_auth_coexistence_and_cli_notion_client(tmp_path):
    state_dir = tmp_path / "state"
    key_file = tmp_path / "auth.key"
    create_key(key_file)
    ca_dir = tmp_path / "ca"
    create_ca(ca_dir)
    cert_dir = tmp_path / "certs"
    issue(ca_dir, cert_dir, "anna", server=False)
    env = {"INBOXSTRIDE_AUTH_STATE": str(state_dir), "INBOXSTRIDE_AUTH_KEY": str(key_file),
           "INBOXSTRIDE_AUTH_MICROSOFT_TARGETS_ENABLED": "1"}

    google_file = tmp_path / "google.json"
    google_file.write_text(json.dumps({"web": {"client_id": "gid", "client_secret": "gsec"}}), encoding="utf-8")
    ms_file = tmp_path / "ms.json"
    ms_file.write_text(json.dumps({"client_id": "mid", "client_secret": "msec", "tenant": "common"}), encoding="utf-8")
    notion_file = tmp_path / "notion.json"
    notion_file.write_text(json.dumps({"client_id": "nid", "client_secret": "nsec"}), encoding="utf-8")

    with pytest.raises(ValueError, match="Missing Notion client"):
        auth_cli.set_notion_client(env, tmp_path / "google.json")

    assert auth_cli.main(["set-client", str(google_file)], env) == 0
    assert auth_cli.main(["set-mail-client", str(ms_file)], env) == 0
    assert auth_cli.main(["set-notion-client", str(notion_file)], env) == 0
    assert auth_cli.main(["register", "anna", "anna.inboxstride.example", str(cert_dir / "anna.pem")], env) == 0

    service = auth_cli.build(env)
    assert set(service.mail_providers) == {"microsoft", "microsoft_targets", "notion"}

    # Verify Notion public callback routing and slot coexistence (calendar + notion on profile:1)
    central = _central(tmp_path)

    job_cal, url_cal = central.service.start("anna", "sess1", "profile:1", "connect", "k_cal", "calendar")
    back_cal = central.google_return(url_cal)
    receipt_cal = back_cal.split("beleg=")[1]
    redeemed_cal = central.service.redeem("anna", "sess1", receipt_cal)
    conn_cal = central.service.activate("anna", "sess1", job_cal.id, redeemed_cal.version)

    job_ntn, url_ntn = central.service.start("anna", "sess1", "profile:1", "connect", "k_ntn", "notion")
    state_param = dict(part.split("=") for part in urlsplit(url_ntn).query.split("&"))["state"]
    ans = public(central.service, "GET", f"/auth/notion/callback?state={state_param}&code=good", lambda *a: None)
    assert ans.status == 303 and "/einrichtung/notion/abschluss?beleg=" in ans.headers["Location"]
    receipt_ntn = ans.headers["Location"].split("beleg=")[1]
    redeemed_ntn = central.service.redeem("anna", "sess1", receipt_ntn)
    conn_ntn = central.service.activate("anna", "sess1", job_ntn.id, redeemed_ntn.version)

    # Both calendar and notion remain active on profile:1!
    connections = central.service.state.read().connections
    assert connections[conn_cal.id].status == "active"
    assert connections[conn_ntn.id].status == "active"

    # Replacing notion on profile:1 disconnects old notion but keeps calendar active
    job_ntn2, url_ntn2 = central.service.start("anna", "sess1", "profile:1", "reauthorize", "k_ntn2", "notion")
    st2 = dict(part.split("=") for part in urlsplit(url_ntn2).query.split("&"))["state"]
    ans2 = public(central.service, "GET", f"/auth/notion/callback?state={st2}&code=second", lambda *a: None)
    rec2 = ans2.headers["Location"].split("beleg=")[1]
    red2 = central.service.redeem("anna", "sess1", rec2)
    conn_ntn2 = central.service.activate("anna", "sess1", job_ntn2.id, red2.version)
    connections = central.service.state.read().connections
    assert connections[conn_cal.id].status == "active"
    assert connections[conn_ntn.id].status == "disconnected"
    assert connections[conn_ntn2.id].status == "active"


class TargetProfilesDouble:
    def __init__(self):
        self.data = {1: {"microsoft_connection": "", "notion_connection": ""},
                     2: {"microsoft_connection": "", "notion_connection": ""}}
        self.version = 1
        self.saved = []

    def read(self, profile: int, field_name: str) -> tuple[str, int]:
        if profile not in self.data:
            raise LookupError(profile)
        return self.data[profile].get(field_name, ""), self.version

    def save(self, actor: str, profile: int, values: dict, version: int, key: str) -> None:
        if version != self.version or not key:
            raise ValueError("stale")
        self.saved.append((actor, profile, values, version))
        self.data[profile].update(values)
        self.version += 1

    def target(self, profile: int) -> str:
        if profile not in self.data:
            raise LookupError(profile)
        return f"profile:{profile}"


def _notion_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "results": [{"id": "a" * 32, "title": [{"plain_text": "Aufgaben 2026"}]}],
            "has_more": False, "next_cursor": None})
    return httpx.MockTransport(handler)


def test_hosted_targets_site_microsoft_and_notion_flows(web, tmp_path):
    central = _central(tmp_path)
    profiles = TargetProfilesDouble()
    client = central.client("anna")
    state = {"client": client}
    site = HostedTargetsSite(
        web.site, web.store, lambda: state["client"],
        HostedTargetContext(profiles.read, profiles.save, profiles.target),
        "/einrichtung", transport=_notion_transport(),
    )

    # 1. Microsoft full flow
    offer_ms = web.browser.request("GET", "/microsoft/verbinden?profile=1")
    assert offer_ms.status == 200 and "https://login.microsoftonline.com" in offer_ms.headers["Content-Security-Policy"]
    start_ms = web.browser.request("POST", "/microsoft/verbinden", fields(offer_ms.body.decode(), "/microsoft/verbinden"))
    assert start_ms.status == 303 and "login.microsoftonline.com" in start_ms.headers["Location"]
    st = dict(part.split("=") for part in urlsplit(start_ms.headers["Location"]).query.split("&"))["state"]
    cb = public(central.service, "GET", f"/auth/microsoft/callback?state={st}&code=good", lambda *a: None)
    assert cb.status == 303
    parts = urlsplit(cb.headers["Location"])
    ret_page = web.browser.request("GET", f"{parts.path}?{parts.query}")
    assert ret_page.status == 200 and "/microsoft/ziele?beleg=" in ret_page.body.decode()
    receipt = parts.query.split("beleg=")[1]
    confirm_page = web.browser.request("GET", f"/microsoft/ziele?beleg={receipt}")
    assert confirm_page.status == 200
    redeemed = web.browser.request("POST", "/einrichtung/microsoft/abschluss",
                                   fields(confirm_page.body.decode(), "/einrichtung/microsoft/abschluss"))
    assert redeemed.status == 303 and redeemed.headers["Location"] == "/microsoft/ziele"
    targets_page = web.browser.request("GET", "/microsoft/ziele")
    assert targets_page.status == 200 and "outlook_calendar" in targets_page.body.decode()

    # Invalid target ID rejected
    bad_form = {**fields(targets_page.body.decode(), "/microsoft/ziele"), "outlook_calendar": "bad id!"}
    assert web.browser.request("POST", "/microsoft/ziele", bad_form).status == 409

    good_form = {**fields(targets_page.body.decode(), "/microsoft/ziele"),
                 "outlook_calendar": "cal1", "microsoft_todo_list": "todo1"}
    adopted = web.browser.request("POST", "/microsoft/ziele", good_form)
    assert adopted.status == 303 and adopted.headers["Location"] == "/einrichtung"
    ms_conn = profiles.data[1]["microsoft_connection"]
    assert len(ms_conn) == 32 and profiles.data[1]["outlook_calendar"] == "cal1"

    # Offer now shows disconnect button; disconnect works
    offer_ms2 = web.browser.request("GET", "/microsoft/verbinden?profile=1")
    assert "/microsoft/trennen" in offer_ms2.body.decode()
    disc = web.browser.request("POST", "/microsoft/trennen", fields(offer_ms2.body.decode(), "/microsoft/trennen"))
    assert disc.status == 303

    # 2. Notion full flow
    offer_ntn = web.browser.request("GET", "/notion/verbinden?profile=1")
    assert offer_ntn.status == 200 and "https://api.notion.com" in offer_ntn.headers["Content-Security-Policy"]
    start_ntn = web.browser.request("POST", "/notion/verbinden", fields(offer_ntn.body.decode(), "/notion/verbinden"))
    assert start_ntn.status == 303
    st_n = dict(part.split("=") for part in urlsplit(start_ntn.headers["Location"]).query.split("&"))["state"]
    cb_n = public(central.service, "GET", f"/auth/notion/callback?state={st_n}&code=good", lambda *a: None)
    parts_n = urlsplit(cb_n.headers["Location"])
    receipt_n = parts_n.query.split("beleg=")[1]
    confirm_n = web.browser.request("GET", f"/notion/ziele?beleg={receipt_n}")
    web.browser.request("POST", "/einrichtung/notion/abschluss",
                        fields(confirm_n.body.decode(), "/einrichtung/notion/abschluss"))
    targets_n = web.browser.request("GET", "/notion/ziele")
    assert targets_n.status == 200 and "Aufgaben 2026" in targets_n.body.decode()

    # Unknown Notion source rejected
    bad_n = {**fields(targets_n.body.decode(), "/notion/ziele"), "source": "b" * 32}
    assert web.browser.request("POST", "/notion/ziele", bad_n).status == 409

    good_n = {**fields(targets_n.body.decode(), "/notion/ziele"), "source": "a" * 32}
    adopted_n = web.browser.request("POST", "/notion/ziele", good_n)
    assert adopted_n.status == 303 and adopted_n.headers["Location"] == "/notion/zuordnung?profile=1"
    assert len(profiles.data[1]["notion_connection"]) == 32

    # Navigation=False redirects Notion to setup_path
    site.navigation = False
    client.close()


def test_hosted_targets_site_error_and_edge_branches(web, tmp_path, monkeypatch):
    central = _central(tmp_path)
    del central.service.mail_providers["notion"]
    profiles = TargetProfilesDouble()
    client = central.client("anna")
    state: dict = {"client": client}
    site = HostedTargetsSite(
        web.site, web.store, lambda: state["client"],
        HostedTargetContext(profiles.read, profiles.save, profiles.target),
        "/einrichtung", transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json={"results": [], "has_more": False, "next_cursor": None})),
    )

    # Profile validation & unknown profile
    assert web.browser.request("GET", "/microsoft/verbinden?profile=0").status == 404
    assert web.browser.request("GET", "/microsoft/verbinden?profile=9").status == 404

    # Provider not configured (notion not registered in central) & client is None
    assert web.browser.request("GET", "/notion/verbinden?profile=1").status == 503
    state["client"] = None
    assert web.browser.request("GET", "/microsoft/verbinden?profile=1").status == 503
    state["client"] = client

    # Cancelled return
    assert web.browser.request("GET", "/einrichtung/microsoft/abschluss?abbruch=1").status == 409

    # Targets without pending record
    assert web.browser.request("GET", "/microsoft/ziele").status == 409

    # Start with invalid redirect URL or unavailable service
    session = web.auth.authenticate(web.browser.cookies["mh_session"])
    from mailhelp.web.hosted_google_site import session_reference
    ref = session_reference(session)
    slot = f"microsoft:{ref}"
    csrf = web.auth.csrf_token(session.id)
    state["client"] = SimpleNamespace(post=lambda path, data: {"providers": ["microsoft_targets"],
                                                               "url": "https://evil.example/x"})
    assert web.browser.request("POST", "/microsoft/verbinden",
                               {"csrf": csrf, "profile": "1", "key": "k" * 32}).status == 409

    def fail_unavailable(path, data):
        raise HostedUnavailable("down")

    web.store.save(PENDING, {slot: {
        "job": "j1", "profile": 1, "version": 1, "provider": "microsoft", "purpose": "microsoft_targets",
        "expires": (datetime.now(UTC) + timedelta(minutes=5)).isoformat()}})
    state["client"] = SimpleNamespace(post=fail_unavailable)
    assert web.browser.request("POST", "/microsoft/verbinden",
                               {"csrf": csrf, "profile": "1", "key": "k" * 32}).status == 503
    assert web.browser.request("POST", "/einrichtung/microsoft/abschluss",
                               {"csrf": csrf, "receipt": "r" * 24, "key": "k" * 32}).status == 503
    assert web.browser.request("POST", "/microsoft/trennen",
                               {"csrf": csrf, "profile": "1", "version": "1", "key": "k" * 32}).status == 503
    assert web.browser.request("POST", "/microsoft/ziele",
                               {"csrf": csrf, "key": "k" * 32}).status == 409

    # Disconnect invalid version
    state["client"] = client
    assert web.browser.request("POST", "/microsoft/trennen",
                               {"csrf": csrf, "profile": "1", "version": "1", "key": "k" * 32}).status == 409

    # Expired pending, version changed, missing candidate, missing token, no sources, activation retry
    web.store.save(PENDING, {slot: {
        "job": "j1", "profile": 1, "version": 1, "provider": "microsoft", "purpose": "microsoft_targets",
        "expires": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()}})
    assert web.browser.request("GET", "/microsoft/ziele").status == 409

    web.store.save(PENDING, {slot: {
        "job": "j1", "profile": 1, "version": 99, "provider": "microsoft", "purpose": "microsoft_targets",
        "expires": (datetime.now(UTC) + timedelta(minutes=5)).isoformat()}})
    assert web.browser.request("GET", "/microsoft/ziele").status == 409

    # Missing candidate connection
    web.store.save(PENDING, {slot: {
        "job": "j1", "profile": 1, "version": 1, "provider": "microsoft", "purpose": "microsoft_targets",
        "expires": (datetime.now(UTC) + timedelta(minutes=5)).isoformat()}})
    assert web.browser.request("GET", "/microsoft/ziele").status == 409

    # Wrong binding on redeem
    state["client"] = SimpleNamespace(post=lambda path, data: {
        "providers": ["microsoft_targets"], "job": "other", "target": "profile:1", "purpose": "microsoft_targets"})
    assert web.browser.request("POST", "/einrichtung/microsoft/abschluss",
                               {"csrf": csrf, "receipt": "r" * 24, "key": "k" * 32}).status == 409

    # Missing access_token from /intern/token
    web.store.save(PENDING, {slot: {
        "job": "j1", "profile": 1, "version": 1, "provider": "microsoft", "purpose": "microsoft_targets",
        "connection": "c" * 32, "job_version": 2,
        "expires": (datetime.now(UTC) + timedelta(minutes=5)).isoformat()}})
    state["client"] = SimpleNamespace(post=lambda path, data: {
        "providers": ["microsoft_targets"], "access_token": ""})
    assert web.browser.request("GET", "/microsoft/ziele").status == 409

    # HostedUnavailable during targets GET
    def fail_on_token(path, data):
        if path == "/intern/token":
            raise HostedUnavailable("down")
        return {"providers": ["microsoft_targets"]}

    state["client"] = SimpleNamespace(post=fail_on_token)
    assert web.browser.request("GET", "/microsoft/ziele").status == 503

    # Notion empty sources
    central.service.mail_providers["notion"] = central.google
    slot_n = f"notion:{ref}"
    web.store.save(PENDING, {slot_n: {
        "job": "j2", "profile": 1, "version": 1, "provider": "notion", "purpose": "notion",
        "connection": "c" * 32, "job_version": 2,
        "expires": (datetime.now(UTC) + timedelta(minutes=5)).isoformat()}})
    state["client"] = SimpleNamespace(post=lambda path, data: {
        "providers": ["notion"], "access_token": "tok"})
    assert web.browser.request("GET", "/notion/ziele").status == 409

    # Adopt edge cases: adopting changed, session expired, activation mismatch, outage on activate
    web.store.save(PENDING, {slot: {
        "job": "j1", "profile": 1, "version": 1, "provider": "microsoft", "purpose": "microsoft_targets",
        "connection": "c" * 32, "job_version": 2, "adopting": {"other": 1},
        "expires": (datetime.now(UTC) + timedelta(minutes=5)).isoformat()}})
    state["client"] = SimpleNamespace(post=lambda path, data: {
        "providers": ["microsoft_targets"], "access_token": "tok", "connection": "c" * 32})
    form_adopt = {"csrf": csrf, "key": "k" * 32, "outlook_calendar": "cal1", "microsoft_todo_list": "todo1"}
    assert web.browser.request("POST", "/microsoft/ziele", form_adopt).status == 409

    # Outage on activate after local save, then retry with saved=True, activation mismatch, then success
    web.store.save(PENDING, {slot: {
        "job": "j1", "profile": 1, "version": 1, "provider": "microsoft", "purpose": "microsoft_targets",
        "connection": "c" * 32, "job_version": 2,
        "expires": (datetime.now(UTC) + timedelta(minutes=5)).isoformat()}})

    def down_activate(path, data):
        if path == "/intern/activate":
            raise HostedUnavailable("down")
        return {"providers": ["microsoft_targets"], "access_token": "tok"}

    state["client"] = SimpleNamespace(post=down_activate)
    assert web.browser.request("POST", "/microsoft/ziele", form_adopt).status == 503
    assert profiles.data[1]["microsoft_connection"] == "c" * 32

    # Activation mismatch
    state["client"] = SimpleNamespace(post=lambda path, data: {
        "providers": ["microsoft_targets"], "access_token": "tok", "connection": "d" * 32})
    assert web.browser.request("POST", "/microsoft/ziele", form_adopt).status == 409

    # Session expired right before activate
    monkeypatch.setattr(web.site.auth, "active", lambda _sid: False)
    assert web.browser.request("POST", "/microsoft/ziele", form_adopt).status == 409
    monkeypatch.undo()

    # Retry succeeds without double save; Notion navigation=False redirect
    site.navigation = False
    web.store.save(PENDING, {slot_n: {
        "job": "j2", "profile": 1, "version": profiles.version, "provider": "notion", "purpose": "notion",
        "connection": "c" * 32, "job_version": 2, "saved": True,
        "adopting": {"notion_connection": "c" * 32, "notion_data_source_id": "a" * 32},
        "expires": (datetime.now(UTC) + timedelta(minutes=5)).isoformat()}})
    site.transport = _notion_transport()
    state["client"] = SimpleNamespace(post=lambda path, data: {
        "providers": ["notion"], "access_token": "tok", "connection": "c" * 32})
    res = web.browser.request("POST", "/notion/ziele", {"csrf": csrf, "key": "k" * 32, "source": "a" * 32})
    assert res.status == 303 and res.headers["Location"] == "/einrichtung"
    client.close()


def test_onboarding_service_and_web_flow(web, tmp_path):
    authorized = {"ok": True}
    service = OnboardingService(
        tmp_path, web.store, lambda actor: authorized["ok"] and actor.startswith("web:"),
        lambda value: "sig:" + value,
    )
    OnboardingSite(web.site, service, "/einrichtung")

    # Initial GET /onboarding
    page1 = web.browser.request("GET", "/onboarding")
    assert page1.status == 200 and "Schritt 1: Postfach verbinden" in page1.body.decode()

    # Step 2 before Step 1 is rejected
    f_target = fields(page1.body.decode(), "/onboarding/ziel")
    assert web.browser.request("POST", "/onboarding/ziel", f_target).status == 409

    # Dry run before Step 1 & 2 is rejected
    f_dry = fields(page1.body.decode(), "/onboarding/probelauf")
    assert web.browser.request("POST", "/onboarding/probelauf", {**f_dry, "preset_family": "1"}).status == 409

    # Activate before dry run is rejected
    f_act = fields(page1.body.decode(), "/onboarding/aktivieren")
    assert web.browser.request("POST", "/onboarding/aktivieren", {**f_act, "confirm": "yes"}).status == 409
    assert web.browser.request("POST", "/onboarding/aktivieren", {**f_act, "confirm": "no"}).status == 409

    # Step 1: Mailbox check with provider detection (web.de) & stale version rejection
    actor = "web:" + web.auth.authenticate(web.browser.cookies["mh_session"]).id
    f_mb = {**fields(page1.body.decode(), "/onboarding/postfach"), "email": "anna@web.de"}
    assert web.browser.request("POST", "/onboarding/postfach", {**f_mb, "version": "99"}).status == 409
    res1 = web.browser.request("POST", "/onboarding/postfach", f_mb)
    assert res1.status == 200 and "WEB.DE" in res1.body.decode() and "Postfach geprüft" in res1.body.decode()
    # Idempotent replay of same key
    assert service.record_mailbox(actor, 1, f_mb["key"], f_mb).version == 2
    with pytest.raises(ValueError, match="Idempotenzkonflikt"):
        service.record_mailbox(actor, 1, f_mb["key"], {"email": "other@web.de"})
    with pytest.raises(ValueError, match="Versionskonflikt"):
        service.record_mailbox(actor, 1, "new_key_" + "a" * 24, f_mb)
    with pytest.raises(ValueError, match="Ungültiger Idempotenzschlüssel"):
        service.record_mailbox(actor, 2, "short", f_mb)

    # Repeat Step 1 when status is already step_target
    f_mb2 = {**fields(res1.body.decode(), "/onboarding/postfach"), "email": "anna@unknown.example"}
    res1b = web.browser.request("POST", "/onboarding/postfach", f_mb2)
    assert res1b.status == 200

    # Step 2: Target check
    f_tg = fields(res1b.body.decode(), "/onboarding/ziel")
    res2 = web.browser.request("POST", "/onboarding/ziel", f_tg)
    assert res2.status == 200 and "Zielsystem geprüft" in res2.body.decode()
    assert service.record_target(actor, 3, f_tg["key"], f_tg).version == 4
    # Repeat Step 2 when status is already step_topics_dryrun
    f_tg2 = fields(res2.body.decode(), "/onboarding/ziel")
    res2b = web.browser.request("POST", "/onboarding/ziel", f_tg2)
    assert res2b.status == 200

    # Step 3: Dry run without presets fails, with presets succeeds
    f_dr_empty = {k: v for k, v in fields(res2b.body.decode(), "/onboarding/probelauf").items()
                  if not k.startswith("preset_")}
    assert web.browser.request("POST", "/onboarding/probelauf", f_dr_empty).status == 409

    f_dr = {**f_dr_empty, "preset_family": "1", "preset_club": "1"}
    res3 = web.browser.request("POST", "/onboarding/probelauf", f_dr)
    assert res3.status == 200 and "Testmodus-Vorschau" in res3.body.decode()
    assert service.run_dryrun(actor, 5, f_dr["key"], ["family", "club"]).version == 6

    # Step 3: Activate writes topics.yaml and redirects
    f_act2 = {**fields(res3.body.decode(), "/onboarding/aktivieren"), "confirm": "yes"}
    res4 = web.browser.request("POST", "/onboarding/aktivieren", f_act2)
    assert res4.status == 303 and res4.headers["Location"] == "/"
    assert (tmp_path / "topics.yaml").is_file()
    assert service.activate(actor, 6, f_act2["key"], "yes").status == "completed"

    # Skip flow & idempotent skip
    page_after = web.browser.request("GET", "/onboarding")
    f_skip = fields(page_after.body.decode(), "/onboarding/ueberspringen")
    res_skip = web.browser.request("POST", "/onboarding/ueberspringen", f_skip)
    assert res_skip.status == 303 and res_skip.headers["Location"] == "/einrichtung"
    assert service.skip(actor, 7, f_skip["key"]).status == "skipped"
    # Stale skip fails with 409
    assert web.browser.request("POST", "/onboarding/ueberspringen",
                               {**f_skip, "key": "k" * 32, "version": "1"}).status == 409

    # Empty probe summary & unauthorized actor branches
    bad_service = OnboardingService(
        tmp_path, web.store, lambda actor: authorized["ok"], lambda value: value,
        probe_mailbox=lambda _f: "   ", probe_target=lambda _f: "   ",
    )
    with pytest.raises(ValueError, match="ohne Ergebnis"):
        bad_service.record_mailbox("web:s1", bad_service.state().version, "m" * 32, {})
    with pytest.raises(ValueError, match="ohne Ergebnis"):
        bad_service.record_target("web:s1", bad_service.state().version, "t" * 32, {})

    authorized["ok"] = False
    for path in ("/onboarding/postfach", "/onboarding/ziel", "/onboarding/probelauf",
                 "/onboarding/aktivieren", "/onboarding/ueberspringen"):
        assert web.browser.request("POST", path, {"csrf": f_skip["csrf"], "version": "1", "key": "x" * 32}).status == 403


def _tls(directory):
    create_ca(directory / "ca")
    issue(directory / "ca", directory / "certs", "anna", server=False)
    return {"certificate": str(directory / "certs" / "anna.pem"), "key": str(directory / "certs" / "anna.key"),
            "ca": str(directory / "ca" / "ca.pem")}


def test_writers_wiring_and_warnings_for_hosted_microsoft_and_notion(configured, tmp_path, monkeypatch):
    conn = "c" * 32
    hosted_cfg = hosted_settings().model_copy(update=_tls(tmp_path / "tls"))

    # TargetSettings bindings and validation
    t_ms = TargetSettings(calendar_provider="outlook", outlook_calendar="default",
                          task_provider="microsoft_todo", microsoft_todo_list="default",
                          microsoft_connection=conn)
    assert t_ms.calendar_binding == "outlook-" + conn[:16]
    assert provider_secret_names(t_ms) == []

    # Writers with hosted microsoft_connection and notion_connection
    cfg = configured.cfg.model_copy(update={
        "hosted_auth": hosted_cfg,
        "targets": TargetSettings(
            calendar_provider="outlook", outlook_calendar="default",
            task_provider="notion", notion_data_source_id="a" * 32,
            notion_properties={"title": "t", "description": "d", "due": "u", "source": "s", "operation_key": "k"},
            microsoft_connection=conn, notion_connection=conn,
        ),
    })
    from mailhelp.config import Secrets
    writers = build_writers(
        cfg,
        Secrets(imap={1: {"username": "u@example.test", "password": "pw"}}, openrouter_api_key="sk-test"),
        tmp_path,
    )
    assert writers.calendar.binding == "outlook-" + conn[:16]
    writers.close()

    # browser_accounts hosted_notion_token & initial_pages boxes & connection_warnings
    (configured.tmp_path / "config.yaml").write_text(
        yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
    configured.app.services = SimpleNamespace()
    monkeypatch.setattr(browser_accounts, "cached_client",
                        lambda _read: lambda: SimpleNamespace(post=lambda _p, _d: {"access_token": "ntn_tok"}))
    browser_accounts.attach_accounts(configured.app, configured.web.site, configured.tmp_path)
    # Exercise hosted_notion_token when notion_connection is set
    assert configured.web.browser.request("GET", "/notion/datenquelle?profile=1").status == 409
    # And when notion_connection is empty
    cfg_no_ntn = cfg.model_copy(update={"targets": cfg.targets.model_copy(update={"notion_connection": ""})})
    (configured.tmp_path / "config.yaml").write_text(
        yaml.safe_dump(cfg_no_ntn.model_dump(mode="json")), encoding="utf-8")
    assert configured.web.browser.request("GET", "/notion/datenquelle?profile=1").status == 409

    boxes = hosted_target_boxes({"microsoft_connection": conn, "notion_connection": conn}, 2)
    assert "Microsoft erneut verbinden" in boxes and "Notion erneut verbinden" in boxes
    when = datetime(2026, 11, 20, 8, tzinfo=UTC)
    warn = connection_warnings([
        ConnectionProblem(key="ms", service="microsoft_oauth", code="refresh_denied",
                          first_seen=when, last_seen=when, sequence=1),
        ConnectionProblem(key="ntn", service="notion", code="login_rejected", number=2,
                          first_seen=when, last_seen=when, sequence=2),
    ], "UTC", hosted_google=True)
    assert 'href="/microsoft/verbinden?profile=1">Microsoft erneut verbinden' in warn
    assert 'href="/notion/verbinden?profile=2">Notion erneut verbinden' in warn
