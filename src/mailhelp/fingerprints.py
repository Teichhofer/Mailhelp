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
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from .config import PromptConfig, Settings, Topic
from .storage import JsonStore

# Sections and fields introduced by 2.0 and later; they never influence an analysis.
EXPERIENCE = frozenset({"push", "daily_briefing", "smart_reply", "personal_info", "activity_report"})
EXPERIENCE_FIELDS = (("imap", "drafts_folder"), ("telegram", "enabled"), ("retention", "activity_report_days"))
OPERATIONAL = frozenset({"web", "metrics", "retention", "logging", "learning", "poll_interval_seconds",
                         "timeouts", "retries", *EXPERIENCE})
# Preparation-only settings and prompt steps (see module documentation).
PREPARATION = frozenset({"vision"})
PREPARATION_PROMPTS = frozenset({"vision_ocr", "draft_reply", "activity_relevance", "activity_events"})


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _settings(settings: Settings, exclude: set[str]) -> dict[str, Any]:
    value = settings.model_dump(mode="json", exclude=exclude | EXPERIENCE)
    for section, name in EXPERIENCE_FIELDS:
        # A section may itself be excluded (retention is operational for the analysis).
        if section in value:
            value[section].pop(name)
    return value


def analysis_settings(settings: Settings) -> dict[str, Any]:
    return _settings(settings, set(OPERATIONAL | PREPARATION))


def analysis_prompts(prompts: PromptConfig) -> dict[str, Any]:
    return prompts.model_dump(exclude={"prompts": set(PREPARATION_PROMPTS)})


def config_fingerprint(settings: Settings, prompts: PromptConfig, topics: list[Topic]) -> str:
    return _hash([analysis_settings(settings), analysis_prompts(prompts),
                  [topic.model_dump() for topic in topics]])


def topic_policy(settings: Settings, prompts: PromptConfig) -> str:
    """Everything but the topics; equal policies may exchange topic lists."""
    return _hash([analysis_settings(settings), analysis_prompts(prompts)])


def legacy_fingerprints(settings: Settings, prompts: PromptConfig, topics: list[Topic]) -> set[str]:
    """Fingerprints that 1.1 and the 1.2 beta computed for this same configuration."""
    beta = _settings(settings, {"web", *PREPARATION})
    release_1_1 = copy.deepcopy(beta)
    release_1_1.pop("metrics")
    release_1_1["retention"] = {key: value for key, value in release_1_1["retention"].items()
                                if key not in {"analysis_days", "history_days"}}
    rest = [analysis_prompts(prompts), [topic.model_dump() for topic in topics]]
    return {_hash([release_1_1, *rest]), _hash([beta, *rest])}


def legacy_policies(settings: Settings, prompts: PromptConfig) -> set[str]:
    """Topic policies written by the 1.2 beta."""
    return {_hash([_settings(settings, {"web", "metrics", "retention", *PREPARATION}),
                   analysis_prompts(prompts)])}


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
