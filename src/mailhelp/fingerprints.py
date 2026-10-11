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
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from .config import PromptConfig, Settings, Topic
from .storage import JsonStore

OPERATIONAL = frozenset({"web", "metrics", "retention", "logging", "learning", "poll_interval_seconds",
                         "timeouts", "retries"})


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def analysis_settings(settings: Settings) -> dict[str, Any]:
    return settings.model_dump(mode="json", exclude=set(OPERATIONAL))


def config_fingerprint(settings: Settings, prompts: PromptConfig, topics: list[Topic]) -> str:
    return _hash([analysis_settings(settings), prompts.model_dump(), [topic.model_dump() for topic in topics]])


def topic_policy(settings: Settings, prompts: PromptConfig) -> str:
    """Everything but the topics; equal policies may exchange topic lists."""
    return _hash([analysis_settings(settings), prompts.model_dump()])


def legacy_fingerprints(settings: Settings, prompts: PromptConfig, topics: list[Topic]) -> set[str]:
    """Fingerprints that 1.1 and the 1.2 beta computed for this same configuration."""
    beta = settings.model_dump(mode="json", exclude={"web"})
    release_1_1 = copy.deepcopy(beta)
    release_1_1.pop("metrics")
    release_1_1["retention"] = {key: value for key, value in release_1_1["retention"].items()
                                if key not in {"analysis_days", "history_days"}}
    rest = [prompts.model_dump(), [topic.model_dump() for topic in topics]]
    return {_hash([release_1_1, *rest]), _hash([beta, *rest])}


def legacy_policies(settings: Settings, prompts: PromptConfig) -> set[str]:
    """Topic policies written by the 1.2 beta."""
    return {_hash([settings.model_dump(mode="json", exclude={"web", "metrics", "retention"}),
                   prompts.model_dump()])}


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


__all__ = ["OPERATIONAL", "adopt_legacy_configuration", "analysis_settings", "config_fingerprint",
           "legacy_fingerprints", "legacy_policies", "topic_policy"]
