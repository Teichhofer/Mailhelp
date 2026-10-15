"""Configuration fingerprints that only change when the analysis would change.

A mail whose analysis started under one configuration is held back when the
configuration changes (``Orchestrator.accepts_configuration``).  Operational
settings – polling, logging, retention, timeouts, metrics, the web interface –
do not change how a mail is analysed, so they are not part of the fingerprint:
changing them in the web interface must not hold back running mails.

Up to 1.1 (and in the 1.2 beta) the fingerprint covered almost every setting.
For exactly the same configuration those former fingerprints are registered as
equivalent at start-up, so mails waiting for a decision continue after the
upgrade instead of being held back forever.

Vision OCR (1.4) only enriches a mail while it is being prepared, before any
fingerprinted analysis step.  Its settings and its ``vision_ocr`` prompt are
therefore excluded as well; the fingerprint of an unchanged 1.3 configuration
stays the same after the upgrade.

The 2.0 sections (Web-Push, reply drafts, daily briefing, standalone mode) act
only after the analysis.  They are removed from every fingerprint, including the
legacy ones, so an unchanged 1.x configuration keeps all of its fingerprints.

Mailboxes (3.1) decide where mail comes from, not how it is analysed: ``imap`` is
operational. Until 3.0 it was part of the fingerprint; for mailbox 1 the former
``imap`` section is reproduced exactly, so mails started before the upgrade continue.

Write targets (3.2) are operational as well. The 3.1 hashes and topic policies
are registered as equivalent on upgrade without changing saved proposal bindings.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from .config import MAILBOX_FIELDS, PromptConfig, Settings, Topic
from .storage import JsonStore

# Sections and fields introduced by 2.0 and later; they never influence an analysis.
EXPERIENCE = frozenset({"push", "daily_briefing", "smart_reply", "personal_info", "activity_report", "notifications",
                        "event_defaults", "proposal_reconciliation", "target_profiles"})
EXPERIENCE_FIELDS = (("imap", "drafts_folder"), ("telegram", "enabled"), ("retention", "activity_report_days"),
                     # 2.3: further write targets; an unchanged Google/Todoist configuration keeps its fingerprint.
                     *(("targets", name) for name in ("calendar_provider", "task_provider", "caldav_calendar_url",
                                                      "caldav_task_url", "outlook_calendar", "microsoft_todo_list",
                                                      "microsoft_tenant")))
OPERATIONAL_BEFORE_3_1 = frozenset({"web", "metrics", "retention", "logging", "learning", "poll_interval_seconds",
                                    "timeouts", "retries", *EXPERIENCE})
OPERATIONAL = OPERATIONAL_BEFORE_3_1 | {"imap"}
# Preparation-only settings and prompt steps (see module documentation).
PREPARATION = frozenset({"vision", "attachments"})
PREPARATION_PROMPTS = frozenset({
    "vision_ocr", "draft_reply", "activity_relevance", "activity_events", "diagnostic_test", "open_proposal_match"})


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _imap_before_3_1(settings: Settings) -> dict[str, Any] | None:
    """The ``imap`` section as releases before 3.1 dumped it, built from mailbox 1."""
    mailbox = settings.imap.mailbox(1)
    if mailbox is None:
        return None
    return {**mailbox.model_dump(mode="json", include=set(MAILBOX_FIELDS)),
            "batch_size": settings.imap.batch_size, "global_newest_first": settings.imap.global_newest_first}


def _settings(settings: Settings, exclude: set[str]) -> dict[str, Any]:
    value = settings.model_dump(mode="json", exclude=exclude | EXPERIENCE)
    if "imap" in value:
        # Only the fingerprints of former releases still contain the section.
        value["imap"] = _imap_before_3_1(settings)
    for section, name in EXPERIENCE_FIELDS:
        # A section may itself be excluded (retention is operational for the analysis).
        if section in value:
            value[section].pop(name)
    return value


def analysis_settings(settings: Settings) -> dict[str, Any]:
    return _settings(settings, set(OPERATIONAL | PREPARATION | {"targets"}))


def analysis_prompts(prompts: PromptConfig) -> dict[str, Any]:
    return prompts.model_dump(exclude={"prompts": set(PREPARATION_PROMPTS)})


def config_fingerprint(settings: Settings, prompts: PromptConfig, topics: list[Topic]) -> str:
    return _hash([analysis_settings(settings), analysis_prompts(prompts),
                  [topic.model_dump(exclude_none=True) for topic in topics]])


def topic_policy(settings: Settings, prompts: PromptConfig) -> str:
    """Everything but the topics; equal policies may exchange topic lists."""
    return _hash([analysis_settings(settings), analysis_prompts(prompts)])


def proposal_match_policy(prompts: PromptConfig) -> str:
    step = prompts.prompts.get("open_proposal_match")
    return _hash([prompts.defaults, step.model_dump() if step is not None else None])


def legacy_fingerprints(settings: Settings, prompts: PromptConfig, topics: list[Topic]) -> set[str]:
    """Fingerprints that releases through 3.1 computed for this same configuration.

    Without mailbox 1 only the 3.1 fingerprint can be reconstructed.
    """
    rest = [analysis_prompts(prompts), [topic.model_dump(exclude_none=True) for topic in topics]]
    former = {_hash([_settings(settings, set(OPERATIONAL | PREPARATION)), *rest])}
    if _imap_before_3_1(settings) is None:
        return former
    beta = _settings(settings, {"web", *PREPARATION})
    release_1_1 = copy.deepcopy(beta)
    release_1_1.pop("metrics")
    release_1_1["retention"] = {key: value for key, value in release_1_1["retention"].items()
                                if key not in {"analysis_days", "history_days"}}
    release_3_0 = _settings(settings, set(OPERATIONAL_BEFORE_3_1 | PREPARATION))
    return former | {_hash([release_1_1, *rest]), _hash([beta, *rest]), _hash([release_3_0, *rest])}


def legacy_policies(settings: Settings, prompts: PromptConfig) -> set[str]:
    """Topic policies written by the 1.2 beta and by 1.2 through 3.1."""
    former = {_hash([_settings(settings, set(OPERATIONAL | PREPARATION)), analysis_prompts(prompts)])}
    if _imap_before_3_1(settings) is None:
        return former
    return former | {
        _hash([_settings(settings, {"web", "metrics", "retention", *PREPARATION}), analysis_prompts(prompts)]),
        _hash([_settings(settings, set(OPERATIONAL_BEFORE_3_1 | PREPARATION)), analysis_prompts(prompts)]),
    }


def adopt_legacy_configuration(store: JsonStore, fingerprint: str, legacy: set[str], policy: str,
                               old_policies: set[str], topics: list[Topic]) -> int:
    """Register former fingerprints of this configuration; returns how many were added."""
    added = 0
    for former in sorted(legacy - {fingerprint}):
        name = f"processing-topics-{former}"
        if store.load(name) is None:
            store.save(name, {"schema_version": 1, "policy": policy,
                              "topics": [topic.model_dump() for topic in topics]})
            added += 1
    for name in store.names("processing-topics-"):
        record = store.load(name)
        if record.get("policy") in old_policies:
            store.save(name, {**record, "policy": policy})
    return added


__all__ = ["EXPERIENCE", "EXPERIENCE_FIELDS", "OPERATIONAL", "PREPARATION", "PREPARATION_PROMPTS",
           "adopt_legacy_configuration",
           "analysis_prompts", "analysis_settings", "config_fingerprint",
           "legacy_fingerprints", "legacy_policies", "topic_policy"]
