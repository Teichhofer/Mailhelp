import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
import yaml

from mailhelp.notifications.webpush import PushService
from mailhelp.runtime.diagnostics import DiagnosticsService
from tests.fakes.push68 import subscription


def push_for(web, sent=None):
    push = PushService(
        web.store, web.auth, "mailto:ops@example.test", lambda **kw: (sent.append(kw) if sent is not None else None)
    )
    web.site.experience.push = push
    return push, web.auth.sessions()[0].id


def post(web, path, **fields):
    sid = web.auth.sessions()[0].id
    return web.browser.request("POST", path, {"csrf": web.auth.csrf_token(sid), **fields}, accept="application/json")


def test_own_device_status_has_no_subscription_secrets_or_other_device_data(web):
    push, sid = push_for(web)
    value = subscription()
    push.change(sid, "subscribe-01", value)
    data = json.loads(web.browser.request("GET", "/api/push/status").body)
    assert data["offered"] and data["device"]["registered"] and data["device"]["activated_at"]
    assert data["public_key"] == push.public_key and data["key_fingerprint"] == push.fingerprint
    text = json.dumps(data)
    for secret in [push.private, value["endpoint"], *value["keys"].values()]:
        assert secret not in text
    assert not push.status("different-session")["registered"]
    web.auth.revoke_all()
    assert web.browser.request("GET", "/api/push/status").status == 401
    assert web.browser.request("GET", "/api/push/public-key").status == 401


def test_server_off_and_subscription_codes_and_csrf(web, monkeypatch):
    assert web.site.experience.push_page.warnings() == ()
    html = web.browser.request("GET", "/einstellungen?bereich=benachrichtigungen").body.decode()
    assert "am Server ausgeschaltet" in html and 'id="push-enable"' not in html
    assert "JavaScript" in html
    assert json.loads(web.browser.request("GET", "/api/push/public-key").body)["code"] == "push_disabled"
    assert json.loads(post(web, "/api/push/subscribe").body)["code"] == "push_disabled"
    push, sid = push_for(web)
    bad = web.browser.request("POST", "/api/push/subscribe", {"csrf": "wrong"}, accept="application/json")
    assert bad.status == 403 and json.loads(bad.body)["code"] == "csrf_rejected"
    assert json.loads(post(web, "/api/push/subscribe", subscription="invalid").body)["code"] == "invalid_subscription"
    assert json.loads(post(web, "/api/push/subscribe", subscription="null").body)["code"] == "invalid_subscription"
    assert json.loads(post(web, "/api/push/subscribe", subscription="{}").body)["code"] == "invalid_subscription"
    value = subscription()
    value["endpoint"] = "https://evil.example/secret"
    assert (
        json.loads(post(web, "/api/push/subscribe", key="subscribe-01", subscription=json.dumps(value)).body)["code"]
        == "provider_not_allowed"
    )
    assert json.loads(post(web, "/api/push/subscribe", public_key="different").body)["code"] == "key_conflict"
    good = post(
        web,
        "/api/push/subscribe",
        key="subscribe-01",
        subscription=json.dumps(subscription()),
        public_key=push.public_key,
    )
    assert good.status == 200

    def expired(*_):
        raise PermissionError("synthetic")

    monkeypatch.setattr(push, "change", expired)
    assert json.loads(post(web, "/api/push/unsubscribe", key="unsubscribe-01").body)["code"] == "session_expired"


def test_example_contact_and_key_change_warn_without_showing_secrets(web):
    push, sid = push_for(web)
    push.subject = "mailto:admin@example.invalid"
    push.key_changed = True
    html = web.browser.request("GET", "/status").body.decode()
    assert "Beispielwert" in html and "Serverschlüssel" in html
    assert push.private not in html
    assert len(web.site.experience.push_page.warnings()) == 2


@pytest.mark.parametrize("value", ["null", "[]", "42", '"synthetic"'])
def test_invalid_json_subscription_cannot_unsubscribe_the_existing_device(web, value):
    push, sid = push_for(web)
    push.change(sid, "subscribe-existing", subscription())
    before = web.store.load("push-subscriptions")
    response = post(web, "/api/push/subscribe", key="subscribe-invalid", subscription=value)
    assert response.status == 400
    assert web.store.load("push-subscriptions") == before


def test_channel_preview_changes_nothing_and_confirm_is_versioned(configured):
    web = configured.web
    push, sid = push_for(web)
    push.change(sid, "subscribe-01", subscription())
    path = configured.tmp_path / "config.yaml"
    original = path.read_bytes()
    html = web.browser.request("GET", "/einstellungen?bereich=benachrichtigungen").body.decode()
    assert "Web-Push für neue Vorschläge einschalten" in html
    form = web.form("/push/kanaele", action="/push/kanaele")
    assert path.read_bytes() == original
    response = web.browser.request("POST", "/push/kanaele", form)
    assert response.status == 303
    web.run()
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "web_push" in saved["notifications"]["categories"]["decisions"]
    assert "web_push" in saved["notifications"]["categories"]["daily_briefing"]
    html = web.browser.request("GET", "/einstellungen?bereich=benachrichtigungen").body.decode()
    assert "Neue Vorschläge werden nicht per Push gemeldet." not in html
    assert web.browser.request("POST", "/push/kanaele", {**form, "key": "different-key"}).status == 409
    web.auth.revoke_all()
    assert web.browser.request("GET", "/push/kanaele").status == 303


def test_channel_confirmation_requires_live_session_and_explicit_form(configured):
    web = configured.web
    original = (configured.tmp_path / "config.yaml").read_bytes()
    form = web.form("/push/kanaele", action="/push/kanaele")
    assert web.browser.request("POST", "/push/kanaele", {**form, "confirm": "no"}).status == 422
    assert web.browser.request("POST", "/push/kanaele", {**form, "csrf": "wrong"}).status == 403
    web.browser.request("POST", "/push/kanaele", form)
    web.auth.revoke_all()
    web.run()
    assert (configured.tmp_path / "config.yaml").read_bytes() == original


def test_unavailable_profile_and_invalid_mailbox_are_explained(web, configured):
    site = configured.web.site
    assert configured.web.browser.request("GET", "/push/kanaele?postfach=99").status == 422
    assert configured.web.browser.request("GET", "/push/kanaele?postfach=not-a-number").status == 422
    site.archive.configuration = None
    assert configured.web.browser.request("GET", "/push/kanaele").status == 422


def test_real_test_path_uses_diagnostic_receipts_and_is_rate_limited(web):
    sent = []
    push, sid = push_for(web, sent)
    assert json.loads(post(web, "/api/push/test").body)["code"] == "push_disabled"

    def send(actor):
        push.deliver(push.destinations()[0], "test")
        return "ready", ""

    diagnostics = DiagnosticsService(web.store, web.auth.active, {"push_test": send})
    web.site.setup_page.runtime = SimpleNamespace(diagnostics=diagnostics)
    assert (
        json.loads(post(web, "/api/push/test", key="test-key01", version="0").body)["code"] == "device_not_registered"
    )
    push.change(sid, "subscribe-01", subscription())
    assert post(web, "/api/push/test", key="bad", version="0").status == 400
    assert post(web, "/api/push/test", key="test-key01", version="bad").status == 400
    for number in range(3):
        version = diagnostics.state().version
        fields = {"key": f"test-key{number:02}", "version": str(version)}
        assert json.loads(post(web, "/api/push/test", **fields).body)["code"] == "accepted"
        assert json.loads(post(web, "/api/push/test", **fields).body)["code"] == "accepted"
    assert len(sent) == 3
    assert post(web, "/api/push/test", key="fourth-key", version=str(diagnostics.state().version)).status == 429
    assert all(json.loads(item["data"]) == {"tag": "test"} for item in sent)


def test_test_push_rejection_key_conflict_and_stale_receipt(web):
    push, sid = push_for(web)
    diagnostics = DiagnosticsService(web.store, web.auth.active, {"push_test": lambda _: ("failed", "service")})
    web.site.setup_page.runtime = SimpleNamespace(diagnostics=diagnostics)
    push.change(sid, "subscribe-01", subscription())
    assert post(web, "/api/push/test", key="test-key01", version="99").status == 409
    state = web.store.load("push-subscriptions")
    state["metadata"][sid]["rejected"] = True
    web.store.save("push-subscriptions", state)
    assert json.loads(post(web, "/api/push/test", key="test-key02", version="0").body)["code"] == "provider_rejected"
    state["metadata"][sid]["rejected"] = False
    state["metadata"][sid]["fingerprint"] = "old"
    web.store.save("push-subscriptions", state)
    assert json.loads(post(web, "/api/push/test", key="test-key03", version="0").body)["code"] == "key_conflict"
    state["metadata"][sid]["fingerprint"] = push.fingerprint
    web.store.save("push-subscriptions", state)
    assert json.loads(post(web, "/api/push/test", key="test-key04", version="0").body)["code"] == "test_failed"


def test_mailbox_channel_confirmation_preserves_other_profiles(configured):
    from mailhelp.config.mail_settings import ImapSettings, MailboxSettings
    from mailhelp.config.notifications import NotificationSettings

    cfg = configured.app.settings
    cfg.notifications = NotificationSettings(categories={"decisions": ["telegram"]})
    cfg.imap = ImapSettings(
        mailboxes=[MailboxSettings(id=n, host="synthetic.test", port=993, folders=["INBOX"]) for n in (1, 2)]
    )
    path = configured.tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
    form = configured.web.form("/push/kanaele?postfach=2", action="/push/kanaele")
    assert configured.web.browser.request("POST", "/push/kanaele", form).status == 303
    configured.web.run()
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["imap"]["mailboxes"][0]["notifications"] is None
    assert saved["notifications"]["categories"]["decisions"] == ["telegram"]
    assert saved["imap"]["mailboxes"][1]["notifications"]["categories"]["decisions"] == ["telegram", "web_push"]
    # A preview of an already enabled profile is harmless and preserves the list.
    assert configured.web.browser.request("GET", "/push/kanaele?postfach=2").status == 200


@pytest.mark.parametrize(
    "last,diagnostic,expected",
    [
        ("accepted", "service", "test_failed"),
        ("not_tested", "timeout", "test_timeout"),
        ("provider_rejected", "permission", "provider_rejected"),
        ("retryable", "service", "retryable"),
    ],
)
def test_failed_test_cannot_report_an_old_accepted_delivery(web, last, diagnostic, expected):
    push, sid = push_for(web)
    push.change(sid, "subscribe-01", subscription())
    state = web.store.load("push-subscriptions")
    state["metadata"][sid]["last_code"] = last
    web.store.save("push-subscriptions", state)
    service = DiagnosticsService(web.store, web.auth.active, {"push_test": lambda _: ("failed", diagnostic)})
    web.site.setup_page.runtime = SimpleNamespace(diagnostics=service)
    result = json.loads(post(web, "/api/push/test", key="test-failure01", version="0").body)
    assert result["code"] == expected


def test_readonly_push_diagnosis_distinguishes_contact_rotation_and_rejection(configured):
    web = configured.web
    push, sid = push_for(web)
    configured.app.settings.push.enabled = True
    push.subject = "mailto:admin@example.invalid"
    assert configured.runtime.push(sid) == ("limited", "vapid_subject")
    push.subject = "mailto:ops@example.test"
    push.key_changed = True
    assert configured.runtime.push(sid) == ("limited", "vapid_changed")
    push.change(sid, "subscribe-01", subscription())
    state = web.store.load("push-subscriptions")
    state["metadata"][sid]["rejected"] = True
    web.store.save("push-subscriptions", state)
    assert configured.runtime.push(sid) == ("limited", "push_rejected")
