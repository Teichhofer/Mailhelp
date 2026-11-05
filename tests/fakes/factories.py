"""Model factories: a test states only what differs from a valid default (Planung 4.1, 9.9).

Each factory starts from one complete, valid default and validates the result through the
real Pydantic model. A new required field or validator therefore needs one change here,
not one in every test module that used to spell out raw dictionaries.

``changes`` replace top-level fields; for settings, nested dictionaries are merged, so
``minimal_settings(tmp_path, imap={"folders": ["Archiv"]})`` keeps the other IMAP values.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from mailhelp.config import Settings
from mailhelp.domain.mail import MailState
from mailhelp.domain.proposal import Proposal

MAIL_ID = "a" * 24
ROOT = Path(__file__).resolve().parents[2]

PROPOSAL_DEFAULTS: dict[str, Any] = {
    "id": "p1", "version": 1, "kind": "task", "responsibility": "user", "certainty": "certain",
    "classification": "new", "title": "Aufgabe", "description": "", "evidence": "Beleg",
    "source_mail_id": MAIL_ID, "target": "inbox",
}


def clarification_needed(values: dict[str, Any]) -> bool:
    """The builder's rule: anything but a certain, new task of the user needs clarification."""
    return bool(values.get("open_questions") or values["responsibility"] != "user"
                or values["certainty"] != "certain" or values["classification"] != "new")


def build_proposal(**changes: Any) -> Proposal:
    """A valid proposal; without an explicit status it follows the builder's clarification rule."""
    values = {**PROPOSAL_DEFAULTS, **changes}
    if "status" not in changes and clarification_needed(values):
        values["status"] = "needs_clarification"
    return Proposal.model_validate(values)


def build_mail_state(mail_id: str = MAIL_ID, *, uid: int = 1, proposals=(),
                     sender: str | None = "Ada Muster <ada@example.test>", subject: str = "Elternabend",
                     updated: datetime | None = None, imap: dict[str, Any] | None = None,
                     **changes: Any) -> MailState:
    """A stored mail state created a day before *updated*, with display headers and proposals.

    *imap* changes single identity fields (``account_id``, ``folder``, ``uidvalidity``).
    """
    now = updated or datetime.now(UTC)
    values: dict[str, Any] = {
        "id": mail_id, "config_fingerprint": "f" * 64,
        "imap": {"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": uid, **(imap or {})},
        "display_headers": {"sender": sender, "subject": subject} if sender else None,
        "proposals": list(proposals), "created_at": now - timedelta(days=1), "updated_at": now,
    }
    values.update(changes)
    return MailState.model_validate(values)


def merged(base: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    """*base* with *changes*; dictionaries are merged recursively, everything else replaced."""
    result = deepcopy(base)
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merged(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _timeouts() -> dict[str, Any]:
    service = {"timeout_seconds": 30.0, "retries": 0, "initial_backoff_seconds": 0.0, "max_backoff_seconds": 1.0}
    return {**{name: dict(service) for name in ("imap", "telegram", "openrouter", "todoist", "google_calendar")},
            "telegram_poll_seconds": 30}


def minimal_settings_data(tmp_path: Path) -> dict[str, Any]:
    """The smallest valid configuration: test mode, one IMAP folder, no retries, quiet logs."""
    log = {"max_bytes": 10000, "backup_count": 1, "retention_days": 30}
    return {
        "timezone": "UTC", "poll_interval_seconds": 5, "test_mode": True,
        "data_directory": str(tmp_path / "data"),
        "imap": {"host": "h", "port": 993, "folders": ["INBOX"], "global_newest_first": False},
        "telegram": {"user_id": 1, "chat_id": 2},
        "targets": {"todoist_project": "p", "google_calendar": "c"},
        "limits": {"max_mail_bytes": 1024, "llm_calls_per_minute": 2},
        "retries": {"provider_retry": 0, "json_repair": 0, "schema_repair": 0},
        "timeouts": _timeouts(),
        "logging": {"directory": str(tmp_path / "logs"), "console": {"enabled": False},
                    "file": {"filename": "application.jsonl", **log},
                    "llm": {"filename": "llm/requests.jsonl", **log}},
    }


def minimal_settings(tmp_path: Path, **changes: Any) -> Settings:
    return Settings.model_validate(merged(minimal_settings_data(tmp_path), changes))


def complete_settings(tmp_path: Path, **changes: Any) -> Settings:
    """The shipped ``config.example.yaml`` with data and logs below *tmp_path*."""
    data = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    data["data_directory"] = str(tmp_path / "data")
    data["logging"]["directory"] = str(tmp_path / "logs")
    return Settings.model_validate(merged(data, changes))
