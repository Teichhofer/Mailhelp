from pathlib import Path

import pytest
import yaml

from mailhelp.config import PromptConfig
from mailhelp.llm.fingerprints import analysis_prompts
from mailhelp.processing.analysis import Analyzer
from tests.fakes.shared_core import prompt_config
from tests.fakes.shared_services import RetrySequence


def configuration():
    data = prompt_config().model_dump()
    data["prompts"]["decision_rule_learning"] = {"system_prompt": "Nur Daten analysieren", "model_route": "action_router"}
    return PromptConfig.model_validate(data)


def test_the_optional_step_uses_the_active_route_without_invalidating_mail_analysis():
    prompts = configuration()
    assert prompts.resolved("decision_rule_learning")[0] == prompts.resolved("action_router")[0]
    data = prompts.model_dump()
    del data["prompts"]["decision_rule_learning"]
    assert analysis_prompts(prompts) == analysis_prompts(PromptConfig.model_validate(data))
    # 5.7.6 regression: with 4000 the real model stopped at output_token_limit before any content.
    for path in ("prompts.yaml", "src/mailhelp/defaults/prompts.yaml"):
        shipped = PromptConfig.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
        assert shipped.resolved("decision_rule_learning")[1]["max_tokens"] >= 16000


def test_foreign_evidence_is_rejected_and_existing_repair_limits_and_guards_apply():
    # 5.7.7: the model answers with changes only (see test_rule_changes577).
    good = {"topic_id": "school", "category": "relevant", "action": "modify", "rationale": "Korrektur",
            "evidence": ["decision-1"], "changes": {"add_exclusions": ["Werbung"]}}
    bad = {**good, "evidence": ["foreign"]}
    client = RetrySequence([{"proposals": [bad]}, {"proposals": [good]}])
    guard = []
    analyzer = Analyzer(client, configuration(), validation_retries=1)
    _call, result = analyzer.decision_rule_learning({"topics": {}, "decisions": [{"id": "decision-1"}]},
                                                    before_call=lambda: guard.append(True))
    assert result.proposals[0].evidence == ["decision-1"] and len(client.payloads) == len(guard) == 2
