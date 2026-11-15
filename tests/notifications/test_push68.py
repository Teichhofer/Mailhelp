import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import requests
from pywebpush import WebPushException

from mailhelp.llm.adapter import PermanentError, RetryableError
from mailhelp.notifications.webpush import PushService
from mailhelp.storage import JsonStore
from tests.fakes.log_fakes import RecordingLogger
from tests.fakes.push68 import subscription


@pytest.mark.parametrize("status", [401, 403])
def test_regression_rejected_subscription_is_not_used_again_after_restart(tmp_path, status):
    calls = []

    def reject(**kwargs):
        calls.append(1)
        response = requests.Response()
        response.status_code = status
        raise WebPushException("SYNTHETIC PRIVATE RESPONSE", response=response)

    with JsonStore(tmp_path) as store:
        auth = SimpleNamespace(active=lambda _: True)
        push = PushService(store, auth, "mailto:synthetic@example.test", reject)
        push.change("device", "activate-001", subscription())
        with pytest.raises(PermanentError):
            push.deliver(push.destinations()[0], "decisions")
        assert push.destinations() == []
        assert PushService(store, auth, "mailto:synthetic@example.test", reject).destinations() == []
        assert calls == [1]


@pytest.mark.parametrize(
    "status,code,error",
    [
        (400, "provider_refused", PermanentError),
        (401, "provider_rejected", PermanentError),
        (403, "provider_rejected", PermanentError),
        (404, "expired", PermanentError),
        (410, "expired", PermanentError),
        (429, "retryable", RetryableError),
        (500, "retryable", RetryableError),
        (503, "retryable", RetryableError),
        (None, "retryable", RetryableError),
    ],
)
def test_safe_delivery_outcomes_are_persisted_and_never_log_secrets(tmp_path, status, code, error):
    log = RecordingLogger()
    response = requests.Response() if status is not None else None
    if response is not None:
        response.status_code = status

    def send(**_):
        raise WebPushException("SECRET ENDPOINT AND PRIVATE KEY", response=response)

    with JsonStore(tmp_path) as store:
        push = PushService(store, SimpleNamespace(active=lambda _: True), "mailto:ops@example.test", send, logger=log)
        value = subscription()
        push.change("a" * 16, "subscribe-01", value)
        device = push.destinations()[0]
        with pytest.raises(error):
            push.deliver(device, "test")
        own = push.status("a" * 16)
        assert own["last_code"] == code and own["last_at"]
        assert own["rejected"] == (status in (401, 403))
        assert own["registered"] == (status not in (404, 410))
        text = repr(log.events)
        for secret in [push.private, value["endpoint"], *value["keys"].values(), "SECRET"]:
            assert secret not in text
        assert "apple" in text and code in text


def test_network_error_legacy_notify_and_success_share_the_safe_path(tmp_path):
    now = [datetime(2026, 11, 14, 10, tzinfo=UTC)]
    sent = []
    log = RecordingLogger()
    active = {"a" * 16, "b" * 16}
    with JsonStore(tmp_path) as store:
        push = PushService(
            store,
            SimpleNamespace(active=lambda a: a in active),
            "mailto:ops@example.test",
            lambda **kwargs: sent.append(kwargs),
            logger=log,
            clock=lambda: now[0],
        )
        value = subscription()
        push.change("a" * 16, "subscribe-01", value)
        first = push.destinations()[0]
        activated = push.status("a" * 16)["activated_at"]
        now[0] += timedelta(minutes=1)
        push.change("a" * 16, "subscribe-02", value)
        assert push.status("a" * 16)["activated_at"] == activated and push.destinations() == [first]
        push.change("b" * 16, "subscribe-01", subscription())
        active.remove("b" * 16)
        push.notify("test")
        assert json.loads(sent[0]["data"]) == {"tag": "test"}
        assert push.status("a" * 16)["last_code"] == "accepted"
        assert set(store.load("push-subscriptions")["devices"]) == {"a" * 16}

        def offline(**_):
            raise requests.ConnectionError("SECRET ENDPOINT")

        push.sender = offline
        with pytest.raises(RetryableError):
            push.deliver(first, "decisions")
        push.notify()
        assert push.status("a" * 16)["last_code"] == "retryable"
        assert "SECRET" not in repr(log.events)
        active.clear()
        with pytest.raises(PermanentError):
            push.deliver(first, "test")


def test_key_rotation_and_legacy_metadata_reactivation_are_restart_safe(tmp_path):
    auth = SimpleNamespace(active=lambda _: True)
    with JsonStore(tmp_path) as store:
        push = PushService(store, auth, "mailto:ops@example.test", lambda **_: None)
        value = subscription()
        push.change("a" * 16, "subscribe-01", value)
        before = push.fingerprint
        store.save("web-vapid", None)
        changed = PushService(store, auth, "mailto:ops@example.test", lambda **_: None)
        assert changed.key_changed and changed.fingerprint != before
        assert changed.destinations() == [] and not changed.status("a" * 16)["key_matches"]
        changed.change("a" * 16, "subscribe-02", value)
        assert changed.destinations() and changed.status("a" * 16)["key_matches"]
        state = store.load("push-subscriptions")
        state.pop("metadata")
        store.save("push-subscriptions", state)
        restarted = PushService(store, auth, "mailto:ops@example.test", lambda **_: None)
        assert restarted.status("a" * 16)["activated_at"] and restarted.destinations()
        assert not restarted.key_changed


def test_rejecting_a_replaced_subscription_does_not_disable_its_replacement(tmp_path):
    with JsonStore(tmp_path) as store:
        push = PushService(store, SimpleNamespace(active=lambda _: True), "mailto:ops@example.test")
        push.change("a" * 16, "subscribe-01", subscription())

        def replace(**_):
            push.change("a" * 16, "subscribe-02", subscription())
            response = requests.Response()
            response.status_code = 403
            raise WebPushException("SECRET", response=response)

        push.sender = replace
        with pytest.raises(PermanentError):
            push.deliver(push.destinations()[0], "test")
        assert push.destinations() and not push.status("a" * 16)["rejected"]
