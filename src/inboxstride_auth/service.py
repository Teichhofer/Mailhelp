"""Sign-in flow of the central OAuth service (Planung 8.0, sections 4 and 6).

Start, Google's return and the local completion are three separate steps. Google's code is
exchanged exactly once; the browser only ever carries a short one-time receipt back to the
instance that started the sign-in. A new access becomes active only after the instance confirmed
it with the original local session; until then the previous access stays untouched.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlencode

from pydantic import ValidationError

from .google import ClientRefused, GoogleTokens, GrantRefused, TemporaryFailure, UnclearResult, authorization_url
from .models import (
    JOB_LIFETIME,
    RECEIPT_LIFETIME,
    SCOPES,
    TERMINAL,
    TRANSITIONS,
    AuthJob,
    AuthState,
    Connection,
    Instance,
)
from .secret_store import SecretStore
from .state_file import StateFile

REFRESH_MARGIN = 60


class Refused(RuntimeError):
    """A request that must not change anything; ``code`` is a safe, content-free reason."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def register_instance(states: StateFile, instance: Instance) -> None:
    """Only the operator registers an instance; its host is the only return address."""
    def change(state: AuthState) -> AuthState:
        if any(other.host == instance.host and other.id != instance.id for other in state.instances.values()):
            raise Refused("host_taken")
        return state.model_copy(update={"instances": {**state.instances, instance.id: instance}})
    states.update(change)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")


class AuthService:
    def __init__(self, state: StateFile, store: SecretStore, google: GoogleTokens,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 token: Callable[[int], str] = secrets.token_urlsafe,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self.state, self.store, self.google = state, store, google
        self.clock, self.token, self.monotonic = clock, token, monotonic
        # Short-lived access tokens only in memory, per connection: (token, valid until monotonic).
        self._tokens: dict[str, tuple[str, float]] = {}

    # Operator ------------------------------------------------------------------------------

    def register(self, instance: Instance) -> None:
        register_instance(self.state, instance)

    # Start ---------------------------------------------------------------------------------

    def start(self, instance_id: str, session: str, target: str,
              operation: Literal["connect", "reauthorize", "replace"], key: str) -> tuple[AuthJob, str]:
        """A new sign-in, or the same one again for the same idempotency key, and its Google URL."""
        now = self.clock()
        state = self.state.read()
        instance = state.instances.get(instance_id)
        if instance is None or not instance.enabled:
            raise Refused("unknown_instance")
        job_id = digest(f"{instance_id}\n{key}")[:32]
        existing = state.jobs.get(job_id)
        if existing is not None and (existing.session, existing.target, existing.operation) != (
                digest(session), target, operation):
            raise Refused("key_reused")
        if existing is not None and existing.state != "awaiting_google":
            raise Refused("job_not_open")
        verifier, oauth_state = self.token(48), self.token(32)
        if existing is None:
            job = AuthJob(id=job_id, instance=instance_id, session=digest(session), target=target,
                          operation=operation, client_revision=state.client_revision, created=now,
                          expires=now + JOB_LIFETIME).advance("awaiting_google", now, state_hash=digest(oauth_state))
        else:
            # A repeated start (for example after a crash) gets a fresh state; the old one stops working.
            job = AuthJob.model_validate({**existing.model_dump(), "state_hash": digest(oauth_state),
                                          "version": existing.version + 1})
        self.store.put(f"pkce:{job.id}", verifier)

        def change(current: AuthState) -> AuthState:
            jobs = dict(current.jobs)
            for other in current.jobs.values():
                # A newly started sign-in for the same target makes older open ones stale.
                if (other.instance, other.target) == (instance_id, target) and other.id != job.id \
                        and other.state not in TERMINAL and other.state != "activating":
                    jobs[other.id] = (other.advance("cancelled", now) if "cancelled" in TRANSITIONS[other.state]
                                      else other)
            jobs[job.id] = job
            return current.model_copy(update={"jobs": jobs})
        self.state.update(change)
        client = self.google.client
        return job, authorization_url(client, oauth_state, _challenge(verifier), SCOPES)

    # Google's return ----------------------------------------------------------------------------

    def callback(self, oauth_state: str, code: str | None, error: str | None) -> str:
        """Exchange the code once and send the browser to its instance with a one-time receipt."""
        now = self.clock()
        state = self.state.read()
        job = next((item for item in state.jobs.values() if item.state_hash == digest(oauth_state)), None)
        if job is None:
            raise Refused("unknown_state")
        instance = state.instances[job.instance]
        if job.state != "awaiting_google":
            raise Refused("state_used")
        if now >= job.expires:
            self._end(job, "expired", now)
            raise Refused("expired")
        if error is not None or not code:
            self._end(job, "cancelled" if error == "access_denied" else "failed", now,
                      "access_denied" if error == "access_denied" else "provider_error")
            return f"{instance.return_url}?{urlencode({'abbruch': '1'})}"
        self._save_job(job.advance("exchanging", now))
        verifier = self.store.get(f"pkce:{job.id}")
        self.store.delete(f"pkce:{job.id}")
        try:
            answer = self.google.exchange(code, verifier or "")
        except (UnclearResult, ClientRefused, GrantRefused) as exc:
            reason = {UnclearResult: "exchange_unclear", ClientRefused: "client_refused",
                      GrantRefused: "grant_refused"}[type(exc)]
            self._end(self._current(job.id), "failed", now, reason)
            return f"{instance.return_url}?{urlencode({'abbruch': '1'})}"
        connection_id = digest(f"{job.id}:candidate")[:32]
        try:
            if answer.refresh_token is None:
                raise Refused("no_refresh_token")
            connection = Connection(id=connection_id, instance=job.instance, target=job.target, status="candidate",
                                    generation=1, scopes=tuple(answer.scope.split()),
                                    secret=f"refresh:{connection_id}", client_revision=job.client_revision,
                                    created=now)
        except (Refused, ValidationError) as exc:
            self._end(self._current(job.id), "failed", now,
                      exc.code if isinstance(exc, Refused) else "missing_scopes")
            return f"{instance.return_url}?{urlencode({'abbruch': '1'})}"
        self.store.put(connection.secret, answer.refresh_token)
        receipt = self.token(32)
        ready = self._current(job.id).advance(
            "candidate_ready", now, candidate=connection.id, receipt_hash=digest(receipt),
            receipt_expires=min(now + RECEIPT_LIFETIME, job.expires))

        def change(current: AuthState) -> AuthState:
            return current.model_copy(update={"jobs": {**current.jobs, ready.id: ready},
                                              "connections": {**current.connections, connection.id: connection}})
        self.state.update(change)
        self._tokens[connection.id] = (answer.access_token, self.monotonic() + answer.expires_in - REFRESH_MARGIN)
        return f"{instance.return_url}?{urlencode({'beleg': receipt})}"

    # Local completion ----------------------------------------------------------------------------

    def redeem(self, instance_id: str, session: str, receipt: str) -> AuthJob:
        """The instance proves the original session; the receipt works once and only briefly."""
        now = self.clock()
        state = self.state.read()
        job = next((item for item in state.jobs.values() if item.receipt_hash == digest(receipt)), None)
        if job is None or job.instance != instance_id or job.session != digest(session):
            raise Refused("unknown_receipt")
        if job.receipt_expires is None or now >= job.receipt_expires or job.state != "candidate_ready":
            raise Refused("receipt_expired")
        redeemed = job.advance("awaiting_local_confirmation", now, receipt_hash=None, receipt_expires=None)
        self._save_job(redeemed)
        return redeemed

    def activate(self, instance_id: str, session: str, job_id: str, version: int) -> Connection:
        """Make the confirmed candidate the active access of its target, replacing the previous one."""
        now = self.clock()
        job = self.state.read().jobs.get(job_id)
        if job is None or job.instance != instance_id or job.session != digest(session):
            raise Refused("unknown_job")
        if job.state != "awaiting_local_confirmation" or job.version != version:
            raise Refused("job_changed")
        self._save_job(job.advance("activating", now))
        return self.resume(job_id)

    def resume(self, job_id: str) -> Connection:
        """Finish an activation; after a crash it is repeated without a second effect."""
        now = self.clock()
        replaced: list[str] = []

        def change(current: AuthState) -> AuthState:
            job = current.jobs[job_id]
            assert job.candidate is not None  # validated for this state
            candidate = current.connections[job.candidate]
            if job.state == "active":
                return current
            connections = dict(current.connections)
            previous = [item for item in connections.values() if (item.instance, item.target) == (
                job.instance, job.target) and item.status in {"active", "reconnect_required"}]
            for item in previous:
                connections[item.id] = item.model_copy(update={"status": "disconnected"})
                replaced.append(item.secret)
            generation = max((item.generation for item in previous), default=0) + 1
            connections[candidate.id] = candidate.model_copy(update={"status": "active", "generation": generation})
            return current.model_copy(update={"connections": connections,
                                              "jobs": {**current.jobs, job_id: job.advance("active", now)}})
        state = self.state.update(change)
        for secret in replaced:
            self.store.delete(secret)
            self._tokens.pop(secret.removeprefix("refresh:"), None)
        connection_id = state.jobs[job_id].candidate
        assert connection_id is not None
        return state.connections[connection_id]

    # Tokens ------------------------------------------------------------------------------------

    def access_token(self, instance_id: str, connection_id: str) -> tuple[str, int]:
        """(access token, seconds valid) for a candidate or active access of exactly this instance."""
        connection = self.state.read().connections.get(connection_id)
        if connection is None or connection.instance != instance_id:
            raise Refused("unknown_connection")
        if connection.status not in {"candidate", "active"}:
            raise Refused(connection.status)
        cached = self._tokens.get(connection_id)
        if cached is not None and cached[1] > self.monotonic():
            return cached[0], int(cached[1] - self.monotonic())
        refresh = self.store.get(connection.secret)
        if refresh is None:
            raise Refused("reconnect_required")
        try:
            answer = self.google.refresh(refresh)
        except GrantRefused:
            self._mark(connection_id, "reconnect_required")
            raise Refused("reconnect_required") from None
        except ClientRefused:
            raise Refused("client_refused") from None
        except TemporaryFailure:
            raise Refused("temporarily_unavailable") from None
        if answer.refresh_token is not None:
            self.store.put(connection.secret, answer.refresh_token)  # rotation; a missing one keeps the old
        valid = answer.expires_in - REFRESH_MARGIN
        self._tokens[connection_id] = (answer.access_token, self.monotonic() + valid)
        return answer.access_token, valid

    def disconnect(self, instance_id: str, connection_id: str) -> None:
        """Stop issuing tokens for this access; Google's grant itself is not revoked."""
        connection = self.state.read().connections.get(connection_id)
        if connection is None or connection.instance != instance_id:
            raise Refused("unknown_connection")
        self._mark(connection_id, "disconnected")
        self.store.delete(connection.secret)
        self._tokens.pop(connection_id, None)

    # Housekeeping ----------------------------------------------------------------------------------

    def sweep(self) -> int:
        """End expired jobs and drop the secrets of candidates that will never become active."""
        now = self.clock()
        ended = 0
        for job in list(self.state.read().jobs.values()):
            if job.state in {"registered", "awaiting_google", "candidate_ready",
                             "awaiting_local_confirmation"} and now >= job.expires:
                self._end(job, "expired", now)
                ended += 1
        state = self.state.read()
        for job in state.jobs.values():
            if job.state in {"expired", "cancelled", "failed"}:
                self.store.delete(f"pkce:{job.id}")
                candidate = state.connections.get(job.candidate or "")
                if candidate is not None and candidate.status == "candidate":
                    self.store.delete(candidate.secret)
                    self._mark(candidate.id, "disconnected")
        return ended

    def _end(self, job: AuthJob, final: Literal["expired", "cancelled", "failed"], now: datetime,
             error: str | None = None) -> None:
        self._save_job(job.advance(final, now, error=error, receipt_hash=None, receipt_expires=None))
        self.store.delete(f"pkce:{job.id}")

    def _current(self, job_id: str) -> AuthJob:
        return self.state.read().jobs[job_id]

    def _save_job(self, job: AuthJob) -> None:
        def change(current: AuthState) -> AuthState:
            return current.model_copy(update={"jobs": {**current.jobs, job.id: job}})
        self.state.update(change)

    def _mark(self, connection_id: str, status: Literal["reconnect_required", "disconnected"]) -> None:
        def change(current: AuthState) -> AuthState:
            item = current.connections[connection_id]
            return current.model_copy(update={
                "connections": {**current.connections, connection_id: item.model_copy(update={"status": status})}})
        self.state.update(change)


__all__ = ["REFRESH_MARGIN", "AuthService", "Refused", "digest", "register_instance"]
