"""4.8, step 19.3: the router decides whether the sender expects a written reply."""
import json
from pathlib import Path

import yaml

from mailhelp.llm.evaluation import semantic_result
from mailhelp.models import ActionRoute, ActionRouteAnswer
from mailhelp.processing.analysis import Analyzer
from mailhelp.proposals.action_normalization import MailDateContext
from tests.fakes.shared_core import prompt_config

CORPUS = Path("tests/fixtures/mail_corpus_v3/corpus.json")


class Answers:
    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def complete(self, model, parameters, system, payload, **metadata):
        self.requests.append(metadata)
        return "call", self.answers.pop(0)


def test_the_model_schema_requires_the_reply_decision():
    schema = ActionRouteAnswer.model_json_schema()
    assert {"reply_needed", "reply_reason"} <= set(schema["required"]) and "description" not in schema


def test_a_reply_need_and_its_reason_reach_the_route():
    client = Answers({"action_state": "none", "task_count": 0, "event_count": 0, "reason": "Frage",
                      "reply_needed": True, "reply_reason": "Die Frage nach dem Liefertermin beantworten."})
    _, route = Analyzer(client, prompt_config(), 0).action_route({"text": "Wann liefern Sie?"})
    assert (route.reply_needed, route.reply_reason) == (True, "Die Frage nach dem Liefertermin beantworten.")
    assert client.requests[0]["response_schema"] is ActionRouteAnswer


def test_stored_routes_and_providers_without_schema_default_to_no_reply():
    old = ActionRoute.model_validate({"action_state": "none", "task_count": 0, "event_count": 0, "reason": "x"})
    assert (old.reply_needed, old.reply_reason) == (False, None)
    client = Answers({"action_state": "none", "task_count": 0, "event_count": 0, "reason": "x"})
    assert Analyzer(client, prompt_config(), 0).action_route({"text": "x"})[1].reply_needed is False


def test_the_evaluation_compares_the_reply_need():
    context = MailDateContext(date_context_status="missing", date_header_parsed=None, imap_received_at=None,
                              user_timezone=None)
    route = {"action_state": "none", "task_count": 0, "event_count": 0, "reason": "x"}
    assert semantic_result("action_router", route, context)["reply_needed"] is False
    assert semantic_result("action_router", {**route, "reply_needed": True}, context)["reply_needed"] is True


def test_the_corpus_expects_a_reply_only_where_the_sender_asks_for_one():
    cases = {case["id"]: case for case in json.loads(CORPUS.read_text(encoding="utf-8"))["cases"]}
    replying = {case_id for case_id, case in cases.items() if case["expected"]["action_route"]["reply_needed"]}
    assert replying == {"04_task_and_event", "07_relative_deadline", "15_invitation_optional_greeting",
                        "21_jimdo_inquiry"}
    assert all(cases[case_id]["expected"]["action_route"]["reply_reason"] for case_id in replying)
    assert not any(cases[case_id]["expected"]["action_route"]["reply_needed"]
                   for case_id in ("16_invitation_feedback_other", "14_invitation_registration",
                                   "32_self_note_photo_invitation", "12_prompt_injection", "22_jimdo_newsletter"))


def test_the_router_prompt_defines_the_reply_need():
    prompt = " ".join(yaml.safe_load(Path("prompts.yaml").read_text(encoding="utf-8"))["prompts"][
        "action_router"]["system_prompt"].split())
    assert "genau sechs Feldern" in prompt and '"reply_needed": true oder false' in prompt
    assert "ausdrücklich eine schriftliche Antwort per Mail erwartet" in prompt
    assert "er ändert weder action_state noch die Zähler" in prompt
    assert prompt.count('"reply_needed":false,"reply_reason":null') == 2  # both examples show the new fields
