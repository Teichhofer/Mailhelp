"""Isolated, read-only paired mail analysis with explicitly retained raw data."""
from __future__ import annotations

import base64
import hashlib
import imaplib
import json
import time
from contextlib import ExitStack
from datetime import datetime, timezone
from dataclasses import asdict
from threading import Lock
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from .adapter import RetryPolicy
from .analysis import Analyzer
from .config import PromptConfig, Secrets, Settings, Topic
from .decisions import (DecisionAnalyzer, DecisionClient, JevRelevanceAnalyzer,
                        load_relevance_prompts)
from .evaluation import write_report
from .imap import FolderNotReadable, ImapReader
from .logging import NullLogger, redact
from .mime import prepare
from .openrouter import OpenRouterClient
from .laya import LayaClient, LayaRelevanceAnalyzer, load_laya_prompts
from .ollama import LocalLlm, OllamaClient
from .paths import runtime_path


class ComparisonRecorder(NullLogger):
    """Retain content only inside this explicitly selected comparison run."""

    def __init__(self, log_path: Path, secrets: tuple[str, ...]):
        self.path, self.secrets = log_path, secrets
        self.entries: list[dict[str, Any]] = []

    def event(self, level: str, module: str, event: str, **context: Any) -> None:
        self._record(event, {"level": level, "module": module, **context})

    def llm_event(self, event: str, request: Any = None, response: Any = None,
                  **context: Any) -> None:
        self._record(event, {"request": request, "response": response, **context})

    def _record(self, event: str, context: dict[str, Any]) -> None:
        entry = redact({"timestamp": datetime.now(timezone.utc).isoformat(),
                        "event": event, **context}, self.secrets)
        self.entries.append(entry)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def http_response(self, response: httpx.Response) -> None:
        response.read()
        try:
            raw = response.json()
        except ValueError:
            raw = response.text
        # No request/response headers are retained: they can contain credentials.
        self._record("http_response", {"http_status": response.status_code, "response": raw})


def _raw_mail(raw: bytes, secrets: tuple[str, ...]) -> str:
    """Keep binary MIME data reversible while removing credentials before base64."""
    text = raw.decode("latin-1")
    encoded_secrets = tuple(secret.encode("utf-8").decode("latin-1") for secret in secrets)
    cleaned = redact(text, encoded_secrets)
    return base64.b64encode(cleaned.encode("latin-1")).decode("ascii")


class LocalPipeline:
    """Ollama path whose relevance check runs on Laya, a local decision model."""

    def __init__(self, main: Analyzer, relevance: Any):
        self.main, self.relevance_analyzer = main, relevance

    def relevance(self, mail: dict[str, Any], topics: list[Topic]) -> Any:
        return self.relevance_analyzer.relevance(mail, topics)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.main, name)


# Intermediate reports are written at most this often.  The report holds every
# raw mail, so rewriting it after each stage would grow quadratically with the
# mail count.  The final state and aborts are always written immediately.
SAVE_INTERVAL_SECONDS = 60.0


class DecisionTestMode:
    def __init__(self, imap: ImapReader, standard: Analyzer, ollama: Analyzer,
                 settings: Settings, topics: list[Topic], report: dict[str, Any],
                 output: Path, recorder: ComparisonRecorder,
                 *, ignore_historical_start: bool = False, relevance_only: bool = False,
                 save_interval: float = SAVE_INTERVAL_SECONDS, clock=time.monotonic):
        self.imap, self.standard, self.ollama = imap, standard, ollama
        self.settings, self.topics = settings, topics
        self.report, self.output, self.recorder = report, output, recorder
        self.ignore_historical_start = ignore_historical_start
        self.relevance_only = relevance_only
        self.save_interval, self.clock = save_interval, clock
        self.saved_at: float | None = None

    def _save(self, *, force: bool = False) -> None:
        now = self.clock()
        if not force and self.saved_at is not None and now - self.saved_at < self.save_interval:
            return
        write_report(self.output, redact(self.report, self.recorder.secrets))
        self.saved_at = now

    def _stage(self, result: dict, name: str, operation) -> Any:
        stage = {"status": "running", "events": []}
        result["stages"][name] = stage
        start = len(self.recorder.entries)
        self._save()
        try:
            call, value = operation()
            stage.update(status="completed", call_id=call, result=value.model_dump(mode="json"))
            return value
        except Exception as exc:
            stage.update(status="failed", error_type=type(exc).__name__)
            return None
        finally:
            stage["events"] = self.recorder.entries[start:]
            self._save()

    def _pipeline(self, record: dict, name: str, mail: dict[str, Any], classifier) -> None:
        result = {"status": "running", "stages": {}}
        record["paths"][name] = result
        relevance = self._stage(result, "relevance", lambda: classifier.relevance(mail, self.topics))
        result["would_process_in_normal_mode"] = relevance is not None and relevance.decision == "relevant"
        if self.relevance_only:
            # Only the relevance decision is compared; no follow-up stage runs.
            for stage in ("summary", "action_router", "task_extraction", "event_extraction"):
                result["stages"][stage] = {"status": "skipped", "reason": "relevance_only"}
        elif not result["would_process_in_normal_mode"]:
            reason = "relevance_failed" if relevance is None else "relevance_" + relevance.decision
            for stage in ("summary", "action_router", "task_extraction", "event_extraction"):
                result["stages"][stage] = {"status": "skipped", "reason": reason}
        else:
            summary = self._stage(result, "summary", lambda: classifier.summary(mail))
            if summary is None:
                result["stages"]["action_router"] = {"status": "skipped", "reason": "summary_failed"}
                route = None
            else:
                route = self._stage(result, "action_router", lambda: classifier.action_route(mail))
            for stage, count, extract in (
                ("task_extraction", None if route is None else route.task_count, classifier.extract_tasks),
                ("event_extraction", None if route is None else route.event_count, classifier.extract_events),
            ):
                if count is None:
                    result["stages"][stage] = {"status": "skipped", "reason": "summary_failed" if summary is None else "routing_failed"}
                elif count == 0:
                    result["stages"][stage] = {"status": "skipped", "reason": "no_candidates"}
                else:
                    self._stage(result, stage, lambda: extract(mail, expected_count=count))
        result["status"] = ("failed" if any(stage["status"] == "failed"
                                             for stage in result["stages"].values()) else "completed")
        self._save()

    def run(self, count: int) -> int:
        try:
            candidates = []
            for folder in self.settings.imap.folders:
                try:
                    candidates.extend(self.imap.discover_since(
                        folder, max_count=count,
                        historical_start=(None if self.ignore_historical_start
                                          else self.settings.imap.historical_start)))
                except FolderNotReadable:
                    if folder == self.settings.imap.primary_folder:
                        raise
                    self.report["selection_errors"].append({"folder": folder, "error_type": "FolderNotReadable"})
            ranks = {folder: index for index, folder in enumerate(self.settings.imap.folders)}
            candidates.sort(key=lambda item: (item.received_at, item.uid, -ranks[item.folder]), reverse=True)
            seen = set()
            for candidate in candidates:
                if len(self.report["mails"]) >= count:
                    break
                try:
                    fetched = self.imap.fetch_uid(candidate.folder, candidate.uid, candidate.uidvalidity)
                except Exception as exc:
                    self.report["selection_errors"].append({"folder": candidate.folder, "uid": candidate.uid,
                                                            "error_type": type(exc).__name__})
                    self._save()
                    continue
                fingerprint = hashlib.sha256(fetched.raw).hexdigest()
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                record = {"mail_sha256": fingerprint, "folder": fetched.folder,
                          "uidvalidity": fetched.uidvalidity, "uid": fetched.uid,
                          "received_at": fetched.received_at.isoformat(),
                          "raw_rfc822_base64": _raw_mail(fetched.raw, self.recorder.secrets),
                          "raw_credentials_redacted": True, "paths": {}, "status": "running"}
                self.report["mails"].append(record)
                self._save()
                try:
                    mail = prepare(fetched.raw, self.settings.limits, fetched.received_at, self.settings.timezone)
                except Exception as exc:
                    record.update(status="failed", error_type=type(exc).__name__)
                    self._save()
                    continue
                record["prepared_mail"] = mail
                self._pipeline(record, "standard", mail, self.standard)
                self._pipeline(record, "ollama", mail, self.ollama)
                record["status"] = ("failed" if any(path["status"] == "failed"
                                                       for path in record["paths"].values()) else "completed")
                self._save()
                print(f"Decision-Test: {len(self.report['mails'])}/{count} Mails verglichen.", flush=True)
            self.report["complete"] = True
        except BaseException as exc:
            self.report["error_type"] = type(exc).__name__
            raise
        finally:
            self.report["selected_mail_count"] = len(self.report["mails"])
            self.report["count_satisfied"] = len(self.report["mails"]) == count
            self._save(force=True)
        failed = any(item["status"] == "failed" for item in self.report["mails"])
        return 1 if not self.report["count_satisfied"] or self.report["selection_errors"] or failed else 0


def run_decision_test(settings: Settings, secrets: Secrets, topics: list[Topic],
                      prompts: PromptConfig, count: int, directory: Path,
                      output: Path | None = None, *, local_llm: LocalLlm,
                      ignore_historical_start: bool = False,
                      laya: tuple[str, int] | None = None, laya_model: str | None = None,
                      relevance_only: bool = False,
                      irrelevant_topics: list[Topic] | None = None) -> int:
    """Construct only read adapters; production stores and write services do not exist here."""
    decision_prompts = load_relevance_prompts(directory)
    # With Laya, the Ollama path checks relevance with the local decision model.
    laya_prompts = None
    if laya is not None:
        laya_prompts = load_laya_prompts(directory)
        if laya_model:
            laya_prompts = laya_prompts.model_copy(update={"model": laya_model})
    if output is None:
        output = runtime_path(settings.data_directory, directory) / "decision-tests" / f"decision-test-{uuid4()}.json"
    else:
        output = runtime_path(output, directory)
    output = output.resolve()
    data_root = runtime_path(settings.data_directory, directory)
    protected = (data_root / "test", data_root / "production")
    if any(output.is_relative_to(path.resolve()) for path in protected):
        raise ValueError("Decision-Testdatei darf nicht im normalen Zustandsverzeichnis liegen")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects prior comparisons and configuration/state files.
    # It also fails before connecting to IMAP or making a paid model call.
    with output.open("x", encoding="utf-8") as stream:
        stream.write("{}\n")
    log_path = output.with_suffix(output.suffix + ".jsonl")
    with log_path.open("x", encoding="utf-8"):
        pass
    known_secrets = tuple(value.get_secret_value() for value in (
        secrets.imap_password, secrets.openrouter_api_key, secrets.telegram_bot_token,
        secrets.todoist_token, secrets.todoist_client_id, secrets.todoist_client_secret,
        secrets.google_oauth_client_id, secrets.google_oauth_client_secret, secrets.google_oauth_refresh_token))
    recorder = ComparisonRecorder(log_path, known_secrets)
    report = {"schema_version": 2, "mode": "decision_test",
              "comparison": "standard_vs_ollama",
              "pipeline_policy": "relevance_only" if relevance_only else "relevant_only",
              "ollama": asdict(local_llm),
              "ollama_relevance": (None if laya_prompts is None else {
                  "engine": "laya", "base_url": LocalLlm(*laya, laya_prompts.model).base_url,
                  "model": laya_prompts.model}),
              "laya_prompts": None if laya_prompts is None else laya_prompts.model_dump(mode="json"),
              # Laya builds its questions from these categories as well.
              "laya_irrelevant_topics": (None if laya_prompts is None else
                                         [topic.model_dump() for topic in irrelevant_topics or []]),
              "timeouts": {"openrouter": settings.timeouts.openrouter.model_dump(),
                           "ollama": settings.timeouts.ollama.model_dump()}, "run_id": str(uuid4()),
              "started_at": datetime.now(timezone.utc).isoformat(), "complete": False,
              "requested_mail_count": count, "selection": "global_newest_first_unique_raw_mail",
              "historical_start": (None if ignore_historical_start or settings.imap.historical_start is None
                                   else settings.imap.historical_start.isoformat()),
              "timezone": settings.timezone,
              "prompts": prompts.model_dump(mode="json"),
              "decisions_prompts": decision_prompts.model_dump(mode="json"),
              "topics": [topic.model_dump() for topic in topics],
              "selection_errors": [], "mails": []}
    write_report(output, redact(report, known_secrets))
    print(f"Decision-Testdatei: {output}", flush=True)
    try:
        with ExitStack() as stack:
            cfg = settings.timeouts.imap
            reader = ImapReader(
                settings.imap.host, settings.imap.port, secrets.imap_username,
                secrets.imap_password.get_secret_value(), cfg.timeout_seconds,
                factory=imaplib.IMAP4_SSL if settings.imap.connection_mode == "ssl" else imaplib.IMAP4,
                policy=RetryPolicy(cfg.retries, cfg.initial_backoff_seconds, cfg.max_backoff_seconds,
                                   lambda delay: (time.sleep(delay), False)[1]),
                starttls=settings.imap.connection_mode == "starttls", batch_size=settings.imap.batch_size,
                logger=recorder)
            stack.callback(reader.close)
            cfg = settings.timeouts.openrouter
            # Both clients share one isolated in-memory rate budget. No production checkpoint is loaded.
            calls: list[float] = []
            def save_calls(values):
                calls[:] = values
            clients = []
            shared_lock = Lock()
            for client_type in (OpenRouterClient, DecisionClient):
                client = client_type(secrets.openrouter_api_key.get_secret_value(), cfg.timeout_seconds,
                                     cfg.retries, settings.limits.llm_calls_per_minute,
                                     initial_backoff=cfg.initial_backoff_seconds, max_backoff=cfg.max_backoff_seconds,
                                     load_calls=lambda: calls, save_calls=save_calls, logger=recorder)
                stack.callback(client.close)
                client._state_lock = shared_lock
                client.client.event_hooks["response"].append(recorder.http_response)
                clients.append(client)
            cfg = settings.timeouts.ollama
            local = dict(initial_backoff=cfg.initial_backoff_seconds,
                         max_backoff=cfg.max_backoff_seconds, logger=recorder)
            local_client = OllamaClient(local_llm, cfg.timeout_seconds, cfg.retries,
                                        settings.limits.llm_calls_per_minute, **local)
            stack.callback(local_client.close)
            local_clients: list[Any] = [local_client]
            if laya is not None and laya_prompts is not None:
                laya_client = LayaClient(*laya, laya_prompts.model, cfg.timeout_seconds, cfg.retries,
                                         settings.limits.llm_calls_per_minute, **local)
                stack.callback(laya_client.close)
                local_clients.append(laya_client)
            for client in local_clients:
                # Fail before any mail is read if a local model is not installed.
                client.check_access()
                client.client.event_hooks["response"].append(recorder.http_response)
            options = dict(provider_retries=settings.retries.provider_retry,
                           json_repair_retries=settings.retries.json_repair,
                           schema_repair_retries=settings.retries.schema_repair)
            standard = JevRelevanceAnalyzer(
                clients[0], prompts, decisions=DecisionAnalyzer(
                    clients[1], decision_prompts, settings.limits.max_llm_payload_bytes), **options)
            ollama: Any = Analyzer(local_client, prompts, **options)
            if laya_prompts is not None:
                ollama = LocalPipeline(ollama, LayaRelevanceAnalyzer(
                    local_clients[1], laya_prompts, settings.limits.max_llm_payload_bytes,
                    irrelevant_topics or []))
            return DecisionTestMode(reader, standard, ollama, settings, topics, report, output,
                                    recorder, ignore_historical_start=ignore_historical_start,
                                    relevance_only=relevance_only).run(count)
    except BaseException as exc:
        report["error_type"] = type(exc).__name__
        write_report(output, redact(report, known_secrets))
        raise
