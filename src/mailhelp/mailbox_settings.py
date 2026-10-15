"""Validated, sparse mailbox policies; configuration never comes from mail content."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from pydantic_core import InitErrorDetails

from .config import EventDefaultsSettings, RetentionPeriod, Settings, TargetSettings, Topic
from .notification_config import NotificationSettings, effective_profile


def merge_policy(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in patch.items():
        if value is not None:
            result[key] = merge_policy(result[key], value) if isinstance(value, dict) else value
    return result


def target_profiles(settings: Settings) -> dict[int, TargetSettings]:
    return {1: settings.targets, **{item.id: item for item in settings.target_profiles}}


def active_profiles(settings: Settings) -> dict[int, TargetSettings]:
    ids = {mailbox.target_profile for mailbox in settings.imap.enabled_mailboxes()}
    return {key: value for key, value in target_profiles(settings).items() if key in ids}


def profile_label(settings: Settings, number: int) -> str:
    labels = {1: "Standard", **{item.id: item.label for item in settings.target_profiles}}
    return labels.get(number, "Entferntes Zielprofil")


def effective_settings(settings: Settings, mailbox_id: int) -> Settings:
    mailbox = settings.imap.mailbox(mailbox_id)
    if mailbox is None:
        raise LookupError("Postfach nicht mehr konfiguriert")
    target = target_profiles(settings)[mailbox.target_profile]
    patch: dict[str, Any] = {
        "targets": TargetSettings.model_validate(target.model_dump(exclude={"id", "label"})),
        "notifications": effective_profile(settings),
    }
    for key in ("personal_info", "smart_reply"):
        value = getattr(mailbox, key)
        if value is not None:
            patch[key] = value
    if mailbox.notifications is not None:
        patch["notifications"] = NotificationSettings.model_validate(
            merge_policy(effective_profile(settings).model_dump(), mailbox.notifications.model_dump(exclude_none=True))
        )
    if mailbox.event_defaults is not None:
        patch["event_defaults"] = EventDefaultsSettings.model_validate(
            merge_policy(settings.event_defaults.model_dump(), mailbox.event_defaults.model_dump(exclude_none=True))
        )
    if mailbox.retention is not None:
        patch["retention"] = settings.retention.model_copy(update={"full_mail_days": mailbox.retention.full_mail_days})
    return settings.model_copy(update=patch)


def effective_topics(topics: list[Topic], mailbox_id: int) -> list[Topic]:
    return [item for item in topics if item.mailboxes is None or mailbox_id in item.mailboxes]


def event_defaults_for(settings: Settings, store, proposal, numbers=None):
    from .models import MailState

    mail = store.peek_model("mail-" + proposal.source_mail_id, MailState)
    number = (
        (mail.proposal_policy or {}).get("mailbox_id", (numbers or {}).get(mail.imap.account_id, 1))
        if mail is not None
        else 1
    )
    if isinstance(number, tuple):
        number = number[0]
    return (
        effective_settings(settings, number).event_defaults
        if settings.imap.mailbox(number) is not None
        else settings.event_defaults
    )


def mailbox_fingerprint(settings: Settings, prompts, topics: list[Topic], mailbox_id: int) -> str:
    from .fingerprints import _hash, config_fingerprint

    effective = effective_settings(settings, mailbox_id)
    selected = [topic.model_copy(update={"mailboxes": None}) for topic in effective_topics(topics, mailbox_id)]
    fingerprint = config_fingerprint(effective, prompts, selected)
    mailbox = settings.imap.mailbox(mailbox_id)
    assert mailbox is not None
    if mailbox.event_defaults is not None:
        fingerprint = _hash([fingerprint, effective.event_defaults.model_dump()])
    return fingerprint


def mailbox_topic_policy(settings: Settings, prompts, mailbox_id: int) -> str:
    from .fingerprints import _hash, topic_policy

    cfg = effective_settings(settings, mailbox_id)
    value = topic_policy(cfg, prompts)
    mailbox = settings.imap.mailbox(mailbox_id)
    assert mailbox is not None
    if mailbox.event_defaults is not None:
        value = _hash([value, cfg.event_defaults.model_dump()])
    return value


def _days(period: RetentionPeriod) -> float:
    if period == "disabled":
        return 0
    if period == "unlimited":
        return float("inf")
    return float(period)


def validate_policies(settings: Settings) -> None:
    ids = [item.id for item in settings.target_profiles]
    if len(ids) != len(set(ids)):
        raise ValueError("Zielprofilnummern dürfen nicht doppelt vorkommen")
    profiles = target_profiles(settings)
    for index, mailbox in enumerate(settings.imap.configured_mailboxes()):
        path = ("imap", "mailboxes", index)
        error = None
        key = "target_profile"
        if mailbox.target_profile not in profiles:
            error = "Zielprofil ist nicht konfiguriert"
        elif mailbox.retention is not None:
            local = mailbox.retention.full_mail_days
            global_period = settings.retention.full_mail_days
            if _days(local) > _days(global_period):
                error, key = "Aufbewahrung darf nur kürzer als global sein", "retention"
        if error is not None:
            raise ValidationError.from_exception_data(
                "Settings",
                [{"type": "value_error", "loc": (*path, key), "input": None, "ctx": {"error": ValueError(error)}}],
            )
        try:
            effective_settings(settings, mailbox.id)
        except ValidationError as exc:
            errors: list[InitErrorDetails] = [
                {
                    "type": item["type"],
                    "input": item.get("input"),
                    "ctx": item.get("ctx", {}),
                    "loc": (*path, "notifications", *item["loc"]),
                }
                for item in exc.errors(include_url=False)
            ]
            raise ValidationError.from_exception_data("Settings", errors) from exc
