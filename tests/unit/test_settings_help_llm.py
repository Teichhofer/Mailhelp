"""5.3 H8: the optional settings_help step uses the active model path, a validated route reference
and a source contract; it changes no fingerprint of the mail analysis."""
from pathlib import Path

import pytest
import yaml

from devtools import prompt_guard
from mailhelp.config import LlmRoute, PromptConfig, PromptStep
from mailhelp.helpdocs import HelpAnswer, answer_validator, load
from mailhelp.llm.fingerprints import analysis_prompts
from mailhelp.processing.analysis import Analyzer
from tests.fakes.shared_core import prompt_config
from tests.fakes.shared_services import RetrySequence

REPOSITORY = PromptConfig.model_validate(yaml.safe_load(Path("prompts.yaml").read_text(encoding="utf-8")))


def with_help(config: PromptConfig, **fields) -> PromptConfig:
    data = config.model_dump()
    data["prompts"]["settings_help"] = {"system_prompt": "Hilfe", "model_route": "action_router",
                                        "parameters": {"max_tokens": 900}, **fields}
    return PromptConfig.model_validate(data)


def test_the_route_reference_uses_the_referenced_model_with_own_parameters():
    model, parameters, prompt = REPOSITORY.resolved("settings_help")
    assert model == REPOSITORY.resolved("action_router")[0] and prompt.startswith("Du bist die Hilfe")
    assert parameters["max_tokens"] == 1500 and parameters["reasoning"] == {"effort": "low"}
    routed = with_help(prompt_config().model_copy(update={"prompts": {
        **prompt_config().prompts, "action_router": PromptStep(system_prompt="r", routes=[
            LlmRoute(provider="openrouter", model="route-a", parameters={"max_tokens": 300})])}}))
    routes, prompt, _retries = routed.resolved_routes("settings_help")
    assert [route.model for route in routes] == ["route-a"] and routes[0].parameters["max_tokens"] == 900
    plain = with_help(prompt_config())
    assert plain.resolved_routes("settings_help")[0][0].model == "model" and plain.resolved("settings_help")[0] == "model"


@pytest.mark.parametrize(("fields", "message"), [
    ({"model_route": "gibt_es_nicht"}, "verweist auf keinen Schritt"),
    ({"model_route": "settings_help"}, "verweist auf keinen Schritt"),
    ({"model": "anderes"}, "schließt model"),
])
def test_an_invalid_route_reference_is_rejected(fields, message):
    with pytest.raises(ValueError, match=message):
        with_help(prompt_config(), **fields)


def test_the_new_step_changes_no_fingerprint_of_the_mail_analysis():
    data = REPOSITORY.model_dump()
    assert "model_route" not in data["prompts"]["action_router"]  # unused references are not written
    assert data["prompts"]["settings_help"]["model_route"] == "action_router"
    del data["prompts"]["settings_help"]
    assert analysis_prompts(PromptConfig.model_validate(data)) == analysis_prompts(REPOSITORY)
    text = Path("prompts.yaml").read_text(encoding="utf-8")
    assert "settings_help:" in text and "settings_help:" not in prompt_guard._evaluated("prompts.yaml", text)
    assert prompt_guard._evaluated("topics.yaml", "x") == "x"


def test_an_answer_is_bound_to_the_given_sources_and_known_settings():
    validate = answer_validator(["betrieb/sicherung"], ["setting:timezone"])
    answer = validate({"answer": "So geht es.", "source_ids": ["betrieb/sicherung"],
                       "setting_ids": ["setting:timezone"], "needs_clarification": False})
    assert answer == HelpAnswer(answer="So geht es.", source_ids=["betrieb/sicherung"], setting_ids=["setting:timezone"])
    for wrong in ({"answer": "x", "source_ids": ["fremd"]}, {"answer": "x", "setting_ids": ["setting:erfunden"]}):
        with pytest.raises(ValueError, match="Unbekannte"):
            validate(wrong)


def test_the_analyzer_asks_the_active_client_and_repairs_a_foreign_source_once():
    sections = load().select("Was bewirkt das Abrufintervall?")
    client = RetrySequence([{"answer": "x", "source_ids": ["erfunden"]},
                            {"answer": "Das Abrufintervall …", "source_ids": [sections[0].id]}])
    analyzer = Analyzer(client, with_help(prompt_config()), validation_retries=1)
    _call, answer = analyzer.settings_help("Was bewirkt das Abrufintervall?", sections, [],
                                           [{"id": "setting:poll_interval_seconds", "label": "Abrufintervall"}])
    assert answer.source_ids == [sections[0].id] and len(client.payloads) == 2
    sent = client.payloads[0]
    assert sent["question"] == "Was bewirkt das Abrufintervall?" and sent["sources"][0]["id"] == sections[0].id
    assert client.systems[0] == "Hilfe" and client.parameters[0]["max_tokens"] == 900
