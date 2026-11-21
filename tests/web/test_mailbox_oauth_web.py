"""Synthetic mailbox sign-in through the real central state machine and local routes."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest

from inboxstride_auth.google import Client, GoogleTokens
from inboxstride_auth.microsoft import CALLBACK, MicrosoftTokens
from inboxstride_auth.models import MAIL_SCOPES
from mailhelp.config import MailboxSettings
from mailhelp.web.mailbox_oauth_site import BASE, PENDING, RETURN, MailboxOAuthContext, MailboxOAuthSite
from tests.fakes.hosted_web import central, fields  # noqa: F401
from tests.fakes.shared_web_actions import web  # noqa: F401


@pytest.fixture
def mailbox_web(web, central):
    tokens = []
    for purpose, kind in (("gmail", GoogleTokens), ("microsoft", MicrosoftTokens)):
        def endpoint(request, purpose=purpose):
            return httpx.Response(200, json={"access_token": "access-mail", "refresh_token": "refresh-mail",
                "expires_in": 3600, "token_type": "Bearer", "scope": " ".join(MAIL_SCOPES[purpose])})
        client = Client("synthetic", "synthetic", CALLBACK) if purpose == "microsoft" else Client("id", "secret")
        provider = kind(client, transport=httpx.MockTransport(endpoint))
        tokens.append(provider)
        central.service.mail_providers[purpose] = provider
    state = {"mailbox": MailboxSettings(id=1, host="old.example.test", port=993, folders=["INBOX"]),
             "version": 1, "revision": "original", "saved": [], "down": False, "probe_error": False}

    def read(number):
        if number != 1:
            raise ValueError("number")
        return state["mailbox"], state["version"], state["revision"]

    def save(actor, mailbox, username, version, key, revision):
        if state.get("save_error"):
            raise OSError("synthetic-save-error")
        assert version == state["version"] and revision == state["revision"]
        state["mailbox"], state["version"], state["revision"] = mailbox, version + 1, "saved"
        state["saved"].append((actor, mailbox, username))

    def probe(mailbox, username):
        assert mailbox.oauth_connection and username == "user@example.test"
        if state["probe_error"]:
            raise OSError("secret-must-not-be-rendered")
        return [("INBOX", "inbox"), ("Entwurf", "drafts"), ("Archiv", None)]

    client = central.client("anna")
    site = MailboxOAuthSite(web.site, web.store, lambda: None if state["down"] else client,
                           MailboxOAuthContext(read, save, probe), "/einrichtung/start")
    web.mail_state, web.mail_site, web.central = state, site, central
    yield web
    client.close()
    for provider in tokens:
        provider.close()


def begin(web, purpose="gmail"):
    page = web.browser.request("GET", BASE + "?provider=" + purpose + "&mailbox=1")
    assert page.status == 200
    form = fields(page.body.decode(), BASE)
    return web.browser.request("POST", BASE, {**form, "username": "user@example.test"})


def ready(web, purpose="gmail"):
    started = begin(web, purpose)
    assert started.status == 303
    state = parse_qs(urlsplit(started.headers["Location"]).query)["state"][0]
    returned = web.central.service.callback(state, "good", None, "microsoft" if purpose == "microsoft" else "google")
    query = urlsplit(returned).query
    page = web.browser.request("GET", RETURN + "?" + query)
    assert page.status == 200 and page.headers["Cache-Control"] == "no-store"
    confirm = web.browser.request("GET", BASE + "/ordner?" + query)
    checked = web.browser.request("POST", RETURN, fields(confirm.body.decode(), RETURN))
    assert checked.status == 303
    return web.browser.request("GET", BASE + "/ordner")


@pytest.mark.parametrize("purpose", ["gmail", "microsoft"])
def test_mailbox_adoption_and_explicit_disconnect(mailbox_web, purpose):
    web = mailbox_web
    page = ready(web, purpose)
    assert page.status == 200 and "Entwurf" in page.body.decode()
    assert web.mail_state["saved"] == []
    form = {**fields(page.body.decode(), BASE + "/ordner"), "inbox": "INBOX", "drafts": "Entwurf"}
    response = web.browser.request("POST", BASE + "/ordner", form)
    assert response.status == 303
    item = web.mail_state["mailbox"]
    assert item.auth_method == purpose and item.drafts_folder == "Entwurf"
    assert web.central.service.state.read().connections[item.oauth_connection].status == "active"
    assert web.store.load(PENDING) == {}
    csrf = form["csrf"]
    disconnected = web.browser.request("POST", BASE + "/trennen", {"csrf": csrf, "mailbox": "1",
        "version": "2", "revision": "saved"})
    assert disconnected.status == 303
    assert web.central.service.state.read().connections[item.oauth_connection].status == "disconnected"
    assert web.browser.request("POST", BASE + "/ordner", form).status == 409


@pytest.mark.parametrize("query", ["", "provider=other&mailbox=1", "provider=gmail&mailbox=99",
                                   "provider=gmail&mailbox=bad"])
def test_bad_offer_is_rejected_without_state_changes(mailbox_web, query):
    assert mailbox_web.browser.request("GET", BASE + "?" + query).status == 409
    assert mailbox_web.store.load(PENDING, {}) == {}


def test_disabled_provider_and_unavailable_client(mailbox_web):
    web = mailbox_web
    web.central.service.mail_providers.clear()
    assert web.browser.request("GET", BASE + "?provider=gmail&mailbox=1").status == 409
    web.mail_state["down"] = True
    assert web.browser.request("GET", BASE + "?provider=gmail&mailbox=1").status == 409


@pytest.mark.parametrize("query", ["", "abbruch=1", "beleg=", "beleg=a&beleg=b", "beleg=" + "a" * 201])
def test_invalid_public_return_does_not_issue_a_session(mailbox_web, query):
    assert mailbox_web.browser.request("GET", RETURN + "?" + query).status == 409


@pytest.mark.parametrize("changes", [{"version": "0"}, {"revision": "changed"}, {"purpose": "calendar"},
                                      {"username": ""}, {"username": "bad\ruser"}, {"mailbox": "99"}])
def test_invalid_start_preserves_the_previous_connection(mailbox_web, changes):
    web = mailbox_web
    page = web.browser.request("GET", BASE + "?provider=gmail&mailbox=1")
    form = {**fields(page.body.decode(), BASE), "username": "user@example.test", **changes}
    assert web.browser.request("POST", BASE, form).status == 409
    assert web.store.load(PENDING, {}) == {}


def test_probe_errors_and_modified_draft_do_not_commit(mailbox_web):
    web = mailbox_web
    page = ready(web)
    form = {**fields(page.body.decode(), BASE + "/ordner"), "inbox": "INBOX", "drafts": "Entwurf"}
    web.mail_state["probe_error"] = True
    assert web.browser.request("GET", BASE + "/ordner").status == 409
    result = web.browser.request("POST", BASE + "/ordner", form)
    assert result.status == 409 and b"secret-must-not-be-rendered" not in result.body
    web.mail_state["probe_error"] = False
    web.mail_state["revision"] = "foreign-edit"
    assert web.browser.request("POST", BASE + "/ordner", form).status == 409
    assert web.mail_state["saved"] == []


def test_expired_pending_and_wrong_receipt_fail(mailbox_web):
    web = mailbox_web
    begin(web)
    state = web.store.load(PENDING)
    record = next(iter(state.values()))
    record["expires"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    web.store.save(PENDING, state)
    assert web.browser.request("GET", BASE + "/ordner").status == 409
    confirm = web.browser.request("GET", BASE + "/ordner?" + urlencode({"beleg": "wrong"}))
    assert confirm.status == 409


def test_failed_save_and_activation_can_be_retried_without_a_second_save(mailbox_web, monkeypatch):
    web = mailbox_web
    page = ready(web)
    form = {**fields(page.body.decode(), BASE + "/ordner"), "inbox": "INBOX", "drafts": "Entwurf"}
    assert web.browser.request("POST", BASE + "/ordner", {**form, "drafts": "missing"}).status == 409
    web.mail_state["save_error"] = True
    assert web.browser.request("POST", BASE + "/ordner", form).status == 409
    assert web.mail_state["saved"] == []
    web.mail_state["save_error"] = False
    activate = web.central.service.activate
    monkeypatch.setattr(web.central.service, "activate", lambda *_args: (_ for _ in ()).throw(ValueError("outage")))
    assert web.browser.request("POST", BASE + "/ordner", form).status == 409
    assert len(web.mail_state["saved"]) == 1
    monkeypatch.setattr(web.central.service, "activate", activate)
    assert web.browser.request("POST", BASE + "/ordner", form).status == 303
    assert len(web.mail_state["saved"]) == 1


def test_untrusted_authorization_redirect_is_refused(mailbox_web, monkeypatch):
    web = mailbox_web
    client = web.mail_site.hub()
    post = client.post
    def changed(path, data):
        result = post(path, data)
        return {**result, "url": "https://attacker.test/"} if path == "/intern/start" else result
    monkeypatch.setattr(client, "post", changed)
    assert begin(web).status == 409 and web.store.load(PENDING, {}) == {}


@pytest.mark.parametrize("wrong_binding", [False, True])
def test_invalid_receipt_or_redeemed_target_cannot_be_adopted(mailbox_web, monkeypatch, wrong_binding):
    web = mailbox_web
    response = begin(web)
    state = parse_qs(urlsplit(response.headers["Location"]).query)["state"][0]
    back = web.central.service.callback(state, "good", None)
    receipt = parse_qs(urlsplit(back).query)["beleg"][0] if wrong_binding else "wrong"
    client = web.mail_site.hub()
    post = client.post
    def changed(path, data):
        result = post(path, data)
        return {**result, "purpose": "calendar"} if path == "/intern/redeem" else result
    monkeypatch.setattr(client, "post", changed)
    form = web.browser.request("GET", BASE + "/ordner?beleg=" + receipt)
    assert web.browser.request("POST", RETURN, fields(form.body.decode(), RETURN)).status == 409
    assert web.mail_state["saved"] == []


def test_lost_activation_response_and_changed_repeat(mailbox_web, monkeypatch):
    web = mailbox_web
    page = ready(web)
    form = {**fields(page.body.decode(), BASE + "/ordner"), "inbox": "INBOX", "drafts": "Entwurf"}
    activate = web.central.service.activate
    def lost(*args):
        activate(*args)
        raise ValueError("synthetic-response-lost")
    monkeypatch.setattr(web.central.service, "activate", lost)
    assert web.browser.request("POST", BASE + "/ordner", form).status == 409
    assert web.browser.request("POST", BASE + "/ordner", {**form, "inbox": "Archiv"}).status == 409
    assert web.browser.request("POST", BASE + "/ordner", form).status == 303
    assert len(web.mail_state["saved"]) == 1


def test_session_revocation_before_activation_and_stale_disconnect(mailbox_web, monkeypatch):
    web = mailbox_web
    page = ready(web)
    form = {**fields(page.body.decode(), BASE + "/ordner"), "inbox": "INBOX", "drafts": "Entwurf"}
    save = web.mail_site.context.save
    def expire(*args):
        save(*args)
        monkeypatch.setattr(web.auth, "active", lambda _session: False)
    web.mail_site.context = replace(web.mail_site.context, save=expire)
    assert web.browser.request("POST", BASE + "/ordner", form).status == 409
    assert web.browser.request("POST", BASE + "/trennen", {**form, "mailbox": "1", "version": "99",
                                                            "revision": "stale"}).status == 409


def test_a_foreign_edit_after_local_save_blocks_activation_retry(mailbox_web, monkeypatch):
    web = mailbox_web
    page = ready(web)
    form = {**fields(page.body.decode(), BASE + "/ordner"), "inbox": "INBOX", "drafts": "Entwurf"}
    activate = web.central.service.activate
    monkeypatch.setattr(web.central.service, "activate", lambda *_: (_ for _ in ()).throw(ValueError("outage")))
    assert web.browser.request("POST", BASE + "/ordner", form).status == 409
    web.mail_state["revision"] = "foreign-edit-after-save"
    monkeypatch.setattr(web.central.service, "activate", activate)
    assert web.browser.request("POST", BASE + "/ordner", form).status == 409
    connection = web.mail_state["mailbox"].oauth_connection
    assert web.central.service.state.read().connections[connection].status == "candidate"


@pytest.mark.parametrize("path", ["/intern/connection", "/intern/activate"])
def test_inconsistent_central_binding_is_refused_and_retry_reconciles(mailbox_web, monkeypatch, path):
    web = mailbox_web
    page = ready(web)
    form = {**fields(page.body.decode(), BASE + "/ordner"), "inbox": "INBOX", "drafts": "Entwurf"}
    client = web.mail_site.hub()
    post = client.post

    def inconsistent(route, payload):
        result = post(route, payload)
        return {**result, "target": "mailbox:2"} if route == path else result

    monkeypatch.setattr(client, "post", inconsistent)
    assert web.browser.request("POST", BASE + "/ordner", form).status == 409
    assert len(web.mail_state["saved"]) == 1
    monkeypatch.setattr(client, "post", post)
    assert web.browser.request("POST", BASE + "/ordner", form).status == 303
    assert len(web.mail_state["saved"]) == 1
