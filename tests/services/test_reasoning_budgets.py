"""Shipped reasoning parameters and output budgets."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


def test_regression_shipped_routes_bound_reasoning_and_leave_output_budget():
    """Bug: reasoning exhausted small budgets (e.g. 700 tokens) before any JSON output."""
    from mailhelp.config import PromptConfig
    config = PromptConfig.model_validate(yaml.safe_load(Path("prompts.yaml").read_text(encoding="utf-8")))
    for step in config.prompts:
        route = config.resolved_routes(step)[0][0]
        expected = {"effort": "medium" if step == "action_router" else "low"}
        assert route.parameters["reasoning"] == expected, step
    for step in ("summary", "mail_question_resolution", "telegram_answer_interpretation",
                 "telegram_answer_clarification", "calendar_duplicate"):
        assert config.resolved_routes(step)[0][0].parameters["max_tokens"] >= 4000, step
    interpretation = config.prompts["telegram_answer_interpretation"]
    assert interpretation.output_token_retry.parameters["max_tokens"] >= \
        config.resolved_routes("telegram_answer_interpretation")[0][0].parameters["max_tokens"]


@pytest.mark.parametrize("reasoning", [
    {"effort": "low"}, {"effort": "minimal", "exclude": True}, {"max_tokens": 1000},
])
def test_reasoning_parameter_accepts_only_its_closed_shapes(reasoning):
    from mailhelp.config import LlmRoute, OutputTokenRetry, checked_parameters
    assert checked_parameters({"reasoning": reasoning}, "x")["reasoning"] == reasoning
    assert LlmRoute(provider="openrouter", model="m", parameters={"reasoning": reasoning})
    assert OutputTokenRetry(system_prompt="s", parameters={"reasoning": reasoning})


@pytest.mark.parametrize(("reasoning", "message"), [
    ("low", "ausschließlich effort"), ({"enabled": False}, "ausschließlich effort"),
    ({}, "genau eines"), ({"effort": "low", "max_tokens": 10}, "genau eines"),
    ({"effort": "extreme"}, "reasoning.effort"), ({"max_tokens": True}, "1 bis 32000"),
    ({"max_tokens": 0}, "1 bis 32000"), ({"effort": "low", "exclude": "ja"}, "Wahrheitswert"),
])
def test_reasoning_parameter_rejects_invalid_or_disabling_values(reasoning, message):
    from mailhelp.config import PromptConfig, checked_parameters
    with pytest.raises(ValueError, match=message):
        checked_parameters({"reasoning": reasoning}, "x")
    raw = yaml.safe_load(Path("prompts.yaml").read_text(encoding="utf-8"))
    raw["defaults"]["parameters"]["reasoning"] = reasoning
    with pytest.raises(ValueError):
        PromptConfig.model_validate(raw).resolved_routes("summary")
    with pytest.raises(ValueError, match="Unbekannte"):
        checked_parameters({"thinking": True}, "Unbekannte")


def test_shipped_output_budgets_match_the_specification():
    config = yaml.safe_load(Path("prompts.yaml").read_text(encoding="utf-8"))["prompts"]
    for step in ("relevance", "action_router", "task_extraction", "event_extraction",
                 "learning_classification"):
        assert config[step]["parameters"]["max_tokens"] == 10_000, step
    assert config["learning_abstraction"]["parameters"]["max_tokens"] == 16_000


def test_event_and_summary_prompts_cover_evaluation_findings():
    prompts = yaml.safe_load(Path("prompts.yaml").read_text(encoding="utf-8"))["prompts"]
    event = " ".join(prompts["event_extraction"]["system_prompt"].split())
    assert "time_text enthält nur die wörtliche Beginnuhrzeit" in event
    assert "ändert das nicht, an wen die Einladung zum Termin gerichtet ist" in event
    summary = " ".join(prompts["summary"]["system_prompt"].split())
    assert "jedes genannte Kalenderdatum" in summary
    assert "rechne sie nie in ein Kalenderdatum um" in summary
