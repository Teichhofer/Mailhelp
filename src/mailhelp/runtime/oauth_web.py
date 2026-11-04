"""Session-bound browser OAuth with durable device jobs and guarded local token commits."""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Literal
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings
from ..config.loader import _dotenv
from ..external.microsoft import DEVICE_GRANT, SCOPES, DeviceCodeResponse, MicrosoftTokenResponse, TokenFile
from ..mailbox.mailbox_settings import target_profiles
from ..proposals.target_profiles import secret_name
from ..storage import JsonStore, atomic_replace
from .env_file import file_hash, set_values

GOOGLE_SCOPES = ("https://www.googleapis.com/auth/calendar.events "
                 "https://www.googleapis.com/auth/calendar.calendars.readonly "
                 "https://www.googleapis.com/auth/calendar.calendarlist.readonly")


@dataclass(frozen=True)
class OAuthConfig:
    client_id: str
    client_secret: str
    tenant: str
    redirect: str


def oauth_config(settings: Settings, env: dict[str, str], profile: int, provider: str) -> OAuthConfig:
    target = target_profiles(settings)[profile]
    prefix = "GOOGLE_OAUTH" if provider == "google" else "MICROSOFT"

    def value(suffix: str) -> str:
        base = f"{prefix}_{suffix}"
        return env.get(secret_name(base, profile), env.get(base, "")) if profile != 1 else env.get(base, "")

    return OAuthConfig(value("CLIENT_ID"), value("CLIENT_SECRET"), target.microsoft_tenant,
                       settings.web.google_redirect_uri)


class OAuthJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    actor: str
    provider: Literal["google", "microsoft"]
    profile: int = Field(ge=1, le=99)
    key: str
    binding: str
    env_revision: str
    status: str = "starting"
    expires: float
    next_poll: float = 0
    interval: int = 5
    verifier: str = ""
    device_code: str = ""
    user_code: str = ""
    uri: str = ""
    token: str = ""


class OAuthJobs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    jobs: list[OAuthJob] = Field(default_factory=list, max_length=100)


class BrowserOAuth:
    def __init__(self, directory: Path, store: JsonStore, authorize: Callable[[str], bool],
                 config: Callable[[int, str], OAuthConfig], sign: Callable[[str], str], *,
                 transport: httpx.BaseTransport | None = None, clock: Callable[[], float] = time.time,
                 stopped: Event | None = None, changed: Callable[[str], None] = lambda actor: None):
        self.directory, self.store, self.authorize, self.config, self.sign = directory, store, authorize, config, sign
        self.transport, self.clock = transport, clock
        self.changed = changed
        self.stopped, self.wake = stopped or Event(), Event()
        self.lock = RLock()
        self.thread: Thread | None = None

    def state(self) -> OAuthJobs:
        return self.store.load_model("web-oauth", OAuthJobs, OAuthJobs())

    def _save(self, state: OAuthJobs) -> None:
        # mkstemp creates owner-only files before any verifier/device secret is written.
        atomic_replace(self.store.directory / "web-oauth.json", state.model_dump_json(indent=2) + "\n")

    def _binding(self, cfg: OAuthConfig) -> str:
        return self.sign(json.dumps([cfg.client_id, cfg.client_secret, cfg.tenant, cfg.redirect]))

    def _authorized(self, job: OAuthJob) -> OAuthConfig:
        cfg = self.config(job.profile, job.provider)
        if not self.authorize(job.actor) or self._binding(cfg) != job.binding:
            raise PermissionError("Sitzung oder OAuth-Konfiguration geändert.")
        return cfg

    def job(self, identity: str, actor: str) -> OAuthJob:
        job = next((job for job in self.state().jobs if job.id == identity and job.actor == actor), None)
        if job is None or not self.authorize(actor):
            raise PermissionError("Anmeldung nicht verfügbar.")
        return job

    def revision(self, profile: int, provider: str) -> str:
        return self.sign(self._binding(self.config(profile, provider)) + file_hash(self.directory / ".env"))

    def start(self, provider: Literal["google", "microsoft"], actor: str, profile: int, key: str,
              revision: str) -> OAuthJob:
        if not self.authorize(actor) or not 8 <= len(key) <= 80:
            raise PermissionError("Anfrage nicht autorisiert.")
        cfg = self.config(profile, provider)
        if not cfg.client_id or provider == "google" and not cfg.client_secret:
            raise ValueError("OAuth-Clientdaten zuerst hinterlegen.")
        with self.lock, self.store.locked():
            state = self.state()
            previous = next((j for j in state.jobs if j.actor == actor and j.key == key), None)
            if previous is not None:
                if (previous.provider, previous.profile) != (provider, profile):
                    raise ValueError("Idempotenzkonflikt.")
                return previous
            if self.revision(profile, provider) != revision:
                raise ValueError("OAuth-Eingaben inzwischen geändert.")
            state.jobs = [j for j in state.jobs if j.status not in {"done", "failed", "expired", "blocked"}]
            if len(state.jobs) >= 100:
                raise ValueError("Zu viele offene Anmeldungen.")
            job = OAuthJob(id=secrets.token_hex(32), actor=actor, provider=provider, profile=profile, key=key,
                binding=self._binding(cfg), env_revision=file_hash(self.directory / ".env"),
                expires=self.clock() + 600, verifier=secrets.token_urlsafe(48))
            if provider == "google":
                job.status = "pending"
                challenge = base64.urlsafe_b64encode(
                    hashlib.sha256(job.verifier.encode()).digest()).decode().rstrip("=")
                job.uri = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
                    "client_id": cfg.client_id, "redirect_uri": cfg.redirect, "response_type": "code",
                    "scope": GOOGLE_SCOPES, "access_type": "offline", "prompt": "consent", "state": job.id,
                    "code_challenge": challenge, "code_challenge_method": "S256"})
            state.jobs.append(job)
            self._save(state)
        self.wake.set()
        return job

    def _request(self, url: str, data: dict[str, str]) -> httpx.Response:
        with httpx.Client(transport=self.transport, timeout=15, follow_redirects=False, trust_env=False) as client:
            return client.post(url, data=data)

    def _update(self, job: OAuthJob) -> None:
        with self.store.locked():
            state = self.state()
            state.jobs = [job if j.id == job.id else j for j in state.jobs]
            self._save(state)

    def _finish(self, job: OAuthJob) -> None:
        self._authorized(job)
        if self.clock() >= job.expires:
            raise ValueError("Anmeldung abgelaufen.")
        env = _dotenv(self.directory / ".env")
        base = "GOOGLE_OAUTH_REFRESH_TOKEN" if job.provider == "google" else "MICROSOFT_REFRESH_TOKEN"
        name = base if job.profile == 1 else secret_name(base, job.profile)
        with self.store.locked():
            self._authorized(job)
            if env.get(name) != job.token:
                set_values(self.directory / ".env", {name: job.token}, job.env_revision)
            if job.provider == "microsoft":
                path = "microsoft-token.json" if job.profile == 1 else f"microsoft-token-{job.profile}.json"
                TokenFile(self.directory / path).save(job.token)
            self.changed(job.actor)
            self._terminal(job, "done")

    def _terminal(self, job: OAuthJob, status: str) -> None:
        job.status = status
        job.token = job.device_code = job.verifier = job.uri = ""
        self._update(job)

    def google_callback(self, identity: str, actor: str, code: str) -> OAuthJob:
        with self.lock:
            job = self.job(identity, actor)
            if job.provider != "google":
                raise ValueError("Falscher Anmeldeweg.")
            if job.status == "done":
                return job
            if job.status != "pending" or self.clock() >= job.expires or not 1 <= len(code) <= 4096:
                raise ValueError("Anmeldung abgelaufen oder bereits verarbeitet.")
            cfg = self._authorized(job)
            job.status = "exchanging"
            self._update(job)
            try:
                response = self._request("https://oauth2.googleapis.com/token", {
                    "client_id": cfg.client_id, "client_secret": cfg.client_secret, "code": code,
                    "redirect_uri": cfg.redirect, "grant_type": "authorization_code", "code_verifier": job.verifier})
                response.raise_for_status()
                token = response.json()["refresh_token"]
                if not isinstance(token, str) or not token:
                    raise ValueError("Refresh-Token fehlt.")
                job.status, job.token = "committing", token
                self._update(job)
                self._finish(job)
            except (httpx.HTTPError, ValueError, KeyError, PermissionError):
                self._terminal(job, "failed")
            return job

    def tick(self, identity: str) -> None:
        with self.lock:
            job = next(j for j in self.state().jobs if j.id == identity)
            if job.status not in {"starting", "pending", "committing", "exchanging"}:
                return
            try:
                cfg = self._authorized(job)
                if self.clock() >= job.expires:
                    self._terminal(job, "expired")
                elif job.status == "committing":
                    self._finish(job)
                elif job.status == "exchanging":
                    # A consumed authorization code must never be exchanged a second time after a crash.
                    self._terminal(job, "failed")
                elif job.provider == "microsoft" and self.clock() >= job.next_poll:
                    self._microsoft(job, cfg)
            except PermissionError:
                self._terminal(job, "blocked")
            except (httpx.HTTPError, ValueError, KeyError):
                self._terminal(job, "failed")

    def _microsoft(self, job: OAuthJob, cfg: OAuthConfig) -> None:
        base = f"https://login.microsoftonline.com/{cfg.tenant}/oauth2/v2.0"
        if job.status == "starting":
            response = self._request(base + "/devicecode", {"client_id": cfg.client_id, "scope": SCOPES})
            response.raise_for_status()
            device = DeviceCodeResponse.model_validate(response.json())
            job.device_code, job.user_code, job.uri = device.device_code, device.user_code, device.verification_uri
            # Never render a provider-controlled link to an arbitrary host.
            if job.uri not in {"https://microsoft.com/devicelogin", "https://www.microsoft.com/link",
                               "https://login.microsoftonline.com/common/oauth2/deviceauth"}:
                raise ValueError("Unerwartete Anmeldeadresse.")
            job.expires, job.interval, job.status = self.clock() + device.expires_in, device.interval, "pending"
        else:
            data = {"client_id": cfg.client_id, "grant_type": DEVICE_GRANT, "device_code": job.device_code}
            if cfg.client_secret:
                data["client_secret"] = cfg.client_secret
            response = self._request(base + "/token", data)
            if response.status_code == 200:
                token = MicrosoftTokenResponse.model_validate(response.json())
                if not token.refresh_token or token.token_type.lower() != "bearer":
                    raise ValueError("Refresh-Token fehlt.")
                job.token, job.status = token.refresh_token, "committing"
                self._update(job)
                self._finish(job)
                return
            error = response.json()["error"]
            if error not in {"authorization_pending", "slow_down"}:
                raise ValueError("Microsoft-Anmeldung abgelehnt.")
            if error == "slow_down":
                job.interval += 5
        self._authorized(job)
        job.next_poll = self.clock() + job.interval
        self._update(job)

    def run(self) -> None:
        while not self.stopped.is_set():
            for job in self.state().jobs:
                self.tick(job.id)
            self.wake.wait(0.5)
            self.wake.clear()

    def start_worker(self) -> Thread:
        thread = Thread(target=self.run, name="browser-oauth", daemon=True)
        thread.start()
        self.thread = thread
        return thread

    def stop(self) -> None:
        self.stopped.set()
        self.wake.set()
        if self.thread is not None:
            self.thread.join(timeout=20)
