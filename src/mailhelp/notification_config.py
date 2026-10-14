"""Validated notification profile; omitted profiles preserve the 2.x choices."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Channel = Literal["telegram", "web_push"]
Category = Literal["decisions", "action_results", "daily_briefing", "system_errors"]
CATEGORIES = ("decisions", "action_results", "daily_briefing", "system_errors")
TIME_PATTERN = r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$"


class ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class QuietHours(ProfileModel):
    enabled: bool = False
    start: str = Field(default="22:00", pattern=TIME_PATTERN)
    end: str = Field(default="07:30", pattern=TIME_PATTERN)
    allow_system_errors: bool = False

    @model_validator(mode="after")
    def distinct_times(self) -> QuietHours:
        if self.enabled and self.start == self.end:
            raise ValueError("Aktive Ruhezeiten benötigen verschiedene Start- und Endzeiten")
        return self


class Batching(ProfileModel):
    enabled: bool = False
    window_seconds: int = Field(default=300, ge=1, le=86400)


class Categories(ProfileModel):
    decisions: list[Channel] = Field(default_factory=list, max_length=2)
    action_results: list[Channel] = Field(default_factory=list, max_length=2)
    daily_briefing: list[Channel] = Field(default_factory=list, max_length=2)
    system_errors: list[Channel] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def unique_channels(self) -> Categories:
        if any(len(getattr(self, name)) != len(set(getattr(self, name))) for name in CATEGORIES):
            raise ValueError("Kanäle dürfen je Kategorie nur einmal vorkommen")
        return self


class DeliverySettings(ProfileModel):
    max_attempts: int = Field(default=3, ge=1, le=10)
    initial_backoff_seconds: int = Field(default=30, ge=1, le=86400)
    max_backoff_seconds: int = Field(default=900, ge=1, le=86400)
    history_days: int = Field(default=30, ge=1, le=3650)
    max_pending: int = Field(default=1000, ge=1, le=100000)

    @model_validator(mode="after")
    def ordered_backoff(self) -> DeliverySettings:
        if self.max_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError("Maximaler Backoff muss mindestens dem anfänglichen Backoff entsprechen")
        return self


class NotificationSettings(ProfileModel):
    quiet_hours: QuietHours = Field(default_factory=QuietHours)
    batching: Batching = Field(default_factory=Batching)
    categories: Categories = Field(default_factory=Categories)
    telegram_content: Literal["neutral", "summary"] = "neutral"
    delivery: DeliverySettings = Field(default_factory=DeliverySettings)


def effective_profile(settings) -> NotificationSettings:
    if settings.notifications is not None:
        return settings.notifications
    telegram: list[Channel] = ["telegram"] if settings.telegram.enabled else []
    push: list[Channel] = ["web_push"] if settings.push.enabled else []
    return NotificationSettings(telegram_content="summary", categories=Categories(
        decisions=telegram + push, action_results=telegram,
        daily_briefing=telegram + push, system_errors=telegram))
