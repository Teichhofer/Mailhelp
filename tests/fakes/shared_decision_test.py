"""Shared synthetic fixtures and doubles; no test-module dependencies."""

import json
from datetime import UTC, datetime

import httpx
import yaml
from shared_decisions import ROOT, envelope

from mailhelp.config import Secrets, Settings, Topic
from mailhelp.decision_test import ComparisonRecorder, DecisionTestMode
from mailhelp.decision_test import run_decision_test as _run_decision_test
from mailhelp.decisions import DecisionClient
from mailhelp.imap import FetchedMail, MailCandidate
from mailhelp.laya import LayaClient
from mailhelp.models import ActionRoute, EventExtraction, Relevance, Summary, TaskExtraction
from mailhelp.ollama import LocalLlm, OllamaClient
from mailhelp.openrouter import OpenRouterClient

LOCAL = LocalLlm("ollama.example.test", 11434, "synthetic/local", 8192)

LAYA = ("laya.example.test", 11434)

LAYA_MODEL = "laya:322m-multilingual-mlx-fp16"

ADS = Topic(id="werbung", name="Werbung", enabled=True, description="Synthetische Werbung")

def run_decision_test(*args, **kwargs):
    return _run_decision_test(*args, local_llm=LOCAL, **kwargs)

NOW = datetime(2026, 10, 8, 10, tzinfo=UTC)

RAW = b"From: sender@example.test\r\nSubject: Synthetic comparison\r\nDate: Thu, 08 Oct 2026 10:00:00 +0000\r\n\r\nBitte Anmeldung bestaetigen. Treffen am 9.10.2026 um 10:00 Uhr."

def settings():
    data = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    data["imap"]["folders"] = ["INBOX", "Optional"]
    return Settings.model_validate(data)

def secrets():
    return Secrets.model_validate({**{name: "synthetic-" + name for name in Secrets.model_fields
                                      if name not in {"imap", "profiles", "iserv"}},
                                   "imap": {1: {"username": "synthetic-user", "password": "synthetic-imap"}}})

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
              jev="relevant", fallback="relevant", local="relevant",
              installed=(LOCAL.model, LAYA_MODEL)):
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
                if kind is LayaClient:
                    assert request.url.host == LAYA[0]
                    assert "Authorization" not in request.headers
                    if request.url.path == "/api/tags":
                        return httpx.Response(200, json={"models": [{"name": name} for name in installed]})
                    data = json.loads(request.content)
                    assert isinstance(data["state"], str)
                    # A relevant mail: the topic option wins over the catch-all in every order.
                    answers = {}
                    for name, question in data["questions"].items():
                        probabilities = {letter: 0.02 if text.startswith("None of these") else 0.98
                                         for letter, text in question["criteria"].items()}
                        answers[name] = {"type": "choice", "choice": max(probabilities, key=probabilities.get),
                                         "confidence": 0.9, "probabilities": probabilities}
                    # Ollama answers without an id, unlike OpenRouter decisions.
                    return httpx.Response(200, json={"model": data["model"], "answers": answers,
                                                     "usage": {"input_tokens": 40, "output_tokens": 0}})
                if kind is OllamaClient:
                    assert request.url.host == LOCAL.host
                    assert "Authorization" not in request.headers
                    if request.url.path == "/api/tags":
                        return httpx.Response(200, json={"models": [{"name": name} for name in installed]})
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
    monkeypatch.setattr("mailhelp.decision_test.LayaClient", make_client(LayaClient))
    return cfg, reader, clients, requests, reader_options

class AnalyzerStub:
    last_relevance_source = "test"

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
