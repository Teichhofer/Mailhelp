"""Synthetic decisions, topic files and model for the 5.6 rule-review contracts."""
import json
from types import SimpleNamespace

import yaml

from mailhelp.configuration import ConfigurationService
from mailhelp.review.learning_log import learning_path
from mailhelp.rule_learning.changes import RuleSuggestions
from mailhelp.rule_learning.models import RuleAnalysis, RuleProposal, RuleTopic
from mailhelp.rule_learning.service import DecisionRuleLearning
from mailhelp.storage import JsonStore
from tests.fakes.shared_application import settings


def topic(**changes):
    return RuleTopic(id="school", name="Schule", enabled=True, description="Verbindliche Schulaufgaben",
                     **changes) if not changes else RuleTopic.model_validate({
                         **topic().model_dump(), **changes})


def proposal(**changes):
    data = {"topic_id": "school", "category": "relevant", "action": "modify",
            "rationale": "Wiederholte manuelle Korrektur", "evidence": ["decision-1"],
            "proposed": topic(exclusions=["Unverbindliche Werbung"]).model_dump()}
    return RuleProposal.model_validate({**data, **changes})


def record(identity="decision-1", kind="reject", **changes):
    return {"schema_version": 1, "id": identity, "kind": kind,
            "analysis": {"relevance": {"decision": "relevant", "topic_ids": ["school"]}},
            "mail": {"headers": {"subject": "Synthetischer Elternbrief"},
                     "content": {"text": "Nur ein unverbindliches Angebot. secret-token"}},
            "proposal": {"changes": {}}, **changes}


class FakeRuleAnalyzer:
    def __init__(self):
        self.prompts = SimpleNamespace(prompts={"decision_rule_learning": object()})
        self.calls, self.retries = [], []
        self.before = lambda: None
        self.error = None
        self.result = RuleAnalysis(proposals=[proposal()])

    def decision_rule_learning(self, payload, *, before_call, assemble=None, retry_payload=None):
        self.before()
        before_call()
        self.calls.append(payload)
        self.retries.append(retry_payload)
        if self.error is not None:
            raise self.error
        # 5.7.7: a change-based answer is assembled like the real analyzer does.
        return "synthetic", assemble(self.result) if isinstance(self.result, RuleSuggestions) else self.result


class RuleHarness:
    def __init__(self, directory, store=None, active=None):
        self.directory = directory
        self.store = store or JsonStore(directory / "data")
        self.authorized = {"web:a", "web:b"}
        self.active = active or (lambda actor: actor in self.authorized)
        self.activated = []
        cfg = settings(directory)
        (directory / "config.yaml").write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
        (directory / "topics.yaml").write_text(yaml.safe_dump({"topics": [topic().model_dump()]}), encoding="utf-8")
        (directory / "irrelevant_topics.yaml").write_text("topics: []\n", encoding="utf-8")
        self.analyzer = FakeRuleAnalyzer()
        self.configuration = ConfigurationService(directory, self.store, cfg, self.active, lambda _: None,
                                                  self.activated.append)
        self.now = 1000.0
        self.limit = 100_000
        self.service = DecisionRuleLearning(self.configuration, lambda: self.analyzer, self.active,
            lambda text: text.replace("secret-token", "[entfernt]"), lambda: self.limit, lambda: self.now)

    def log(self, *records):
        path = learning_path(self.store.directory)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")

    def analyze(self, actor="web:a", key="analyze-1"):
        state = self.service.state(actor)
        return self.service.change(actor, state.version, key, "analyze", {"confirm": True})

    def review(self):
        self.log(record())
        self.analyze()
        assert self.service.tick()
        return self.service.state("web:a")

    def apply(self, choices=None, key="apply-key", actor="web:a"):
        state = self.service.state(actor)
        if choices is None:
            choices = [{"index": 0, "topic": state.proposals[0].proposed.model_dump()}]
        return self.service.change(actor, state.version, key, "apply", {"confirm": True, "choices": choices})
