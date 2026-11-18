"""Readable, versioned state of the central OAuth service (Planung 8.0, sections 3 and 4.2).

Secrets never appear here: refresh tokens, PKCE verifiers and the client secret live in the
encrypted secret store and are referenced by name only. Every time is an absolute UTC instant,
so a restart never prolongs a deadline.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

JOB_LIFETIME = timedelta(minutes=10)
RECEIPT_LIFETIME = timedelta(minutes=2)
RESERVED_SUBDOMAINS = frozenset({"auth", "demo", "www", "api", "mail", "admin"})
SCOPES = ("https://www.googleapis.com/auth/calendar.events",
          "https://www.googleapis.com/auth/calendar.calendars.readonly",
          "https://www.googleapis.com/auth/calendar.calendarlist.readonly")

JobState = Literal["registered", "awaiting_google", "exchanging", "candidate_ready", "awaiting_local_confirmation",
                   "activating", "active", "cancelled", "expired", "failed", "blocked"]
TERMINAL: frozenset[str] = frozenset({"active", "cancelled", "expired", "failed", "blocked"})
# Allowed transitions; anything else is refused, so a job never skips the local confirmation.
TRANSITIONS: dict[str, frozenset[str]] = {
    "registered": frozenset({"awaiting_google", "cancelled", "expired", "blocked"}),
    "awaiting_google": frozenset({"exchanging", "cancelled", "expired", "failed"}),
    "exchanging": frozenset({"candidate_ready", "failed"}),
    "candidate_ready": frozenset({"awaiting_local_confirmation", "cancelled", "expired", "failed"}),
    "awaiting_local_confirmation": frozenset({"activating", "cancelled", "expired"}),
    "activating": frozenset({"active", "failed"}),
}
_ID = r"^[a-z0-9][a-z0-9-]{2,62}$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=False, frozen=True)


class Instance(StrictModel):
    """A Mailhelp instance registered by the operator; nothing else may start a sign-in."""

    id: str = Field(pattern=_ID)
    host: str = Field(min_length=4, max_length=253)
    # SHA-256 of the instance's client certificate (mTLS identity), lower-case hex.
    certificate: str = Field(pattern=r"^[a-f0-9]{64}$")
    enabled: bool = True

    @field_validator("host")
    @classmethod
    def plain_host(cls, value: str) -> str:
        host = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+", host):
            raise ValueError("Nur ein Hostname ohne Schema, Pfad oder Port")
        if host.split(".", 1)[0] in RESERVED_SUBDOMAINS:
            raise ValueError("Reservierte Subdomain")
        return host

    @property
    def return_url(self) -> str:
        """The only place a browser is sent back to: the instance's own completion page."""
        return f"https://{self.host}/einrichtung/google/abschluss"


class AuthJob(StrictModel):
    """One sign-in, bound to instance, session reference, target and client revision."""

    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    instance: str = Field(pattern=_ID)
    # Opaque reference of the local web session; the local session itself never leaves the instance.
    session: str = Field(pattern=r"^[a-f0-9]{64}$")
    target: str = Field(pattern=r"^(profile:[1-9][0-9]?|draft:[a-f0-9]{32})$")
    operation: Literal["connect", "reauthorize", "replace"]
    client_revision: int = Field(ge=1)
    state: JobState = "registered"
    # SHA-256 of the OAuth state parameter; the value itself is only in the Google redirect.
    state_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    receipt_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    receipt_expires: datetime | None = None
    candidate: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    error: str | None = Field(default=None, pattern=r"^[a-z_]{3,40}$")
    created: datetime
    expires: datetime
    version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def consistent(self) -> AuthJob:
        if self.expires - self.created > JOB_LIFETIME:
            raise ValueError("Ein Anmeldeauftrag läuft höchstens 10 Minuten")
        if self.receipt_expires is not None and (self.receipt_expires > self.expires or self.receipt_hash is None):
            raise ValueError("Ein Abschlussbeleg endet spätestens mit seinem Auftrag")
        if self.state in {"candidate_ready", "awaiting_local_confirmation", "activating"} and self.candidate is None:
            raise ValueError("Dieser Zustand braucht einen vorläufigen Zugang")
        return self

    def advance(self, state: JobState, now: datetime, **changes: object) -> AuthJob:
        """The next state; an expired job only ends, a refused step raises."""
        if state not in TRANSITIONS.get(self.state, frozenset()):
            raise ValueError(f"Übergang {self.state} → {state} nicht erlaubt")
        if now >= self.expires and state not in {"expired", "failed", "cancelled"}:
            raise ValueError("Auftrag abgelaufen")
        return AuthJob.model_validate({**self.model_dump(), **changes, "state": state, "version": self.version + 1})


class Connection(StrictModel):
    """A Google access of one instance and profile; candidates and active accesses stay apart."""

    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    instance: str = Field(pattern=_ID)
    # The same binding as the job: a target profile, or a setup draft before config.yaml exists.
    target: str = Field(pattern=r"^(profile:[1-9][0-9]?|draft:[a-f0-9]{32})$")
    status: Literal["candidate", "active", "reconnect_required", "disconnected"]
    generation: int = Field(ge=1)
    scopes: tuple[str, ...]
    # Name of the encrypted refresh token in the secret store.
    secret: str = Field(pattern=r"^refresh:[a-f0-9]{32}$")
    client_revision: int = Field(ge=1)
    created: datetime

    @field_validator("scopes")
    @classmethod
    def required_scopes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        missing = [scope for scope in SCOPES if scope not in value]
        if missing:
            raise ValueError("Erforderliche Kalenderberechtigungen fehlen")
        return tuple(sorted(set(value)))


class AuthState(StrictModel):
    """The whole readable state; ``revision`` is the compare-and-swap counter of every write."""

    schema_version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    client_revision: int = Field(default=1, ge=1)
    instances: dict[str, Instance] = Field(default_factory=dict)
    jobs: dict[str, AuthJob] = Field(default_factory=dict)
    connections: dict[str, Connection] = Field(default_factory=dict)

    @model_validator(mode="after")
    def references(self) -> AuthState:
        keyed: list[tuple[str, str]] = [(key, item.id) for key, item in self.instances.items()]
        keyed += [(key, item.id) for key, item in self.jobs.items()]
        keyed += [(key, item.id) for key, item in self.connections.items()]
        if any(key != ident for key, ident in keyed):
            raise ValueError("Schlüssel und Kennung müssen übereinstimmen")
        owners = [item.instance for item in self.jobs.values()] + [item.instance for item in self.connections.values()]
        if any(owner not in self.instances for owner in owners):
            raise ValueError("Unbekannte Instanz")
        return self


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Zeitpunkte brauchen eine Zeitzone")
    return value.astimezone(UTC)


__all__ = ["JOB_LIFETIME", "RECEIPT_LIFETIME", "RESERVED_SUBDOMAINS", "SCOPES", "TERMINAL", "TRANSITIONS",
           "AuthJob", "AuthState", "Connection", "Instance", "JobState", "utc"]
