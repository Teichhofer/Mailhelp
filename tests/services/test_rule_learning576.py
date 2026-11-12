"""5.7.6: specific failure reasons, the whole log, and "only new" or "all" decisions."""
import json

import pytest

from mailhelp.processing.analysis import (
    LlmInvalidJson,
    LlmProviderResponseInvalid,
    LlmSchemaValidationFailed,
    LlmTokenLimitExceeded,
)
from mailhelp.rule_learning import service as rule_service
from mailhelp.rule_learning.mining import DecisionRuleMiner
from mailhelp.rule_learning.models import RuleAnalysis
from mailhelp.rule_learning.service import GENERIC_FAILURE, failure_message
from mailhelp.rule_learning.validation import RuleConflict
from tests.fakes.rule_learning import RuleHarness, proposal, record


class Logger:
    def __init__(self):
        self.events = []

    def event(self, level, module, event, **context):
        self.events.append((level, module, event, context))


@pytest.fixture
def rules(tmp_path):
    harness = RuleHarness(tmp_path)
    harness.service.logger = Logger()
    return harness


def large(count, text_size=24_000):
    # Real decision records are about 20 KB; the text is cut to 1000 characters for the model.
    return [record(f"decision-{index}", mail={"headers": {"subject": f"Betreff {index}"},
                                              "content": {"text": "x" * text_size}}) for index in range(count)]


def test_the_whole_log_is_read_not_only_its_last_megabyte(tmp_path):
    # 5.7.6 regression: the miner read only the last 1 MB, i.e. about 40 real records.
    path = tmp_path / "decisions.jsonl"
    path.write_text("\n".join(json.dumps(item) for item in large(60)) + "\n", encoding="utf-8")
    assert path.stat().st_size > 1_400_000
    evidence, skipped = DecisionRuleMiner(path).mine(limit=500)
    assert len(evidence) == 60 and skipped == 0 and evidence[0]["id"] == "decision-59"
    newest, _ = DecisionRuleMiner(path).mine()
    assert len(newest) == 60
    without, _ = DecisionRuleMiner(path).mine({"decision-59", "decision-58"}, limit=3)
    assert [item["id"] for item in without] == ["decision-57", "decision-56", "decision-55"]


def test_only_new_skips_analysed_decisions_and_all_uses_them_again(rules, monkeypatch):
    rules.log(record("decision-1"), record("decision-2"))
    state = rules.analyze()
    assert state.scope == "new" and rules.service.tick()
    assert rules.service.state("web:a").status == "review"
    assert rules.service.history().decision_ids == ["decision-2", "decision-1"]
    rules.log(record("decision-1"), record("decision-2"), record("decision-3"))
    assert rules.service.overview("web:a")["new_decisions"] == 1
    assert rules.service.overview("web:a")["all_decisions"] == 3
    state = rules.service.state("web:a")
    state = rules.service.change("web:a", state.version, "analyze-new", "analyze", {"confirm": True, "scope": "new"})
    assert [item["id"] for item in state.evidence] == ["decision-3"]
    rules.service.tick()  # the fake proposal names decision-1, which is unknown here: a failed run
    state = rules.service.state("web:a")
    state = rules.service.change("web:a", state.version, "analyze-all", "analyze", {"confirm": True, "scope": "all"})
    assert [item["id"] for item in state.evidence] == ["decision-3", "decision-2", "decision-1"]
    assert state.scope == "all"
    rules.service.tick()
    state = rules.service.state("web:a")
    monkeypatch.setitem(rule_service.SCOPES, "all", 2)
    state = rules.service.change("web:a", state.version, "analyze-cap", "analyze", {"confirm": True, "scope": "all"})
    assert len(state.evidence) == 2


def test_without_new_decisions_the_message_points_to_all(rules):
    rules.log(record("decision-1"))
    rules.analyze()
    rules.service.tick()
    state = rules.service.state("web:a")
    with pytest.raises(ValueError, match="Keine neuen verwertbaren Entscheidungen.*Alle bisherigen"):
        rules.service.change("web:a", state.version, "analyze-again", "analyze", {"confirm": True})
    with pytest.raises(ValueError, match="Unbekannte Auswahl"):
        rules.service.change("web:a", state.version, "analyze-bad", "analyze", {"confirm": True, "scope": "x"})
    rules.log()
    with pytest.raises(ValueError, match="Keine verwertbaren Entscheidungen im Lernprotokoll"):
        rules.service.change("web:a", state.version, "analyze-empty", "analyze", {"confirm": True, "scope": "all"})


def test_a_token_limit_failure_names_its_cause_and_is_logged_without_content(rules):
    # 5.7.6 regression: every failure showed one generic sentence and nothing was logged.
    rules.log(record())
    rules.analyze()
    rules.analyzer.error = LlmTokenLimitExceeded("decision_rule_learning", "output_token_limit")
    assert rules.service.tick()
    state = rules.service.state("web:a")
    assert state.status == "failed" and "am Ausgabelimit abgeschnitten" in state.message
    assert "max_tokens von decision_rule_learning" in state.message
    [(level, module, event, context)] = rules.service.logger.events
    assert (level, module, event) == ("WARNING", "rule_learning", "analysis_failed")
    assert context["error"] == "LlmTokenLimitExceeded" and context["scope"] == "new" and context["decisions"] == 1
    assert "Elternbrief" not in json.dumps(context) and "secret-token" not in json.dumps(context)


@pytest.mark.parametrize(("error", "expected"), [
    (LlmProviderResponseInvalid("decision_rule_learning", "choice_missing"), "keine verwertbare Antwort"),
    (LlmInvalidJson("decision_rule_learning"), "nicht dem erwarteten Format"),
    (LlmSchemaValidationFailed("decision_rule_learning"), "nicht dem erwarteten Format"),
    (PermissionError("x"), "Sitzung abgelaufen"),
    (RuleConflict("x"), "währenddessen geändert"),
    (ValueError("In prompts.yaml fehlt decision_rule_learning"), "In prompts.yaml fehlt decision_rule_learning."),
])
def test_each_failure_has_a_specific_reason(error, expected):
    assert expected in failure_message(error)


@pytest.mark.parametrize("error", [RuntimeError("intern: geheim"), ValueError(""), KeyError("x")])
def test_unknown_failures_keep_the_generic_reason_without_details(error):
    assert failure_message(error) == GENERIC_FAILURE


def test_a_failure_without_logger_still_records_the_reason(tmp_path):
    harness = RuleHarness(tmp_path)
    harness.log(record())
    harness.analyze()
    harness.analyzer.error = RuntimeError("boom")
    assert harness.service.tick()
    assert harness.service.state("web:a").message == GENERIC_FAILURE


def test_decisions_left_out_by_the_payload_limit_are_counted(rules):
    rules.log(*large(3, 3000))
    rules.analyzer.result = RuleAnalysis(proposals=[proposal(evidence=["decision-2"])])
    rules.limit = 2000  # one decision fits (about 1.4 KB), two do not
    state = rules.service.state("web:a")
    rules.service.change("web:a", state.version, "analyze-trim", "analyze", {"confirm": True, "scope": "all"})
    assert rules.service.tick()
    state = rules.service.state("web:a")
    assert state.status == "review" and state.trimmed == 2 and [item["id"] for item in state.evidence] == ["decision-2"]
