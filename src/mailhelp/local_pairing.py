"""Host-authorized CLI pairing without credentials in logs or browser requests."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time

import httpx

from .config import Settings, _dotenv, read_yaml


def signature(secret: str, message: str) -> str:
    return hmac.new(secret.encode(), f"local-pair:{message}".encode(), hashlib.sha256).hexdigest()


def issue(auth, message, supplied, clock=time.time):
    try:
        stamp, nonce = message.split(":")
        valid = abs(clock() - int(stamp)) <= 60 and len(nonce) == 32
    except (ValueError, AttributeError):
        valid = False
    if not valid or not hmac.compare_digest(
        signature(auth._key.decode(), message).encode("utf-8"), supplied.encode("utf-8")
    ):
        raise PermissionError("Lokale Kopplung nicht autorisiert")
    with auth.store.locked():
        used = auth.store.load("local-pairing", {"schema_version": 1, "requests": {}})
        used["requests"] = {key: at for key, at in used["requests"].items() if clock() - at <= 120}
        if message in used["requests"]:
            raise PermissionError("Kopplungsanforderung bereits verwendet")
        used["requests"][message] = clock()
        auth.store.save("local-pairing", used)
    return auth.issue_code()


def request_local_code(directory):
    settings = Settings.model_validate(read_yaml(directory / "config.yaml"))
    env = {**_dotenv(directory / ".env"), **os.environ}
    secret = env.get("MAILHELP_WEB_SECRET", "")
    if not settings.web.enabled or len(secret) < 32:
        raise ValueError("web.enabled und MAILHELP_WEB_SECRET (mindestens 32 Zeichen) erforderlich")
    message = f"{int(time.time())}:{secrets.token_hex(16)}"
    with httpx.Client(trust_env=False, timeout=10) as client:
        response = client.post(f"http://127.0.0.1:{settings.web.port}/api/local-pair",
                               data={"message": message, "signature": signature(secret, message)})
        response.raise_for_status()
        code = response.json()["code"]
        if not isinstance(code, str) or not re.fullmatch(r"[0-9]{4}", code):
            raise ValueError("Lokaler Dienst hat keinen gültigen Einmalcode geliefert")
    print(f"Einmalcode: {code} – 10 Minuten gültig. In /anmelden eingeben.", flush=True)
