"""VAPID notifications with device ownership and content-free payloads."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid
from pywebpush import WebPushException, webpush

from ..llm.adapter import PermanentError, RetryableError
from ..logging import NullLogger
from ..storage import StateStore


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def subscription(value: dict[str, Any]) -> dict[str, Any]:
    """Only known browser push providers, never arbitrary user supplied URLs."""
    endpoint = str(value["endpoint"])
    url = urlsplit(endpoint)
    allowed = (url.hostname in {"fcm.googleapis.com", "updates.push.services.mozilla.com",
                               "web.push.apple.com"}
               or bool(re.fullmatch(r"[a-z0-9-]+\.notify\.windows\.com", url.hostname or "")))
    if (not allowed or url.scheme != "https" or url.port not in (None, 443)
            or url.username or url.password or url.fragment or len(endpoint) > 4096):
        raise ValueError("Ungültiger Push-Anbieter")
    keys = value["keys"]
    decoded: dict[str, str] = {}
    for name, size in (("p256dh", 65), ("auth", 16)):
        text = str(keys[name])
        if not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", text):
            raise ValueError("Ungültiger Push-Schlüssel")
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
        if len(raw) != size:
            raise ValueError("Ungültige Push-Schlüssellänge")
        decoded[name] = text
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),
        base64.urlsafe_b64decode(decoded["p256dh"] + "=" * (-len(decoded["p256dh"]) % 4)))
    return {"endpoint": endpoint, "keys": decoded}


MAX_OPERATIONS = 500  # per device


class AuthSessionManager(Protocol):
    def active(self, session_id: str) -> bool: ...


class NoRedirectSession(requests.Session):
    def request(self, method: str, url: str | bytes, *args: Any, **kwargs: Any) -> requests.Response:
        kwargs["allow_redirects"] = False
        return super().request(method, url, *args, **kwargs)


class PushService:
    def __init__(self, store: StateStore, auth: AuthSessionManager, subject: str, sender: Any = webpush,
                 *, logger: Any = None, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.store, self.auth, self.subject, self.sender = store, auth, subject, sender
        self.logger, self.clock = logger or NullLogger(), clock
        # Subscription changes are serialized with the store's own lock: notification
        # delivery asks for destinations while holding it, so a separate push lock
        # taken before the store deadlocked with it.
        with store.locked():
            saved = store.load("web-vapid")
            if saved is None:
                vapid = Vapid()
                vapid.generate_keys()
                saved = {"private": b64(vapid.private_key.private_bytes(
                    serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption()))}
                store.save("web-vapid", saved)
            self.private = saved["private"]
            key = Vapid.from_string(self.private).public_key
            self.public_key = b64(key.public_bytes(serialization.Encoding.X962,
                                                  serialization.PublicFormat.UncompressedPoint))
            self.fingerprint = hashlib.sha256(self.public_key.encode()).hexdigest()
            health = store.load("push-key-status", {})
            self.key_changed = bool(health and health.get("fingerprint") != self.fingerprint)
            store.save("push-key-status", {"fingerprint": self.fingerprint, "changed": self.key_changed,
                                          "checked_at": clock().isoformat()})
            state = self._state()
            for actor in state["devices"]:
                state["metadata"].setdefault(actor, self._activation())
            store.save("push-subscriptions", state)

    def _activation(self) -> dict[str, Any]:
        return {"activated_at": self.clock().isoformat(), "fingerprint": self.fingerprint,
                "rejected": False, "last_code": "not_tested", "last_at": None}

    def change(self, actor: str, key: str, value: dict[str, Any] | None = None) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", key):
            raise ValueError("Idempotenzschlüssel fehlt")
        checked = subscription(value) if value is not None else None
        digest = hashlib.sha256(json.dumps(checked, sort_keys=True).encode()).hexdigest()
        with self.store.locked():
            if not self.auth.active(actor):
                raise PermissionError("Sitzung abgelaufen")
            state = self._state()
            operation = f"{actor}:{key}"
            if operation in state["operations"]:
                if state["operations"][operation] != digest:
                    raise ValueError("Idempotenzkonflikt")
                return
            if checked is None:
                state["devices"].pop(actor, None)
                state["metadata"].pop(actor, None)
            else:
                old = state["metadata"].get(actor, {})
                if (state["devices"].get(actor) != checked or old.get("rejected")
                        or old.get("fingerprint") != self.fingerprint):
                    state["metadata"][actor] = self._activation()
                state["devices"][actor] = checked
            state["operations"][operation] = digest
            # Replays are only expected shortly after a request; old keys are dropped,
            # counted per device so that one busy device never evicts another's keys.
            own = [name for name in state["operations"] if name.startswith(f"{actor}:")]
            for name in own[:-MAX_OPERATIONS]:
                del state["operations"][name]
            self.store.save("push-subscriptions", state)

    def _state(self) -> dict[str, Any]:
        state = cast(dict[str, Any], self.store.load("push-subscriptions", {"devices": {}, "operations": {}}))
        state.setdefault("metadata", {})
        return state

    def _revision(self, state: dict[str, Any], actor: str) -> str:
        material = [state["devices"].get(actor), state["metadata"].get(actor, {}).get("activated_at"),
                    self.fingerprint]
        return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()

    def status(self, actor: str) -> dict[str, Any]:
        """Only safe state of this device; never expose its endpoint or encryption keys."""
        with self.store.locked():
            state = self._state()
            meta = state["metadata"].get(actor, {})
            return {"registered": actor in state["devices"],
                    "activated_at": meta.get("activated_at"), "last_at": meta.get("last_at"),
                    "last_code": meta.get("last_code", "not_tested"),
                    "rejected": bool(meta.get("rejected")),
                    "key_matches": meta.get("fingerprint") == self.fingerprint}

    def destinations(self) -> list[str]:
        """Opaque subscription revisions keep provider addresses out of the queue."""
        with self.store.locked():
            state = self._state()
            return [f"{actor}:{self._revision(state, actor)}" for actor in state["devices"]
                    if self.auth.active(actor) and not state["metadata"].get(actor, {}).get("rejected")
                    and state["metadata"].get(actor, {}).get("fingerprint") == self.fingerprint]

    def _result(self, device: str, code: str, status: int, provider: str) -> None:
        actor = device.partition(":")[0]
        with self.store.locked():
            state = self._state()
            if actor in state["devices"] and device == f"{actor}:{self._revision(state, actor)}":
                meta = state["metadata"][actor]
                meta.update(last_code=code, last_at=self.clock().isoformat())
                if status in (401, 403):
                    meta["rejected"] = True
                if status in (404, 410):
                    del state["devices"][actor]
                self.store.save("push-subscriptions", state)
        self.logger.event("INFO" if code == "accepted" else "WARNING", "push", "delivery_result",
                          stage="provider", result_code=code, status_class=status // 100, provider=provider)

    def deliver(self, device: str, tag: str) -> None:
        actor = device.partition(":")[0]
        with self.store.locked():
            state = self._state()
            item = state["devices"].get(actor)
            if item is None or device not in self.destinations():
                raise PermanentError("Geraeteabonnement nicht mehr gueltig")
        host = urlsplit(item["endpoint"]).hostname
        provider = {"fcm.googleapis.com": "fcm", "web.push.apple.com": "apple",
                    "updates.push.services.mozilla.com": "mozilla"}.get(host, "windows")
        try:
            with NoRedirectSession() as transport:
                self.sender(subscription_info=item, data=json.dumps({"tag": tag}),
                    vapid_private_key=self.private, vapid_claims={"sub": self.subject},
                    content_encoding="aes128gcm", ttl=3600, timeout=10, requests_session=transport)
        except WebPushException as exc:
            status = exc.response.status_code if exc.response is not None else 0
            code = ("expired" if status in (404, 410) else "provider_rejected" if status in (401, 403)
                    else "provider_refused" if 400 <= status < 500 and status != 429 else "retryable")
            self._result(device, code, status, provider)
            if code in {"expired", "provider_rejected", "provider_refused"}:
                raise PermanentError("Push-Dienst hat das Abonnement abgelehnt") from exc
            raise RetryableError("Push-Dienst voruebergehend nicht erreichbar") from exc
        except requests.RequestException as exc:
            self._result(device, "retryable", 0, provider)
            raise RetryableError("Push-Dienst voruebergehend nicht erreichbar") from exc
        self._result(device, "accepted", 201, provider)

    def notify(self, tag: str = "decisions") -> None:
        """Compatibility path uses precisely the same validation and safe result logging."""
        with self.store.locked():
            state = self._state()
            for actor in list(state["devices"]):
                if not self.auth.active(actor):
                    del state["devices"][actor]
                    state["metadata"].pop(actor, None)
            self.store.save("push-subscriptions", state)
        for device in self.destinations():
            try:
                self.deliver(device, tag)
            except (PermanentError, RetryableError):
                pass
