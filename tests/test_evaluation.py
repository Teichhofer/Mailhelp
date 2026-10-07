"""The opt-in evaluator itself is tested without a network or real key."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml

from mailhelp.evaluation import BoundedCompleter, EvaluationBudgetExceeded, evaluate, main
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
    monkeypatch.setattr("mailhelp.evaluation.OpenRouterClient", lambda *args: provider)
    assert main(args) == 0 and provider.closed
    assert json.loads(output.read_text(encoding="utf-8"))["passed"]
    provider.wrong = True
    assert main(args) == 1
    provider.closed = False
    with pytest.raises(IsADirectoryError if __import__('os').name != 'nt' else PermissionError):
        main(["--output", str(tmp_path), *args[:args.index("--output")], "--max-calls", "1"])
    assert provider.closed
