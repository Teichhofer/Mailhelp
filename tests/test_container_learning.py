"""Exercise atomically replaced learning files on actual Compose directory mounts."""
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace

import yaml

from mailhelp.config import Topic
from mailhelp.imap import FetchedMail
from mailhelp.learning import LearningMode
from mailhelp.models import AbstractCategories, LearnedCategory, MailClassification, Relevance
from mailhelp.orchestrator import Orchestrator, ProcessingOutcome
from mailhelp.storage import JsonStore


def test_learning_mount_preserves_filter_topics_and_folders_across_restart(tmp_path, monkeypatch):
    supplied = os.environ.get("MAILHELP_LEARNING_CONFIG")
    config = Path(supplied) if supplied else tmp_path / "config"
    root = Path(__file__).parents[1]
    if not supplied:
        config.mkdir()
        for source, target in (("config.example.yaml", "config.yaml"),
                               ("topics.yaml", "topics.yaml"),
                               ("irrelevant_topics.yaml", "irrelevant_topics.yaml"),
                               ("irrelevant-senders.example.json", "irrelevant-senders.json")):
            shutil.copyfile(root / source, config / target)
    def forbid(*args, **kwargs): raise AssertionError("Unexpected network or notification")
    monkeypatch.setattr("socket.socket.connect", forbid)
    stages = [int(os.environ["MAILHELP_SMOKE_STAGE"])] if supplied else [1, 2]
    mail = FetchedMail("INBOX", 1, 1,
                      b"From: learned@example.test\nSubject: Synthetic learning\n\nSynthetic body")
    class Imap:
        def list_folders(self): return ["INBOX", "SyntheticLearnedFolder"]
        def fetch_since(self, *args): return [mail]
    accepted = LearnedCategory(name="Synthetic accepted", description="Synthetic relevant topic")
    rejected = LearnedCategory(name="Synthetic rejected", description="Synthetic irrelevant topic")
    class Analyzer:
        def relevance(self, *args): return "r", Relevance(decision="irrelevant", topic_ids=[], reason="synthetic")
        def classify_for_learning(self, *args): return "c", MailClassification(categories=[rejected])
        def abstract_learned_categories(self, *args): return "a", AbstractCategories(categories=[accepted, rejected])
    def topics(name):
        return [Topic.model_validate(item) for item in yaml.safe_load(
            (config / name).read_text(encoding="utf-8"))["topics"]]
    for stage in stages:
        if stage == 1:
            answers = iter(["j", "n"])
            mode = LearningMode(Imap(), Analyzer(), ["INBOX"], 100_000,
                topics("topics.yaml"), config / "topics.yaml",
                topics("irrelevant_topics.yaml"), config / "irrelevant_topics.yaml",
                store=JsonStore(config), input_fn=lambda _: next(answers), output_fn=lambda _: None,
                global_newest_first=False, config_path=config / "config.yaml")
            assert mode.run(1) == 1
        assert "SyntheticLearnedFolder" in yaml.safe_load((config / "config.yaml").read_text(encoding="utf-8"))["imap"]["folders"]
        assert any(topic.name == accepted.name for topic in topics("topics.yaml"))
        assert any(topic.name == rejected.name for topic in topics("irrelevant_topics.yaml"))
        assert "learned@example.test" in json.loads((config / "irrelevant-senders.json").read_text(encoding="utf-8"))["addresses"]
        # Fresh state and adapter: the learned filter must prevent any LLM call.
        with JsonStore(config / "data" / f"filter-smoke-{stage}") as store:
            result = Orchestrator(SimpleNamespace(relevance=forbid), store,
                SimpleNamespace(send=forbid), 1, topics("topics.yaml"), 100_000,
                sender_store=JsonStore(config)).process(mail)
            assert result.outcome is ProcessingOutcome.COMPLETED
            assert result.state["relevance"]["decision"] == "irrelevant"
