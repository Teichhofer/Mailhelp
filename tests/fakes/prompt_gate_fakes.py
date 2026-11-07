"""Offline access to repository prompts, enabled topics and synthetic corpus."""
import json
from pathlib import Path

import yaml

from mailhelp.config import PromptConfig, Topic

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "tests/fixtures/mail_corpus_v3/corpus.json"

def repository_prompts() -> PromptConfig:
    return PromptConfig.model_validate(yaml.safe_load((ROOT / "prompts.yaml").read_text(encoding="utf-8")))

def repository_topics() -> dict[str, Topic]:
    raw = yaml.safe_load((ROOT / "topics.yaml").read_text(encoding="utf-8"))["topics"]
    return {topic.id: topic for topic in map(Topic.model_validate, raw)}

def gated_corpus(topics: dict[str, Topic]) -> dict:
    """Corpus v3 with every repository topic in its current wording from topics.yaml."""
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    corpus["topics"] = [topics[item["id"]].model_dump(mode="json") if item["id"] in topics else item
                        for item in corpus["topics"]]
    return corpus

def repository_topic_gaps(corpus: dict, topics: dict[str, Topic]) -> list[str]:
    """Corpus topics taken from topics.yaml that it no longer offers as enabled topics."""
    expected = {topic_id for case in corpus["cases"] for topic_id in case["expected"]["relevance"]["topic_ids"]}
    synthetic = {"arbeit", "kommune"}
    return sorted(topic_id for topic_id in expected - synthetic
                  if topic_id not in topics or not topics[topic_id].enabled)
