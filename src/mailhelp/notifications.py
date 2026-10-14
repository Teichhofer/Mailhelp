"""Durable, content-free delivery records and one shared background policy."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from .adapter import PermanentError, RetryableError
from .notification_config import Category, effective_profile

PENDING = {"pending", "deferred", "failed"}
TERMINAL = {"sent", "uncertain", "cancelled"}
STATE = "notification-queue"
DeliveryStatus = Literal["pending", "deferred", "sending", "sent", "failed", "uncertain", "cancelled"]
DeliveryError = Literal["", "retryable", "refused", "unknown", "interrupted", "obsolete"]


class QueueFull(RuntimeError):
    """Keep the producer's marker unchanged so the event can be enqueued later."""


class Delivery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-f0-9]{64}$")
    category: Category
    reference: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9:_-]+$")
    version: int = Field(ge=0)
    channel: Literal["telegram", "web_push"]
    device: str = Field(default="", max_length=100, pattern=r"^[a-f0-9:]*$")
    created_at: datetime
    due_at: datetime
    updated_at: datetime
    status: DeliveryStatus = "pending"
    attempts: int = Field(default=0, ge=0)
    error: DeliveryError = ""
    mailbox_id: int = Field(default=1, ge=1, le=99)


class NotificationQueue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    entries: dict[str, Delivery] = Field(default_factory=dict)


def waiting(item: Delivery, max_attempts: int) -> bool:
    return (item.status in PENDING and item.attempts < max_attempts
            and item.error not in {"refused", "unknown", "interrupted"})


def quiet_now(profile, zone: str, now: datetime, category: str) -> bool:
    quiet = profile.quiet_hours
    if not quiet.enabled or (category == "system_errors" and quiet.allow_system_errors):
        return False
    local = now.astimezone(ZoneInfo(zone)).strftime("%H:%M")
    if quiet.start < quiet.end:
        return quiet.start <= local < quiet.end
    return local >= quiet.start or local < quiet.end


class NotificationService:
    def __init__(self, store, settings, destinations, relevant, sender,
                 clock=lambda: datetime.now(UTC), logger=None, settings_for_mailbox=None):
        self.store, self.settings, self.destinations = store, settings, destinations
        self.relevant, self.sender, self.clock, self.logger = relevant, sender, clock, logger
        self._runner = Lock()
        self.settings_for_mailbox = settings_for_mailbox

    def configuration(self, number):
        return self.settings() if self.settings_for_mailbox is None else self.settings_for_mailbox(number)

    def destination_list(self, category, number):
        return self.destinations(category) if self.settings_for_mailbox is None else self.destinations(category, number)

    def state(self) -> NotificationQueue:
        return self.store.load_model(STATE, NotificationQueue, NotificationQueue())

    def _save(self, state: NotificationQueue) -> None:
        self.store.save(STATE, state.model_dump(mode="json"))

    def enqueue(
        self, category: Category, reference: str, version: int = 0, *, exclude_channels=(), mailbox_id=1
    ) -> None:
        """No text, endpoints or authorization is copied into a delivery record."""
        settings, now = self.configuration(mailbox_id), self.clock()
        profile = effective_profile(settings)
        with self.store.locked():
            state = self.state()
            pending = sum(waiting(item, profile.delivery.max_attempts) for item in state.entries.values())
            additions = []
            for channel, device in self.destination_list(category, mailbox_id):
                if channel in exclude_channels:
                    continue
                scoped = "" if mailbox_id == 1 else f":mailbox:{mailbox_id}"
                identity = hashlib.sha256(
                    f"{category}:{reference}:{version}:{channel}:{device}{scoped}".encode()
                ).hexdigest()
                if identity in state.entries or any(
                    (item.category, item.reference, item.version, item.channel, item.device, item.mailbox_id)
                    == (category, reference, version, channel, device, mailbox_id) for item in state.entries.values()):
                    continue
                group = [item for item in state.entries.values() if waiting(item, profile.delivery.max_attempts)
                         and (item.category, item.channel, item.device, item.mailbox_id)
                         == (category, channel, device, mailbox_id)]
                delay = profile.batching.window_seconds if profile.batching.enabled else 0
                due = min((item.due_at for item in group), default=now + timedelta(seconds=delay))
                addition = Delivery(id=identity, category=category, reference=reference, version=version,
                    channel=channel, device=device, created_at=now, due_at=due, updated_at=now, mailbox_id=mailbox_id)
                if category == "daily_briefing" and ":" in reference:
                    old = next((item for item in state.entries.values()
                        if (item.category, item.reference, item.channel, item.device)
                        == (category, reference.split(":", 1)[0], channel, device)
                        and item.status in {"sent", "uncertain", "sending"}), None)
                    if old is not None:
                        addition.status = "uncertain" if old.status == "sending" else old.status
                additions.append(addition)
            available = max(0, profile.delivery.max_pending - pending)
            state.entries.update((item.id, item) for item in additions[:available])
            self._save(state)
            if len(additions) > available:
                raise QueueFull("Benachrichtigungswarteschlange voll; Ereignis bleibt an der Quelle erhalten")

    def tick(self) -> None:
        if not self._runner.acquire(blocking=False):
            return
        try:
            self._tick()
        finally:
            self._runner.release()

    def _tick(self) -> None:
        now, settings = self.clock(), self.settings()
        profile = effective_profile(settings)
        with self.store.locked():
            state = self.state()
            groups: dict[tuple[str, str, str, int], list[Delivery]] = {}
            for item in list(state.entries.values()):
                settings = self.configuration(item.mailbox_id)
                profile = effective_profile(settings)
                if item.status == "sending":
                    # Neither Telegram nor browser push offers a reliable receipt lookup.
                    item.status, item.error, item.updated_at = "uncertain", "interrupted", now
                if item.status in TERMINAL or not waiting(item, profile.delivery.max_attempts):
                    if item.status in PENDING:
                        item.status = "failed"
                    if (item.updated_at < now - timedelta(days=profile.delivery.history_days)
                            and not self.relevant(item)):
                        del state.entries[item.id]
                    continue
                if ((item.channel, item.device) not in self.destination_list(item.category, item.mailbox_id)
                        or not self.relevant(item)):
                    item.status, item.error, item.updated_at = "cancelled", "obsolete", now
                    continue
                if quiet_now(profile, settings.timezone, now, item.category):
                    item.status, item.updated_at = "deferred", now
                    continue
                if item.status == "deferred" or item.due_at <= now:
                    groups.setdefault((item.category, item.channel, item.device, item.mailbox_id), []).append(item)
            self._save(state)
        for items in groups.values():
            self._deliver(items)

    def _deliver(self, candidates: list[Delivery]) -> None:
        now, settings = self.clock(), self.configuration(candidates[0].mailbox_id)
        profile = effective_profile(settings)
        with self.store.locked():
            state = self.state()
            items = []
            for candidate in candidates:
                item = state.entries[candidate.id]
                if not waiting(item, profile.delivery.max_attempts):
                    item.status = "failed"
                    continue
                if ((item.channel, item.device) not in self.destination_list(item.category, item.mailbox_id)
                        or not self.relevant(item)):
                    item.status, item.error, item.updated_at = "cancelled", "obsolete", now
                    continue
                if quiet_now(profile, settings.timezone, now, item.category):
                    item.status, item.updated_at = "deferred", now
                    continue
                item.status, item.updated_at = "sending", now
                item.attempts += 1
                items.append(item)
            self._save(state)
        if not items:
            return
        status: DeliveryStatus = "sent"
        error: DeliveryError = ""
        try:
            self.sender(items, profile)
        except RetryableError:
            status, error = "failed", "retryable"
        except PermanentError:
            status, error = "failed", "refused"
        except Exception:
            status, error = "uncertain", "unknown"
        with self.store.locked():
            state = self.state()
            for sent in items:
                item = state.entries[sent.id]
                item.status, item.error, item.updated_at = status, error, self.clock()
                if error == "refused":
                    item.attempts = profile.delivery.max_attempts
                backoff = min(profile.delivery.max_backoff_seconds,
                              profile.delivery.initial_backoff_seconds * 2 ** (item.attempts - 1))
                item.due_at = item.updated_at + timedelta(seconds=backoff)
            self._save(state)
        if self.logger is not None:
            self.logger.event("INFO", "notifications", "delivery_result", category=items[0].category,
                              channel=items[0].channel, count=len(items), status=status, error_code=error)
