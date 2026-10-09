"""Experimental Laya relevance check against a simulated Ollama server."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from mailhelp.adapter import PermanentError
from mailhelp.config import Topic
from mailhelp.decisions import DecisionResponseError
from mailhelp.laya import (MAX_TOPICS, LayaClient, LayaPrompts, LayaRelevanceAnalyzer, LayaStateTooLong,
                           load_laya_prompts)

ROOT = Path(__file__).resolve().parents[1]
MODEL = "laya:322m-multilingual-mlx-fp16"
TOPICS = [Topic(id="wohnung", name="Wohnung", enabled=True, description="Mietverhältnis"),
          Topic(id="verein", name="Vereinsleben", enabled=True, description="Vereine"),
          Topic(id="aus", name="Abgeschaltet", enabled=False, description="Synthetisch")]
IRRELEVANT = [Topic(id="werbung", name="Werbung", enabled=True, description="Rabatte"),
              Topic(id="pakete", name="Pakete", enabled=True, description="Versand"),
              Topic(id="alt", name="Alt", enabled=False, description="Synthetisch")]
OTHER = "None of these topics: advertising, newsletters, notifications or anything else."
NOUL = {"type": "noul", "instructions": "Synthetic?", "criteria": {"true": "Ja.", "false": "Nein."}}


def prompts(**changes):
    value = load_laya_prompts(ROOT / "missing").model_dump()
    value.update(changes)
    return LayaPrompts.model_validate(value)


def client(handler):
    return LayaClient("mac.example.test", 11434, MODEL, 5, 0, 100, transport=httpx.MockTransport(handler))


def test_shipped_template_matches_the_editable_copy_and_is_loaded_as_fallback(tmp_path):
    assert (ROOT / "laya_prompts.yaml").read_text(encoding="utf-8") == (
        ROOT / "src" / "mailhelp" / "defaults" / "laya_prompts.yaml").read_text(encoding="utf-8")
    shipped = load_laya_prompts(tmp_path)
    assert (shipped.model, shipped.max_state_characters, shipped.max_option_characters) == (MODEL, 900, 90)
    assert (shipped.rotations, shipped.topic_option, shipped.other_option) == (3, "{name}: {description}", OTHER)
    assert (shipped.irrelevant_threshold, shipped.relevant_threshold, shipped.topic_threshold) == (0.75, 0.9, 0.2)
    (tmp_path / "laya_prompts.yaml").write_text(
        (ROOT / "laya_prompts.yaml").read_text(encoding="utf-8").replace(MODEL, "laya:latest"),
        encoding="utf-8")
    assert load_laya_prompts(tmp_path).model == "laya:latest"


@pytest.mark.parametrize("changes,message", [
    ({"topic_option": "Ohne Platzhalter"}, "topic_option"),
    ({"irrelevant_threshold": 0.95}, "irrelevant_threshold darf relevant_threshold nicht übersteigen"),
    ({"rotations": 0}, "rotations"),
    ({"rotations": 11}, "rotations"),
    ({"max_option_characters": 10}, "max_option_characters"),
    ({"instructions": ""}, "instructions"),
    ({"model": "a b"}, "model"),
    ({"max_state_characters": 50}, "max_state_characters"),
])
def test_invalid_laya_prompts_are_rejected(changes, message):
    with pytest.raises(ValueError, match=message):
        prompts(**changes)


def test_client_posts_to_systemone_without_credentials_and_accepts_answers_without_id():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": MODEL}]})
        data = json.loads(request.content)
        return httpx.Response(200, json={"model": data["model"],
                                         "answers": {"topic_0": {"type": "noul", "noul": 0.9}}})

    laya = client(handler)
    laya.check_access()
    call_id, raw = laya.decide(MODEL, "Text", {"topic_0": NOUL}, stage="relevance", max_payload_bytes=100_000)
    laya.close()
    assert call_id and raw["answers"]["topic_0"]["noul"] == 0.9
    assert [request.url.path for request in seen] == ["/api/tags", "/v1/systemone"]
    assert str(seen[1].url) == "http://mac.example.test:11434/v1/systemone"
    assert all("authorization" not in request.headers for request in seen)
    assert seen[1].headers["x-request-id"] == call_id
    assert laya.service_name == "Laya (lokal, experimentell)"


def test_client_reports_missing_model_invalid_answers_and_too_long_states():
    def missing(request):
        return httpx.Response(200, json={"models": [{"name": "gemma4:31b"}]})

    with pytest.raises(ValueError, match="ollama pull laya:322m"):
        client(missing).check_access()

    def wrong(request):
        return httpx.Response(200, json={"answers": {"topic_0": {"type": "choice", "choice": "true"}}})

    with pytest.raises(DecisionResponseError):
        client(wrong).decide(MODEL, "Text", {"topic_0": NOUL}, stage="relevance", max_payload_bytes=100_000)

    def too_long(request):
        return httpx.Response(400, json={"error": "question 0: state has 811 tokens; limit is 772 with this question"})

    with pytest.raises(LayaStateTooLong) as caught:
        client(too_long).decide(MODEL, "Text", {"topic_0": NOUL}, stage="relevance", max_payload_bytes=100_000)
    assert (caught.value.tokens, caught.value.limit) == (811, 772)

    # Other bad requests stay ordinary HTTP errors.
    for response in (httpx.Response(400, json={"error": "option 9 has 52 tokens; limit is 48"}),
                     httpx.Response(400, text="kein JSON"), httpx.Response(400, json=["liste"])):
        with pytest.raises(PermanentError):
            client(lambda request, response=response: response).decide(
                MODEL, "Text", {"topic_0": NOUL}, stage="relevance", max_payload_bytes=100_000)


class FakeClient:
    """Answers each order with the given probabilities per option text prefix."""

    def __init__(self, by_option, fail_first=None):
        self.by_option, self.fail_first, self.calls = by_option, fail_first, []

    def decide(self, model, state, questions, *, stage, max_payload_bytes):
        self.calls.append((model, state, questions, stage, max_payload_bytes))
        if self.fail_first and len(self.calls) == 1:
            raise self.fail_first
        answers = {}
        for name, question in questions.items():
            probabilities = {letter: next(value for prefix, value in self.by_option.items()
                                          if text.startswith(prefix))
                             for letter, text in question["criteria"].items()}
            answers[name] = {"type": "choice", "choice": max(probabilities, key=probabilities.get),
                             "confidence": 0.5, "probabilities": probabilities}
        return "call", {"answers": answers}


def mail(text="Mailtext"):
    return {"headers": {"from": "a@example.test", "subject": "Betreff"}, "text": text}


def test_one_rotated_choice_is_built_at_runtime_from_enabled_topics():
    fake = FakeClient({"Wohnung": 0.7, "Vereinsleben": 0.25, "None": 0.05})
    analyzer = LayaRelevanceAnalyzer(fake, prompts(), 4096, IRRELEVANT)
    call, result = analyzer.relevance(mail(), TOPICS)
    model, state, questions, stage, limit = fake.calls[0]
    assert (call, model, stage, limit) == ("call", MODEL, "relevance", 4096)
    assert state == "From: a@example.test\nSubject: Betreff\n\nMailtext"
    # Neutral letter keys; each order shifts the options and every second one is reversed.
    assert questions == {
        "order_0": {"type": "choice", "instructions": "Which topic is this email about?", "criteria": {
            "A": "Wohnung: Mietverhältnis", "B": "Vereinsleben: Vereine", "C": OTHER}},
        "order_1": {"type": "choice", "instructions": "Which topic is this email about?", "criteria": {
            "A": "Wohnung: Mietverhältnis", "B": OTHER, "C": "Vereinsleben: Vereine"}},
        "order_2": {"type": "choice", "instructions": "Which topic is this email about?", "criteria": {
            "A": OTHER, "B": "Wohnung: Mietverhältnis", "C": "Vereinsleben: Vereine"}}}
    assert (result.decision, result.topic_ids) == ("relevant", ["wohnung", "verein"])
    assert result.reason == 'Laya: P(Thema)=0.95; {"wohnung": 0.7, "verein": 0.25}'


def test_options_are_shortened_and_can_list_irrelevant_categories():
    analyzer = LayaRelevanceAnalyzer(None, prompts(max_option_characters=30, rotations=1,
                                                   other_option="Keines: {irrelevant}"), 4096, IRRELEVANT)
    long = Topic(id="lang", name="Lang", enabled=True, description="Ein Wort " * 10 + "{name}")
    options = analyzer.options([long, Topic(id="k", name="Kurz", enabled=True, description="{name} bleibt")])
    assert options == {"lang": "Lang: Ein Wort Ein Wort Ein…", "k": "Kurz: {name} bleibt",
                       "other": "Keines: Werbung, Pakete"}


def test_too_many_topics_are_rejected_before_any_request():
    many = [Topic(id=f"t{index}", name=f"T{index}", enabled=True, description="x") for index in range(MAX_TOPICS + 1)]
    fake = FakeClient({})
    with pytest.raises(ValueError, match="höchstens 25"):
        LayaRelevanceAnalyzer(fake, prompts(), 4096, []).relevance(mail(), many)
    assert fake.calls == []


def test_a_too_long_state_is_shortened_once_in_proportion():
    fake = FakeClient({"Wohnung": 0.97, "Vereinsleben": 0.0, "None": 0.03}, fail_first=LayaStateTooLong(1000, 500))
    analyzer = LayaRelevanceAnalyzer(fake, prompts(), 4096, [])
    _, result = analyzer.relevance(mail("x" * 2000), TOPICS)
    first, second = fake.calls[0][1], fake.calls[1][1]
    assert len(first) == 900 and len(second) == 900 * 500 * 9 // (1000 * 10) == 405
    assert result.decision == "relevant"
    # A second rejection is not retried again.
    again = FakeClient({}, fail_first=LayaStateTooLong(1000, 500))
    again.decide = lambda *args, **kwargs: (_ for _ in ()).throw(LayaStateTooLong(900, 500))
    with pytest.raises(LayaStateTooLong):
        LayaRelevanceAnalyzer(again, prompts(), 4096, []).relevance(mail(), TOPICS)


def test_state_drops_links_quotes_and_footnotes_and_is_truncated():
    analyzer = LayaRelevanceAnalyzer(None, prompts(max_state_characters=100), 4096, [])
    text = ("Hallo,\n\nsiehe https://track.example.test/?id=" + "x" * 300 + " bitte.\n"
            "> zitierte Zeile\nLinks:\n------\n[1]\n=====\nGrüße")
    assert analyzer.state(mail(text)) == (
        "From: a@example.test\nSubject: Betreff\n\nHallo,\nsiehe  bitte.\nGrüße")
    assert analyzer.state({"text": "nur Text"}) == "From: \nSubject: \n\nnur Text"
    assert len(analyzer.state(mail("y" * 500))) == 100
    assert len(analyzer.state(mail("y" * 500), 60)) == 60


@pytest.mark.parametrize("by_option,expected,ids", [
    ({"Wohnung": 0.9, "Vereinsleben": 0.0, "None": 0.1}, "relevant", ["wohnung"]),
    ({"Wohnung": 0.89, "Vereinsleben": 0.0, "None": 0.11}, "unclear", ["wohnung"]),
    ({"Wohnung": 0.75, "Vereinsleben": 0.0, "None": 0.25}, "unclear", ["wohnung"]),
    ({"Wohnung": 0.74, "Vereinsleben": 0.0, "None": 0.26}, "irrelevant", []),
    # P(Thema) is high but spread so thinly that no topic reaches topic_threshold.
    ({"Wohnung": 0.19, "Vereinsleben": 0.19, "None": 0.62}, "irrelevant", []),
])
def test_three_zone_rule_on_the_averaged_probabilities(by_option, expected, ids):
    _, result = LayaRelevanceAnalyzer(FakeClient(by_option), prompts(), 4096, []).relevance(mail(), TOPICS)
    assert (result.decision, result.topic_ids) == (expected, ids)


def test_relevant_needs_a_topic_above_the_topic_threshold():
    topics = [Topic(id=f"t{index}", name=f"T{index}", enabled=True, description="x") for index in range(6)]
    by_option = {f"T{index}": 0.16 for index in range(6)}
    by_option["None"] = 0.04
    _, result = LayaRelevanceAnalyzer(FakeClient(by_option), prompts(), 4096, []).relevance(mail(), topics)
    assert (result.decision, result.topic_ids) == ("unclear", [])
