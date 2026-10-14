import pytest
import yaml

"""Synthetic configuration of two mailboxes and independent target profiles."""
from shared_application import settings as application_settings

from mailhelp.config import Settings, Topic

ACCOUNT_ONE, ACCOUNT_TWO = "1" * 24, "2" * 24


def settings(tmp_path, *, profiles=True, **changes):
    raw = application_settings(tmp_path).model_dump(mode="json")
    raw["imap"] = {"batch_size": 25, "mailboxes": [
        {"id": 1, "label": "Privat", "host": "private.example.test", "port": 993, "folders": ["INBOX"]},
        {"id": 2, "label": "Arbeit", "host": "work.example.test", "port": 993, "folders": ["INBOX"],
         "target_profile": 2 if profiles else 1}]}
    raw["target_profiles"] = ([{"id": 2, "label": "Arbeit", "calendar_provider": "outlook",
                                "task_provider": "microsoft_todo"}] if profiles else [])
    raw.update(changes)
    return Settings.model_validate(raw)


TOPICS = [Topic(id="shared", name="Gemeinsam", description="Gemeinsam", enabled=True)]


@pytest.fixture
def profiled(configured):
    cfg = settings(configured.tmp_path)
    configured.cfg = configured.app.settings = configured.app.configuration.active = cfg
    configured.app.orchestrator.configure_mailboxes(cfg, configured.app.analyzer.prompts, {ACCOUNT_ONE: 1, ACCOUNT_TWO: 2})
    configured.app.orchestrator.topics = TOPICS
    configured.app.configuration.senders = configured.web.store
    configured.app.dialog.relevance_handler = configured.app.orchestrator
    directory = configured.tmp_path
    (directory / "config.yaml").write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
    for name in ("topics.yaml", "irrelevant_topics.yaml"):
        (directory / name).write_text(yaml.safe_dump({"topics": [topic.model_dump(mode="json") for topic in TOPICS]}))
    return configured
