"""VAPID notifications with device ownership and content-free payloads."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from threading import Lock
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid
from pywebpush import webpush, WebPushException
import requests


def b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def subscription(value):
    """Only known browser push providers, never arbitrary user supplied URLs."""
    endpoint = value["endpoint"]
    url = urlsplit(endpoint)
    allowed = (url.hostname in {"fcm.googleapis.com", "updates.push.services.mozilla.com",
                               "web.push.apple.com"}
               or bool(re.fullmatch(r"[a-z0-9-]+\.notify\.windows\.com", url.hostname or "")))
    if (not allowed or url.scheme != "https" or url.port not in (None, 443)
            or url.username or url.password or url.fragment or len(endpoint) > 4096):
        raise ValueError("Ungültiger Push-Anbieter")
    keys = value["keys"]
    decoded = {}
    for name, size in (("p256dh", 65), ("auth", 16)):
        text = keys[name]
        if not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", text):
            raise ValueError("Ungültiger Push-Schlüssel")
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
        if len(raw) != size:
            raise ValueError("Ungültige Push-Schlüssellänge")
        decoded[name] = text
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),
        base64.urlsafe_b64decode(decoded["p256dh"] + "=" * (-len(decoded["p256dh"]) % 4)))
    return {"endpoint": endpoint, "keys": decoded}


MAX_OPERATIONS = 500


class NoRedirectSession(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs["allow_redirects"] = False
        return super().request(method, url, **kwargs)


class PushService:
    def __init__(self, store, auth, subject, sender=webpush):
        self.store, self.auth, self.subject, self.sender = store, auth, subject, sender
        # Serializes subscription changes; never held by other parts of Mailhelp.
        self._lock = Lock()
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

    def change(self, actor, key, value=None):
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", key):
            raise ValueError("Idempotenzschlüssel fehlt")
        checked = subscription(value) if value is not None else None
        digest = hashlib.sha256(json.dumps(checked, sort_keys=True).encode()).hexdigest()
        with self._lock:
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
            else:
                state["devices"][actor] = checked
            state["operations"][operation] = digest
            # Replays are only expected shortly after a request; old keys are dropped.
            state["operations"] = dict(list(state["operations"].items())[-MAX_OPERATIONS:])
            self.store.save("push-subscriptions", state)

    def _state(self):
        return self.store.load("push-subscriptions", {"devices": {}, "operations": {}})

    def notify(self, tag="decisions"):
        """Never put subjects, mail text, calendar titles or tokens on lock screens.

        Delivery runs without any lock; a device is only removed afterwards if its
        subscription did not change in the meantime.
        """
        with self._lock:
            state = self._state()
            stale = [actor for actor in state["devices"] if not self.auth.active(actor)]
            for actor in stale:
                del state["devices"][actor]
            if stale:
                self.store.save("push-subscriptions", state)
            devices = dict(state["devices"])
        gone = []
        for actor, item in devices.items():
            try:
                with NoRedirectSession() as transport:
                    self.sender(subscription_info=item,
                        data=json.dumps({"title": "Mailhelp", "body": "Neue Informationen in Mailhelp.",
                                         "url": "/offen", "tag": tag}),
                        vapid_private_key=self.private, vapid_claims={"sub": self.subject},
                        content_encoding="aes128gcm", ttl=3600, timeout=10,
                        requests_session=transport)
            except WebPushException as exc:
                if exc.response is not None and exc.response.status_code in (404, 410):
                    gone.append(actor)
            except requests.RequestException:
                pass
        if gone:
            with self._lock:
                state = self._state()
                for actor in gone:
                    if state["devices"].get(actor) == devices[actor]:
                        del state["devices"][actor]
                self.store.save("push-subscriptions", state)
