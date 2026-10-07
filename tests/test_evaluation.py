"""The opt-in evaluator itself is tested without a network or real key."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml

from mailhelp.action_normalization import MailDateContext
from mailhelp.evaluation import (BoundedCompleter, EvaluationBudgetExceeded, UsageRecorder, evaluate,
                                 main, semantic_result, write_report)
from test_quality_corpus import load_corpus, prompt_config


def prompts():
    value = prompt_config()
    value.defaults["parameters"]["max_tokens"] = 1000
    return value


class Provider:
    def __init__(self, corpus, wrong=False):
        self.cases = {case["raw_email"].split("Subject: ")[1].split("\n")[0]: case
                      for case in corpus["cases"]}
        self.wrong = wrong
        self.closed = False
    def complete(self, model, parameters, system, payload, **kwargs):
        assert "expected" not in payload
        stage = system.removeprefix("quality:")
        mail = payload.get("mail", payload)
        expected = self.cases[mail["headers"]["subject"]]["expected"]
        value = deepcopy(expected[{"action_router": "action_route"}.get(stage, stage)])
        if self.wrong and stage == "relevance":
            value = {"decision": "unclear", "topic_ids": [], "reason": "deliberate wrong result"}
        return "synthetic-call", value
    def close(self): self.closed = True


def test_real_evaluation_path_detects_wrong_model_answers_and_records_routes():
    corpus = load_corpus()
    report = evaluate(corpus, prompts(), Provider(corpus), 200)
    assert report["passed"] and report["complete"]
    assert len(report["cases"]) == len(corpus["cases"])
    assert report["routes"]["summary"][0]["model"] == "simulated/openrouter"
    assert len(report["prompt_fingerprint"]) == len(report["corpus_fingerprint"]) == 64
    bad = evaluate(corpus, prompts(), Provider(corpus, wrong=True), 200)
    assert not bad["passed"]
    assert not bad["cases"][0]["stages"]["relevance"]["passed"]


def test_budget_and_error_reports_never_expose_provider_errors():
    corpus = load_corpus()
    report = evaluate(corpus, prompts(), Provider(corpus), 1)
    assert not report["complete"] and not report["passed"] and report["calls"] == 1
    assert report["cases"][0]["error"] == "EvaluationBudgetExceeded"
    class Broken:
        def complete(self, *args, **kwargs): raise RuntimeError("secret-must-not-appear")
    report = evaluate(corpus, prompts(), Broken(), 2)
    assert "secret-must-not-appear" not in json.dumps(report)
    assert report["cases"][0]["error"] == "RuntimeError"
    with pytest.raises(ValueError): BoundedCompleter(Broken(), 0)
    for tokens in (None, True, 0, 16001):
        bounded = BoundedCompleter(Broken(), 1)
        with pytest.raises(ValueError): bounded.complete("m", {"max_tokens": tokens}, "s", {})
        assert bounded.calls == 0


def test_cli_requires_explicit_network_budget_and_key_and_always_closes(tmp_path, monkeypatch):
    corpus = load_corpus()
    source = tmp_path / "corpus.json"
    prompt_file = tmp_path / "prompts.yaml"
    output = tmp_path / "report.json"
    source.write_text(json.dumps(corpus), encoding="utf-8")
    prompt_file.write_text(yaml.safe_dump(prompts().model_dump(mode="json")), encoding="utf-8")
    args = ["--allow-network", "--corpus", str(source), "--prompts", str(prompt_file),
            "--output", str(output), "--max-calls", "200"]
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(SystemExit): main(args)
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-key")
    with pytest.raises(SystemExit): main(args[1:])
    with pytest.raises(SystemExit): main([*args[:-1], "0"])
    provider = Provider(corpus)
    created = []

    def client(*args, **kwargs):
        created.append(kwargs["logger"])
        return provider

    monkeypatch.setattr("mailhelp.evaluation.OpenRouterClient", client)
    assert main(args) == 0 and provider.closed
    assert json.loads(output.read_text(encoding="utf-8"))["passed"]
    provider.wrong = True
    assert main(args) == 1
    # An unusable report path fails before any client exists or a paid call is made.
    created.clear()
    with pytest.raises(OSError):
        main(["--output", str(tmp_path), *args[:args.index("--output")], "--max-calls", "1"])
    assert created == [] and not list(tmp_path.glob("*.tmp"))


CORPUS_V2 = Path(__file__).parent / "fixtures" / "mail_corpus_v2" / "corpus.json"


def load_corpus_v2():
    return json.loads(CORPUS_V2.read_text(encoding="utf-8"))


class AlternativeProvider(Provider):
    """Answer with the first accepted alternative of a stage where one exists."""

    def complete(self, model, parameters, system, payload, **kwargs):
        stage = system.removeprefix("quality:")
        mail = payload.get("mail", payload)
        case = self.cases[mail["headers"]["subject"]]
        key = {"action_router": "action_route"}.get(stage, stage)
        alternatives = case.get("accept", {}).get(key)
        return "synthetic-call", deepcopy(alternatives[0] if alternatives else case["expected"][key])


def test_corpus_v2_is_consistent_and_accepts_only_declared_alternatives():
    corpus = load_corpus_v2()
    assert corpus["schema_version"] == 2 and len(corpus["cases"]) == 17
    assert all(case["received_at"] for case in corpus["cases"])
    report = evaluate(corpus, prompts(), Provider(corpus), 200)
    assert report["passed"] and report["stage_pass_counts"]["summary"] == 17
    alternative = evaluate(corpus, prompts(), AlternativeProvider(corpus), 200)
    assert alternative["passed"]
    assert any(case["stages"]["action_router"]["accepted_alternatives"]
               for case in alternative["cases"])
    wrong = evaluate(corpus, prompts(), Provider(corpus, wrong=True), 200)
    assert wrong["stage_pass_counts"]["relevance"] == 0 and not wrong["passed"]


def context():
    return MailDateContext("valid", "2026-09-18T10:00:00+02:00",
                           "2026-09-18T10:01:00+02:00", "Europe/Berlin")


def raw_task(**changes):
    value = {"title": "Aufgabe", "description": "", "evidence": "Beleg", "responsibility": "user",
             "certainty": "certain", "classification": "new", "due_text": None}
    value.update(changes)
    return value


def test_semantic_comparison_uses_application_normalization():
    ctx = context()
    tasks = lambda *items: semantic_result("task_extraction", {"tasks": list(items)}, ctx)
    assert tasks(raw_task(due_text="bis 01.10.2026")) == tasks(raw_task(due_text="01.10.2026"))
    assert tasks(raw_task(evidence="Bitte bis 2026-09-30 einreichen.")) == tasks(
        raw_task(due_text="2026-09-30"))
    assert tasks(raw_task(due_text="bis nächsten Freitag")) == tasks(
        raw_task(due_text="Nächsten  Freitag"))
    assert tasks(raw_task(), raw_task(responsibility="other")) == tasks(
        raw_task(responsibility="other"), raw_task())
    event = {"title": "T", "description": None, "evidence": "E", "date_text": "Jeden Montag",
             "time_text": None, "end_time_text": None, "location": "Raum 1", "video_link": None,
             "responsibility": "user", "certainty": "certain", "classification": "recurring",
             "time_requirement": "required_unknown"}
    events = lambda *items: semantic_result("event_extraction", {"events": list(items)}, ctx)
    assert events(event) == events({**event, "date_text": "jeden  montag", "location": "Raum 2"})
    assert events(event) != events({**event, "location": None})
    timed = {**event, "date_text": "24.09.2026", "time_text": "09:00", "end_time_text": "10:00",
             "classification": "new", "time_requirement": "timed"}
    assert events(timed)["events"][0]["when"] == {
        "start": "2026-09-24T09:00:00+02:00", "end": "2026-09-24T10:00:00+02:00", "all_day": False}
    summary = lambda *deadlines: semantic_result(
        "summary", {"sentences": ["Satz."], "deadlines": list(deadlines)}, ctx)
    assert summary("bis 25.09.2026", "25.09.2026") == summary("2026-09-25")
    assert summary("Nächsten Freitag") == summary("nächster Freitag")
    assert summary("24.09.2026, 09:00–10:00 Uhr") == summary("Termin am 24.09.2026")
    assert summary("25.09.2026 und 1. Oktober 2026")["deadlines"] == ["2026-09-25", "2026-10-01"]
    assert summary("31.02.2027")["deadlines"] == ["31.02.2027"]
    assert summary("jeden Montag")["deadlines"] == ["<ohne Datum>"]
    assert summary()["deadlines"] == []


def test_usage_recorder_sums_reported_tokens_and_cost_without_content():
    usage = UsageRecorder()
    usage.event("INFO", "openrouter", "ignored", secret="x")
    usage.llm_event("token_usage_recorded", token_usage={
        "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cost": "n/a"})
    usage.llm_event("token_usage_recorded", token_usage={"prompt_tokens": True})
    usage.llm_event("token_usage_recorded", token_usage=None)
    usage.llm_event("response_received", response={"content": "geheim"}, reported_cost=0.25)
    usage.llm_event("response_received", reported_cost="0.5")
    usage.llm_event("request_started", request={"messages": "geheim"})
    assert usage.report() == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
                              "reported_cost": 0.25, "responses_without_usage": 1}
    assert "geheim" not in json.dumps(usage.report())


def test_cli_writes_progress_and_partial_reports(tmp_path, monkeypatch, capsys):
    corpus = load_corpus_v2()
    corpus["cases"] = corpus["cases"][:2]
    source, prompt_file, output = (tmp_path / "c.json", tmp_path / "p.yaml", tmp_path / "r.json")
    source.write_text(json.dumps(corpus), encoding="utf-8")
    prompt_file.write_text(yaml.safe_dump(prompts().model_dump(mode="json")), encoding="utf-8")
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-key")
    snapshots = []
    real_write = write_report

    def recording(path, report):
        snapshots.append(json.loads(json.dumps(report)))
        real_write(path, report)

    monkeypatch.setattr("mailhelp.evaluation.write_report", recording)
    provider = Provider(corpus)
    monkeypatch.setattr("mailhelp.evaluation.OpenRouterClient", lambda *a, **k: provider)
    assert main(["--allow-network", "--corpus", str(source), "--prompts", str(prompt_file),
                 "--output", str(output), "--max-calls", "50"]) == 0
    assert [len(item["cases"]) for item in snapshots] == [0, 1, 2, 2]
    assert snapshots[1]["complete"] is False and "usage" in snapshots[1]
    final = json.loads(output.read_text(encoding="utf-8"))
    assert final["complete"] and final["usage"]["total_tokens"] == 0
    err = capsys.readouterr().err
    assert "[1/2] 01_no_action: bestanden (Aufrufe 3/50)" in err
    provider.wrong = True
    main(["--allow-network", "--corpus", str(source), "--prompts", str(prompt_file),
          "--output", str(output), "--max-calls", "50"])
    assert "[1/2] 01_no_action: abweichend" in capsys.readouterr().err
