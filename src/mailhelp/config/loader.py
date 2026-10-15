"""Loading config.yaml, prompts, topics and secrets from files and the environment."""
from __future__ import annotations

import os
import re
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from .models import (
    ImapSettings,
    IrrelevantTopicsConfig,
    MailboxSettings,
    PromptConfig,
    Secrets,
    Settings,
    TargetSettings,
    Topic,
    TopicsConfig,
)


def read_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: Wurzel muss ein Objekt sein")
    return value


def _dotenv(path: Path) -> dict[str, str]:
    """Read the deliberately small, non-expanding KEY=VALUE .env format."""
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for number, original in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = original.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}: ungültige Zeile {number}")
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError(f"{path}: ungültiger Schlüssel in Zeile {number}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        result[key] = value
    return result


DEFAULT_TOPIC_FILES = ("topics.yaml", "irrelevant_topics.yaml")


def _create_missing_topic_files(directory: Path) -> None:
    """Restore distributed topic files without replacing user configuration."""
    defaults = files("mailhelp").joinpath("defaults")
    for name in DEFAULT_TOPIC_FILES:
        path = directory / name
        if path.exists():
            continue
        content = defaults.joinpath(name).read_text(encoding="utf-8")
        try:
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
        except FileExistsError:
            # A concurrently starting process already restored the file.
            pass


OPTIONAL_PROVIDER_SECRETS = ("MICROSOFT_CLIENT_SECRET", "MICROSOFT_REFRESH_TOKEN")


def provider_secret_names(targets: TargetSettings) -> list[str]:
    """Environment names the configured calendar and task providers require."""
    names = []
    if targets.task_provider == "todoist":
        names += ["TODOIST_TOKEN", "TODOIST_CLIENT_ID", "TODOIST_CLIENT_SECRET"]
    if targets.calendar_provider == "google":
        names += ["GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN"]
    if targets.uses_caldav:
        names += ["CALDAV_USERNAME", "CALDAV_PASSWORD"]
    if targets.uses_microsoft:
        names.append("MICROSOFT_CLIENT_ID")
    return names


# Names of mailbox 1 before 3.1; still accepted when its numbered names are not set.
LEGACY_IMAP_SECRETS = ("IMAP_USERNAME", "IMAP_PASSWORD")


def imap_secret_names(mailbox: MailboxSettings, env: dict[str, str], legacy_format: bool) -> tuple[str, str]:
    """The environment names that hold this mailbox's credentials.

    Mailbox 1 falls back to the names before 3.1 while its numbered names are unset, so an
    existing installation starts without changing ``.env``.
    """
    numbered = mailbox.secret_names
    if (mailbox.id == 1 and not any(env.get(name) for name in numbered)
            and (legacy_format or any(env.get(name) for name in LEGACY_IMAP_SECRETS))):
        return LEGACY_IMAP_SECRETS
    return numbered


def imap_secret_values(imap: ImapSettings, env: dict[str, str]
                       ) -> tuple[dict[int, dict[str, str]], list[str]]:
    """Credentials of every enabled mailbox and the names that are missing."""
    credentials, missing = {}, []
    for mailbox in imap.enabled_mailboxes():
        user, password = imap_secret_names(mailbox, env, imap.legacy_format)
        absent = [name for name in (user, password) if not env.get(name)]
        if absent:
            missing += absent
        else:
            credentials[mailbox.id] = {"username": env[user], "password": env[password]}
    return credentials, missing


def _distinct_accounts(imap: ImapSettings, credentials: dict[int, dict[str, str]]) -> None:
    """Two mailboxes with the same server, port and user would share their whole processing state."""
    from ..imap import account_id
    seen: dict[str, int] = {}
    for mailbox in imap.enabled_mailboxes():
        account = account_id(mailbox.host, mailbox.port, credentials[mailbox.id]["username"])
        if account in seen:
            raise ValueError(f"Postfächer {seen[account]} und {mailbox.id} verwenden dasselbe Konto "
                             "(Server, Port und Benutzername)")
        seen[account] = mailbox.id


def load_all(directory: Path, environ: dict[str, str] | None = None, *, oauth_profile: int | None = None
             ) -> tuple[Settings, Secrets, list[Topic], list[Topic], PromptConfig, str]:
    env = {**_dotenv(directory / ".env"), **(os.environ if environ is None else environ)}
    settings = validated_file(directory / "config.yaml", Settings, read_yaml(directory / "config.yaml"))
    prompts = validated_file(directory / "prompts.yaml", PromptConfig, read_yaml(directory / "prompts.yaml"))
    _create_missing_topic_files(directory)
    topics = validated_file(directory / "topics.yaml", TopicsConfig, read_yaml(directory / "topics.yaml")).topics
    irrelevant_topics = validated_file(
        directory / "irrelevant_topics.yaml", IrrelevantTopicsConfig,
        read_yaml(directory / "irrelevant_topics.yaml"),
    ).topics
    credentials, missing = imap_secret_values(settings.imap, env)
    iserv: dict[int, dict[str, str]] = {}
    for account in settings.iserv.enabled_accounts():
        absent = [name for name in account.secret_names if not env.get(name)]
        missing += absent
        if not absent:
            user, password = account.secret_names
            iserv[account.id] = {"username": env[user], "password": env[password]}
    from ..mailbox_settings import active_profiles
    from ..target_profiles import load_profile_secrets
    used = active_profiles(settings)
    names = [
        "OPENROUTER_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        *(provider_secret_names(settings.targets) if 1 in used else []),
    ]
    profile_values, absent = load_profile_secrets(settings, env)
    missing += absent
    missing += [name for name in names if not env.get(name)]
    if oauth_profile is not None:
        from ..target_profiles import secret_name
        refresh = ("GOOGLE_OAUTH_REFRESH_TOKEN" if oauth_profile == 1
                   else secret_name("GOOGLE_OAUTH_REFRESH_TOKEN", oauth_profile))
        missing = [name for name in missing if name != refresh]
    if not settings.telegram.enabled:
        names.remove("TELEGRAM_BOT_TOKEN")
        missing = [name for name in missing if name != "TELEGRAM_BOT_TOKEN"]
    if missing:
        raise ValueError("Fehlende Geheimnisse: " + ", ".join(missing))
    values: dict[str, Any] = {name.lower(): env.get(name, "") for name in names}
    values["imap"] = credentials
    values["iserv"] = iserv
    values["profiles"] = profile_values
    _distinct_accounts(settings.imap, credentials)
    from ..target_profiles import PROVIDER_FIELDS
    values.update({name: env[name.upper()] for name in PROVIDER_FIELDS if env.get(name.upper())})
    if settings.web.enabled:
        web_secret = env.get("MAILHELP_WEB_SECRET", "")
        if not web_secret:
            raise ValueError("Fehlende Geheimnisse: MAILHELP_WEB_SECRET (benötigt für web.enabled)")
        if len(web_secret) < 32:
            raise ValueError("MAILHELP_WEB_SECRET muss mindestens 32 Zeichen lang sein")
        values["mailhelp_web_secret"] = web_secret
    secrets = Secrets.model_validate(values)
    # Only analysis-relevant settings: operational changes (web, polling, logging,
    # retention, timeouts, metrics) must not hold back mails that are running.
    from ..fingerprints import config_fingerprint
    fingerprint = config_fingerprint(settings, prompts, topics)
    return settings, secrets, topics, irrelevant_topics, prompts, fingerprint


def validated_file(path: Path, model: type[BaseModel], value: Any, prefix: str = "") -> Any:
    try: return model.model_validate(value)
    except ValidationError as exc:
        locations = []
        for error in exc.errors(include_input=False):
            location = ".".join(str(part) for part in error["loc"]) or "<root>"
            locations.append(f"{prefix}.{location}" if prefix else location)
        raise ValueError(f"{path}: ungültige Schlüsselpfade: {', '.join(locations)}") from exc


__all__ = ["DEFAULT_TOPIC_FILES", "LEGACY_IMAP_SECRETS", "OPTIONAL_PROVIDER_SECRETS", "imap_secret_names",
           "imap_secret_values", "load_all", "provider_secret_names", "read_yaml", "validated_file"]
