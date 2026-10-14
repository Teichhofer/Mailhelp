"""Provider credentials and adapter lifetime for stable target profile numbers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import SecretStr

from .config import Secrets, Settings, provider_secret_names
from .external.contracts import ExternalUnavailable, TargetWriter
from .external.providers import Writers, build_writers
from .external.roles import profile_slot
from .logging import redact
from .mailbox_settings import active_profiles, target_profiles

PROVIDER_FIELDS = (
    "todoist_token",
    "todoist_client_id",
    "todoist_client_secret",
    "google_oauth_client_id",
    "google_oauth_client_secret",
    "google_oauth_refresh_token",
    "caldav_username",
    "caldav_password",
    "microsoft_client_id",
    "microsoft_client_secret",
    "microsoft_refresh_token",
)


class ProfileLogger:
    """Provider events contain identifiers and error codes, never target URLs or addresses."""

    def __init__(self, logger, secrets, number):
        self.logger, self.secrets, self.number = logger, secrets.known_values(), number

    def event(self, level, module, event, **context):
        def clean(value):
            if isinstance(value, dict):
                return {key: clean(item) for key, item in value.items()}
            if isinstance(value, list):
                return [clean(item) for item in value]
            if isinstance(value, str):
                return re.sub(r"https?://[^\s]+|[^\s<>]+@[^\s<>]+", "[privat]", value)
            return value

        self.logger.event(level, module, event, profile=self.number, **clean(redact(context, self.secrets)))


def secret_name(name: str, number: int) -> str:
    prefix = "GOOGLE_OAUTH" if name.startswith("GOOGLE_OAUTH_") else name.split("_", 1)[0]
    return f"{prefix}_{number}{name[len(prefix) :]}"


def load_profile_secrets(settings: Settings, env: dict[str, str]):
    profiles, missing = {}, []
    required_profiles = set(active_profiles(settings))
    for number, targets in target_profiles(settings).items():
        if number == 1:
            continue
        required = provider_secret_names(targets)
        values = {}
        for name in (field.upper() for field in PROVIDER_FIELDS):
            key = secret_name(name, number)
            value = env.get(key, "")
            if not value and name.endswith(("_CLIENT_ID", "_CLIENT_SECRET")):
                value = env.get(name, "")
            if value:
                values[name.lower()] = value
            elif name in required and number in required_profiles:
                missing.append(key)
        profiles[number] = values
    return profiles, missing


def profile_secrets(secrets: Secrets, number: int) -> Secrets:
    if number == 1:
        return secrets
    if number not in secrets.profiles:
        raise LookupError("Geheimnisse des Zielprofils fehlen")
    values = {name: SecretStr("") for name in PROVIDER_FIELDS}
    values.update(secrets.profiles[number])
    return secrets.model_copy(update=values)


class UnavailableWriter(TargetWriter):
    def __init__(self, role, target, number):
        self.role, self.target, self.target_profile = role, target, number
        self.service, self.label = "unavailable", "Zielprofil nicht verfügbar"

    def check_access(self):
        raise ExternalUnavailable("Zielprofil nicht verfügbar")

    def reconcile(self, key):
        self.check_access()

    def prepare(self, proposal, key):
        self.check_access()

    def close(self):
        pass

    def fetch_events_in_window(self, start, end, *, strict=False):
        self.check_access()

    def fetch_active_tasks(self, *, strict=False):
        self.check_access()


@dataclass
class ProfileWriters:
    profiles: dict[int, Writers]
    default_profile: int = 1

    @property
    def slots(self):
        return {
            profile_slot(role, number): writer
            for number, pair in self.profiles.items()
            for role, writer in pair.slots.items()
        }

    @property
    def first(self):
        return self.profiles[self.default_profile]

    @property
    def calendar(self):
        return self.first.calendar

    @property
    def tasks(self):
        return self.first.tasks

    def close(self):
        for pair in self.profiles.values():
            pair.close()


def build_profile_writers(settings, secrets, directory, **kwargs):
    pairs = {}
    configured = target_profiles(settings)
    numbers = set(active_profiles(settings)) | {item.id for item in settings.target_profiles}
    for number, targets in configured.items():
        if number not in numbers:
            continue
        cfg = settings.model_copy(update={"targets": targets})
        try:
            credentials = secrets.for_profile(number)
            if any(
                not getattr(credentials, name.lower()).get_secret_value() for name in provider_secret_names(targets)
            ):
                raise LookupError("Geheimnisse des Zielprofils fehlen")
            options = dict(kwargs)
            if options.get("logger") is not None:
                options["logger"] = ProfileLogger(options["logger"], secrets, number)
            pairs[number] = build_writers(cfg, credentials, directory, profile_id=number, **options)
        except Exception as exc:
            logger = kwargs.get("logger")
            if logger is not None:
                logger.event("WARNING", "profiles", "profile_unavailable", profile=number, error=type(exc).__name__)
            pairs[number] = Writers(
                UnavailableWriter("calendar", targets.calendar_target, number),
                UnavailableWriter("tasks", targets.task_target, number),
            )
    return ProfileWriters(pairs, settings.imap.enabled_mailboxes()[0].target_profile)
