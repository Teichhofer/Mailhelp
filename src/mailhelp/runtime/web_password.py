"""Local password hashes; codes and passwords create the same revocable sessions."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from ..storage import JsonStore


class PasswordState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(default=0, ge=0)
    salt: str = Field(default="", pattern=r"^(?:[a-f0-9]{32})?$")
    digest: str = Field(default="", pattern=r"^(?:[a-f0-9]{64})?$")


def password_digest(password: str, salt: str) -> str:
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32).hex()


class WebPassword:
    def __init__(self, store: JsonStore):
        self.store = store

    def state(self) -> PasswordState:
        return self.store.load_model("web-password", PasswordState, PasswordState())

    def verify(self, password: str) -> bool:
        state = self.state()
        # Bound work even for hostile login forms; do not call scrypt on unbounded input.
        if not state.digest or not 1 <= len(password) <= 1024:
            return False
        return hmac.compare_digest(state.digest, password_digest(password, state.salt))

    def set(self, password: str, version: int, authorize: Callable[[], bool] = lambda: True) -> None:
        if not 12 <= len(password) <= 1024 or any(ord(char) < 32 for char in password):
            raise ValueError("Passwort benötigt 12 bis 1024 Zeichen ohne Steuerzeichen.")
        salt = secrets.token_hex(16)
        digest = password_digest(password, salt)
        with self.store.locked():
            if not authorize():
                raise PermissionError("Sitzung abgelaufen.")
            if self.state().version != version:
                raise ValueError("Passwort inzwischen geändert; Seite neu laden.")
            self.store.save("web-password", PasswordState(version=version + 1, salt=salt,
                                                         digest=digest).model_dump())

    def reset(self) -> None:
        """Host-only recovery; all web sessions are revoked along with the password."""
        with self.store.locked():
            self.store.save("web-password", PasswordState(version=self.state().version + 1).model_dump())
            self.store.save("web-sessions", {"schema_version": 1, "sessions": []})
