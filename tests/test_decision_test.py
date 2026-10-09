"""Paired analysis never constructs write adapters or changes normal state."""
from copy import deepcopy
from datetime import datetime, timezone
import base64
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import httpx
import pytest
import yaml

from mailhelp import cli
from mailhelp.config import Secrets, Settings, Topic
from mailhelp.decision_test import ComparisonRecorder, DecisionTestMode, _raw_mail, run_decision_test as _run_decision_test
from mailhelp.decisions import DecisionClient
from mailhelp.imap import FetchedMail, FolderNotReadable, MailCandidate
from mailhelp.models import ActionRoute, Relevance, Summary, TaskExtraction, EventExtraction
from mailhelp.openrouter import OpenRouterClient
from mailhelp.ollama import LocalLlm, OllamaClient
from test_decisions import ROOT, envelope
from test_quality_corpus import prompt_config


LOCAL = LocalLlm("ollama.example.test", 11434, "synthetic/local", 8192)


def run_decision_test(*args, **kwargs):
    return _run_decision_test(*args, local_llm=LOCAL, **kwargs)


NOW = datetime(2026, 10, 8, 10, tzinfo=timezone.utc)
RAW = b"From: sender@example.test\r\nSubject: Synthetic comparison\r\nDate: Thu, 08 Oct 2026 10:00:00 +0000\r\n\r\nBitte Anmeldung bestaetigen. Treffen am 9.10.2026 um 10:00 Uhr."


def settings():
    data = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    data["imap"]["folders"] = ["INBOX", "Optional"]
    return Settings.model_validate(data)


def secrets():
    return Secrets.model_validate({name: "synthetic-" + name for name in Secrets.model_fields})


def topics():
    return [Topic(id="billing", name="Abrechnung", enabled=True, description="Synthetic")]


class Reader:
    def __init__(self, *args, **kwargs):
        self.closed = False
        self.discovery = []
        self.fetched = []
    def close(self):
        self.closed = True
    def discover_since(self, folder, **kwargs):
        self.discovery.append((folder, kwargs))
        return [MailCandidate(folder, 1, uid, "a", NOW) for uid in (1, 2)]
    def fetch_uid(self, folder, uid, validity):
        self.fetched.append((folder, uid, validity))
        return FetchedMail(folder, validity, uid, RAW + str(uid).encode(), received_at=NOW)


def llm_response(request, *, none=False, decision="relevant"):
    payload = json.loads(request.content)
    stage = payload["messages"][0]["content"].removeprefix("quality:").split("\n")[0]
    outputs = {
        "relevance": {"decision": decision, "topic_ids": ["billing"] if decision == "relevant" else [], "reason": "Synthetic"},
        "summary": {"sentences": ["Eine synthetische Zusammenfassung."], "deadlines": []},
        "action_router": {"action_state": "none" if none else "task_and_event",
                          "task_count": 0 if none else 1, "event_count": 0 if none else 1, "reason": "Synthetic"},
        "task_extraction": {"schema_version": 1, "tasks": []},
        "event_extraction": {"schema_version": 1, "events": []},
    }
    return httpx.Response(200, json={"id": "synthetic-chat", "provider": "Synthetic",
        "choices": [{"message": {"content": json.dumps(outputs[stage])}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cost": 0.002}})


def configure(tmp_path, monkeypatch, *, none=False, imap_mode="ssl", fail_client=False,
              jev="relevant", fallback="relevant", local="relevant"):
    (tmp_path / "decisions_prompts.yaml").write_bytes((ROOT / "decisions_prompts.yaml").read_bytes())
    cfg = settings()
    cfg.imap.connection_mode = imap_mode
    reader = Reader()
    clients, requests, reader_options = [], [], []
    def reader_factory(*args, **kwargs):
        reader_options.append(kwargs)
        return reader
    def make_client(kind):
        def construct(*args, **kwargs):
            if fail_client and kind is DecisionClient:
                raise RuntimeError("synthetic construction failure")
            def handler(request):
                requests.append((kind, request))
                if kind is OpenRouterClient:
                    return llm_response(request, none=none, decision=fallback)
                if kind is OllamaClient:
                    assert request.url.host == LOCAL.host
                    assert "Authorization" not in request.headers
                    value = llm_response(request, decision=local).json()
                    return httpx.Response(200, json={
                        "model": LOCAL.model, "done": True, "done_reason": "stop",
                        "message": {"role": "assistant", "content": value["choices"][0]["message"]["content"]},
                        "prompt_eval_count": 10, "eval_count": 5})
                data = json.loads(request.content)
                return httpx.Response(200, json=envelope(data["questions"], {
                    "decision": jev, "topic_0": "match" if jev == "relevant" else "no_match",
                    "action_state": "task_and_event",
                    "task_count": "1", "event_count": "1"}))
            client = kind(*args, **kwargs, transport=httpx.MockTransport(handler), sleep=lambda delay: None)
            clients.append(client)
            return client
        return construct
    monkeypatch.setattr("mailhelp.decision_test.ImapReader", reader_factory)
    monkeypatch.setattr("mailhelp.decision_test.OpenRouterClient", make_client(OpenRouterClient))
    monkeypatch.setattr("mailhelp.decision_test.DecisionClient", make_client(DecisionClient))
    monkeypatch.setattr("mailhelp.decision_test.OllamaClient", make_client(OllamaClient))
    return cfg, reader, clients, requests, reader_options


@pytest.mark.parametrize("imap_mode,ignore", [("ssl", False), ("starttls", True), ("plain", False)])
def test_paired_full_pipeline_raw_reports_unique_selection_and_no_state_writes(tmp_path, monkeypatch,
                                                                               imap_mode, ignore):
    cfg, reader, clients, requests, reader_options = configure(tmp_path, monkeypatch, imap_mode=imap_mode)
    marker = tmp_path / "data/production/state.json"
    marker.parent.mkdir(parents=True)
    marker.write_text('{"untouched":true}', encoding="utf-8")
    config_before = (tmp_path / "decisions_prompts.yaml").read_bytes()
    assert run_decision_test(cfg, secrets(), topics(), prompt_config(), 2, tmp_path,
                             ignore_historical_start=ignore) == 0
    files = list((tmp_path / "data/decision-tests").glob("*.json"))
    assert len(files) == 1
    report = json.loads(files[0].read_text(encoding="utf-8"))
    assert report["complete"] and report["count_satisfied"]
    assert report["schema_version"] == 2 and report["comparison"] == "standard_vs_ollama"
    assert report["ollama"]["model"] == LOCAL.model
    assert report["requested_mail_count"] == report["selected_mail_count"] == 2
    assert report["decisions_prompts"]["model"] == "typesafe/jev-1.13"
    assert [record["uid"] for record in report["mails"]] == [2, 1]
    assert [record["folder"] for record in report["mails"]] == ["INBOX", "INBOX"]
    for record in report["mails"]:
        assert base64.b64decode(record["raw_rfc822_base64"]) == RAW + str(record["uid"]).encode()
        assert record["prepared_mail"]["headers"]["subject"] == "Synthetic comparison"
        assert record["status"] == "completed"
        assert set(record["paths"]) == {"standard", "ollama"}
        for path in record["paths"].values():
            assert path["status"] == "completed" and path["would_process_in_normal_mode"]
            assert len(path["stages"]) == 5
            assert all(stage["status"] == "completed" for stage in path["stages"].values())
            assert any(event["event"] == "http_response" for event in path["stages"]["relevance"]["events"])
    state_payloads = [json.loads(request.content)["state"]["mail"]
                      for kind, request in requests if kind is DecisionClient]
    llm_payloads = [json.loads(json.loads(request.content)["messages"][1]["content"])["mail"]
                    for kind, request in requests if kind is OpenRouterClient]
    assert all(mail in llm_payloads for mail in state_payloads)
    assert marker.read_text(encoding="utf-8") == '{"untouched":true}'
    assert (tmp_path / "decisions_prompts.yaml").read_bytes() == config_before
    assert reader.closed and all(client.client.is_closed for client in clients)
    assert reader_options[0]["starttls"] == (imap_mode == "starttls")
    assert reader.discovery[0][1]["historical_start"] == (None if ignore else cfg.imap.historical_start)
    assert files[0].with_suffix(".json.jsonl").is_file()
    # Repeated invocation with a new output compares again without normal checkpoints.
    assert run_decision_test(cfg, secrets(), topics(), prompt_config(), 1, tmp_path,
                             Path("second.json")) == 0
    assert json.loads((tmp_path / "second.json").read_text(encoding="utf-8"))["selected_mail_count"] == 1


def test_baseline_routing_misses_are_visible_in_new_path(tmp_path, monkeypatch):
    cfg, *_ = configure(tmp_path, monkeypatch, none=True)
    assert run_decision_test(cfg, secrets(), topics(), prompt_config(), 1, tmp_path, Path("test.json")) == 0
    record = json.loads((tmp_path / "test.json").read_text(encoding="utf-8"))["mails"][0]
    assert record["paths"]["standard"]["stages"]["task_extraction"] == {
        "status": "skipped", "reason": "no_candidates"}
    assert record["paths"]["ollama"]["stages"]["task_extraction"]["status"] == "completed"


def test_output_protection_happens_before_external_connections(tmp_path, monkeypatch):
    cfg, reader, clients, requests, _ = configure(tmp_path, monkeypatch)
    output = tmp_path / "protected.json"
    output.write_text("preserved", encoding="utf-8")
    with pytest.raises(FileExistsError):
        run_decision_test(cfg, secrets(), topics(), prompt_config(), 1, tmp_path, output)
    assert output.read_text(encoding="utf-8") == "preserved"
    assert not clients and not requests and not reader.discovery


def test_construction_failure_closes_successfully_created_resources(tmp_path, monkeypatch):
    cfg, reader, clients, *_ = configure(tmp_path, monkeypatch, fail_client=True)
    with pytest.raises(RuntimeError):
        run_decision_test(cfg, secrets(), topics(), prompt_config(), 1, tmp_path, Path("report.json"))
    assert reader.closed and clients[0].client.is_closed
    assert json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))["complete"] is False


class AnalyzerStub:
    def __init__(self, *, fail=(), irrelevant=False, interrupted=False, unclear=False):
        self.fail, self.irrelevant, self.interrupted = fail, irrelevant, interrupted
        self.unclear = unclear
        self.calls = []
    def result(self, name, value):
        self.calls.append(name)
        if self.interrupted:
            raise KeyboardInterrupt
        if name in self.fail:
            raise RuntimeError("synthetic-password must never appear")
        return "call", value
    def relevance(self, mail, topics):
        return self.result("relevance", Relevance(decision="unclear" if self.unclear else "irrelevant" if self.irrelevant else "relevant",
                           topic_ids=[] if self.irrelevant else ["billing"], reason="S"))
    def action_route(self, mail):
        return self.result("action_router", ActionRoute(action_state="task_and_event", task_count=1,
                                                       event_count=1, reason="S"))
    def summary(self, mail):
        return self.result("summary", Summary(sentences=["S"], deadlines=[]))
    def extract_tasks(self, mail, *, expected_count):
        assert expected_count == 1
        return self.result("task_extraction", TaskExtraction(tasks=[]))
    def extract_events(self, mail, *, expected_count):
        assert expected_count == 1
        return self.result("event_extraction", EventExtraction(events=[]))


def mode(tmp_path, reader=None, analyzer=None, decisions=None):
    output = tmp_path / "report.json"
    recorder = ComparisonRecorder(tmp_path / "events.jsonl", ("synthetic-password",))
    report = {"complete": False, "mails": [], "selection_errors": []}
    return DecisionTestMode(reader or Reader(), analyzer or AnalyzerStub(), decisions or AnalyzerStub(),
                            settings(), topics(), report, output, recorder)


def test_stage_errors_do_not_prevent_other_path_and_are_saved_without_error_text(tmp_path):
    runner = mode(tmp_path, analyzer=AnalyzerStub(fail={"relevance", "action_router", "summary"}),
                  decisions=AnalyzerStub(irrelevant=True))
    assert runner.run(1) == 1
    record = runner.report["mails"][0]
    assert record["paths"]["standard"]["status"] == "failed"
    assert record["paths"]["standard"]["stages"]["event_extraction"]["reason"] == "relevance_failed"
    assert record["paths"]["ollama"]["stages"]["relevance"]["status"] == "completed"
    assert not record["paths"]["ollama"]["would_process_in_normal_mode"]
    assert "synthetic-password" not in runner.output.read_text(encoding="utf-8")


def test_interruption_preserves_valid_partial_stage_data_for_review(tmp_path):
    runner = mode(tmp_path, analyzer=AnalyzerStub(interrupted=True))
    with pytest.raises(KeyboardInterrupt):
        runner.run(1)
    report = json.loads(runner.output.read_text(encoding="utf-8"))
    assert not report["complete"] and report["error_type"] == "KeyboardInterrupt"
    assert len(report["mails"]) == 1
    assert report["mails"][0]["paths"]["standard"]["stages"]["relevance"]["status"] == "running"


def test_optional_folder_failures_duplicates_fetch_errors_and_shortfall(tmp_path):
    class BrokenReader(Reader):
        def discover_since(self, folder, **kwargs):
            if folder == "Optional":
                raise FolderNotReadable(folder)
            return super().discover_since(folder, **kwargs)
        def fetch_uid(self, folder, uid, validity):
            if uid == 2:
                raise RuntimeError("unsafe provider diagnostic")
            return super().fetch_uid(folder, uid, validity)
    runner = mode(tmp_path, reader=BrokenReader())
    assert runner.run(2) == 1
    assert runner.report["complete"] and not runner.report["count_satisfied"]
    assert len(runner.report["selection_errors"]) == 2
    assert "unsafe provider diagnostic" not in runner.output.read_text(encoding="utf-8")
    # Duplicates across folders have the same raw fingerprint and are analyzed once.
    another = tmp_path / "another"
    another.mkdir()
    runner = mode(another)
    assert runner.run(3) == 1
    assert len(runner.report["mails"]) == 2


def test_required_folder_failure_is_not_silently_ignored(tmp_path):
    class BrokenReader(Reader):
        def discover_since(self, folder, **kwargs):
            raise FolderNotReadable(folder)
    runner = mode(tmp_path, reader=BrokenReader())
    with pytest.raises(FolderNotReadable):
        runner.run(1)
    assert runner.report["error_type"] == "FolderNotReadable" and not runner.report["complete"]


def test_invalid_mail_is_retained_but_never_sent_to_models(tmp_path, monkeypatch):
    runner = mode(tmp_path)
    monkeypatch.setattr("mailhelp.decision_test.prepare", lambda *args: (_ for _ in ()).throw(ValueError("unsafe")))
    assert runner.run(1) == 1
    record = runner.report["mails"][0]
    assert record["raw_rfc822_base64"] and record["paths"] == {}
    assert record["error_type"] == "ValueError" and record["status"] == "failed"


def test_explicit_content_capture_redacts_secrets_before_base64_and_in_errors(tmp_path):
    recorder = ComparisonRecorder(tmp_path / "events.jsonl", ("synthetic-password",))
    recorder.event("ERROR", "test", "event", error=RuntimeError("synthetic-password"))
    recorder.llm_event("request_started", request={"body": "synthetic-password", "authorization": "Bearer abc"})
    recorder.http_response(httpx.Response(401, text="Bearer abc synthetic-password"))
    recorder.http_response(httpx.Response(200, json={"usage": {"input_tokens": 10}, "secret": "abc"}))
    output = recorder.path.read_text(encoding="utf-8")
    assert "synthetic-password" not in output and "Bearer abc" not in output
    raw = b"password: dangerous\r\n\r\n\x80\r\nsynthetic-password"
    sanitized = base64.b64decode(_raw_mail(raw, ("synthetic-password",)))
    assert b"dangerous" not in sanitized and b"synthetic-password" not in sanitized and b"\x80" in sanitized


@pytest.mark.parametrize("arguments", [
    ["--decision-test-file", "r.json"],
    ["--decision-test", "0"],
    *[["--decision-test", "1", *extra] for extra in [
        ["--check"], ["--check-access"], ["--show-imap-credentials"], ["--max-mails", "1"],
        ["--learn", "1"], ["--clear"], ["--yes"],
        ["--ollama-model", "m"], ["--log-directory", "logs"],
    ]],
])
def test_cli_rejects_ambiguous_modes_before_loading_or_connecting(monkeypatch, arguments):
    monkeypatch.setattr(cli, "load_all", lambda *args: pytest.fail("must reject before load"))
    monkeypatch.setattr(sys, "argv", ["mailhelp", *arguments])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


@pytest.mark.parametrize("file,ignore", [(None, False), ("result.json", True)])
def test_cli_decision_test_bypasses_normal_builder_and_logger(monkeypatch, file, ignore):
    loaded = (settings(), secrets(), topics(), [], prompt_config(), "f")
    captured = []
    monkeypatch.setattr(cli, "load_all", lambda directory: loaded)
    monkeypatch.setattr(cli, "build_logger", lambda *args, **kwargs: pytest.fail("normal logger"))
    monkeypatch.setattr(cli, "build_application", lambda *args, **kwargs: pytest.fail("normal application"))
    monkeypatch.setattr(cli, "run_decision_test", lambda *args, **kwargs: captured.append((args, kwargs)) or 0)
    arguments = ["mailhelp", "--decision-test", "7", "--config-directory", "cfg",
                 "--ollama", "localhost:11434", "--ollama-model", "synthetic/local"]
    if file is not None:
        arguments += ["--decision-test-file", file]
    if ignore:
        arguments += ["--ignore-historical-start"]
    monkeypatch.setattr(sys, "argv", arguments)
    assert cli.main() == 0
    assert captured == [((loaded[0], loaded[1], loaded[2], loaded[4], 7, Path("cfg"),
                          Path(file) if file is not None else None), {"ignore_historical_start": ignore,
                          "local_llm": LocalLlm("localhost", 11434, "synthetic/local")})]


@pytest.mark.parametrize("namespace", ["test", "production"])
def test_custom_report_cannot_enter_normal_state_namespace(tmp_path, monkeypatch, namespace):
    cfg, reader, clients, requests, _ = configure(tmp_path, monkeypatch)
    output = Path("data") / namespace / "new.json"
    with pytest.raises(ValueError, match="Zustandsverzeichnis"):
        run_decision_test(cfg, secrets(), topics(), prompt_config(), 1, tmp_path, output)
    assert not (tmp_path / output).exists() and not clients and not requests
    assert not reader.discovery


def test_separate_docker_configuration_exposes_decision_templates_only_in_test_service():
    compose = yaml.safe_load((ROOT / "compose.decision-test.yaml").read_text(encoding="utf-8"))
    service = compose["services"]["mailhelp-decision-test"]
    assert "--decision-test" in service["command"] and service["restart"] == "no"
    assert "./decisions_prompts.yaml:/config/decisions_prompts.yaml:ro" in service["volumes"]
    assert "./data:/config/data" in service["volumes"]
    standard = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    assert "./decisions_prompts.yaml:/config/decisions_prompts.yaml:ro" in standard["services"]["mailhelp"]["volumes"]


def test_default_report_resolves_directory_links_before_state_namespace_guard(tmp_path, monkeypatch):
    cfg, reader, clients, requests, _ = configure(tmp_path, monkeypatch)
    original_resolve = Path.resolve
    data_root = tmp_path / "data"
    def resolve(path, *args, **kwargs):
        # Simulate a decision-tests directory link into production without
        # requiring Windows symbolic-link privileges in automated tests.
        if path.parent == data_root / "decision-tests":
            return data_root / "production" / path.name
        return original_resolve(path, *args, **kwargs)
    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(ValueError, match="Zustandsverzeichnis"):
        run_decision_test(cfg, secrets(), topics(), prompt_config(), 1, tmp_path)
    assert not clients and not requests and not reader.discovery


@pytest.mark.parametrize("irrelevant,unclear,reason", [
    (True, False, "relevance_irrelevant"), (False, True, "relevance_unclear")])
def test_non_relevant_path_never_summarizes_routes_or_extracts(tmp_path, irrelevant, unclear, reason):
    standard = AnalyzerStub(irrelevant=irrelevant, unclear=unclear)
    local = AnalyzerStub()
    runner = mode(tmp_path, analyzer=standard, decisions=local)
    assert runner.run(1) == 0
    assert standard.calls == ["relevance"]
    assert local.calls == ["relevance", "summary", "action_router", "task_extraction", "event_extraction"]
    paths = runner.report["mails"][0]["paths"]
    for stage in ["summary", "action_router", "task_extraction", "event_extraction"]:
        assert paths["standard"]["stages"][stage] == {"status": "skipped", "reason": reason}
    assert not paths["standard"]["would_process_in_normal_mode"]
    assert paths["ollama"]["would_process_in_normal_mode"]


@pytest.mark.parametrize("failed,reason", [("summary", "summary_failed"), ("action_router", "routing_failed")])
def test_summary_and_route_errors_stop_following_stages_but_other_path_completes(tmp_path, failed, reason):
    standard = AnalyzerStub(fail={failed})
    local = AnalyzerStub()
    runner = mode(tmp_path, analyzer=standard, decisions=local)
    assert runner.run(1) == 1
    assert "task_extraction" not in standard.calls and "event_extraction" not in standard.calls
    assert ("action_router" in standard.calls) is (failed == "action_router")
    paths = runner.report["mails"][0]["paths"]
    assert paths["standard"]["stages"]["task_extraction"]["reason"] == reason
    assert paths["ollama"]["status"] == "completed"


def test_all_local_stages_use_local_analyzer_and_never_standard_extractor(tmp_path):
    class Local(AnalyzerStub):
        def summary(self, mail):
            return self.result("summary", Summary(sentences=["Local summary"], deadlines=[]))
    standard, local = AnalyzerStub(), Local()
    runner = mode(tmp_path, analyzer=standard, decisions=local)
    assert runner.run(1) == 0
    paths = runner.report["mails"][0]["paths"]
    assert paths["standard"]["stages"]["summary"]["result"]["sentences"] == ["S"]
    assert paths["ollama"]["stages"]["summary"]["result"]["sentences"] == ["Local summary"]
    assert standard.calls == local.calls == ["relevance", "summary", "action_router", "task_extraction", "event_extraction"]


def test_ollama_construction_failure_closes_cloud_clients_and_imap(tmp_path, monkeypatch):
    cfg, reader, clients, *_ = configure(tmp_path, monkeypatch)
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic Ollama construction failure")
    monkeypatch.setattr("mailhelp.decision_test.OllamaClient", fail)
    with pytest.raises(RuntimeError, match="construction failure"):
        run_decision_test(cfg, secrets(), topics(), prompt_config(), 1, tmp_path)
    assert reader.closed and len(clients) == 2 and all(c.client.is_closed for c in clients)


def test_cli_decision_test_requires_ollama_address_before_loading(monkeypatch):
    monkeypatch.setattr(cli, "load_all", lambda *args: pytest.fail("configuration must not load"))
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--decision-test", "1"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2


@pytest.mark.parametrize("jev,fallback,local,standard_runs,local_runs,legacy_relevance", [
    ("relevant", "irrelevant", "irrelevant", True, False, False),
    ("irrelevant", "relevant", "relevant", False, True, False),
    ("unclear", "relevant", "unclear", True, False, True),
    ("unclear", "irrelevant", "relevant", False, True, True),
    ("unclear", "unclear", "irrelevant", False, False, True),
])
def test_actual_adapters_compare_standard_fallback_against_local_relevance_gates(
        tmp_path, monkeypatch, jev, fallback, local, standard_runs, local_runs, legacy_relevance):
    cfg, _, clients, requests, _ = configure(tmp_path, monkeypatch, jev=jev, fallback=fallback, local=local)
    assert run_decision_test(cfg, secrets(), topics(), prompt_config(), 1, tmp_path) == 0
    cloud = [json.loads(request.content) for kind, request in requests if kind is OpenRouterClient]
    native = [json.loads(request.content) for kind, request in requests if kind is OllamaClient]
    cloud_stages = [data["messages"][0]["content"].removeprefix("quality:") for data in cloud]
    native_stages = [data["messages"][0]["content"].split("\n")[0].removeprefix("quality:") for data in native]
    assert ("relevance" in cloud_stages) is legacy_relevance
    assert ("summary" in cloud_stages) is standard_runs
    assert ("summary" in native_stages) is local_runs
    assert native_stages[0] == "relevance"
    assert all(data["model"] == LOCAL.model for data in native)
    assert clients[0]._state_lock is clients[1]._state_lock
    assert clients[2]._state_lock is not clients[0]._state_lock
    # All model events and the Jev fallback linkage are retained in one relevance stage.
    files = list((tmp_path / "data/decision-tests").glob("*.json"))
    report = json.loads(files[0].read_text(encoding="utf-8"))
    events = report["mails"][0]["paths"]["standard"]["stages"]["relevance"]["events"]
    assert any(e["event"] == "relevance_fallback_completed" for e in events) is legacy_relevance
    assert all(client.client.is_closed for client in clients)


def test_cli_decision_test_uses_configured_ollama_model_and_context(monkeypatch):
    data = prompt_config().model_dump()
    data["ollama"] = {"model": "synthetic/configured", "num_ctx": 4096}
    config = type(prompt_config()).model_validate(data)
    monkeypatch.setattr(cli, "load_all", lambda directory: (settings(), secrets(), topics(), [], config, "f"))
    captured = []
    monkeypatch.setattr(cli, "run_decision_test", lambda *args, **kwargs: captured.append(kwargs) or 0)
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--decision-test", "1", "--ollama", "localhost:11434"])
    assert cli.main() == 0
    assert captured[0]["local_llm"] == LocalLlm("localhost", 11434, "synthetic/configured", 4096)
