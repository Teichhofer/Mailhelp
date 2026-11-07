"""Independent IMAP sessions, durable per-mail progress and per-call budget reservations."""

from __future__ import annotations

import json
from threading import Event, Thread
from typing import Any, cast

from ..config import IrrelevantTopicsConfig, read_yaml
from ..llm.learning import LearningMode, LearningSource
from ..mailbox.sender_filter import sender_addresses
from ..processing.analysis import Analyzer
from .learning_jobs import LearningCard, LearningConflict, LearningJobs


class LearningPaused(BaseException):
    """Crosses the learning kernel's per-mail Exception isolation without consuming a mail."""


class LearningCompleter:
    def __init__(self, worker, client, generation=None):
        self.worker, self.client = worker, client
        self.generation = worker.jobs.state().generation if generation is None else generation

    def complete(self, model, parameters, system, payload, **kwargs):
        # UTF-8 bytes overestimate textual input tokens; include the schema and request envelope.
        size = len(json.dumps([system, payload, str(kwargs.get("response_schema"))], ensure_ascii=False).encode())
        tokens = (
            size + self.worker.app.settings.limits.max_llm_payload_bytes + parameters.get("max_tokens", 32000)
        ) * (self.client.policy.retries + 1)
        service = self.worker.jobs
        with service.lock:
            state = service.state()
            if state.generation != self.generation:
                raise LearningPaused()
            assert state.selection is not None
            cost = (state.reserved_tokens + tokens) * state.selection.usd_per_million_tokens / 1000000
            if (
                state.status != "running"
                or self.worker.stopped.is_set()
                or not service.active(state.actor)
                or state.revision != service.revision()
                or cost > state.selection.budget_usd
            ):
                if state.status == "running":
                    state.status = "paused"
                    state.message = "Angehalten: Budget, Sitzung oder Konfiguration prüfen."
                    state.version += 1
                    service.save(state)
                raise LearningPaused()
            state.reserved_tokens += tokens
            service.save(state)
        return self.client.complete(model, parameters, system, payload, **kwargs)

    def __getattr__(self, name):
        return getattr(self.client, name)


class LearningWorker:
    def __init__(self, app, site, secrets, open_reader=None):
        from .experience import _reader

        self.app, self.secrets = app, secrets
        self.open_reader = open_reader or _reader
        self.stopped, self.thread = Event(), None
        self.jobs = LearningJobs(
            app.configuration,
            lambda actor: actor.startswith("web:") and site.auth.active(actor.removeprefix("web:")),
            self.estimate,
        )

    def estimate(self, selection):
        prompts = self.app.analyzer.prompts
        stages = ("relevance", "learning_classification", "learning_abstraction")
        output = max(
            route.parameters.get("max_tokens", 32000) for stage in stages for route in prompts.resolved_routes(stage)[0]
        )
        # Two relevance groups, classification, abstraction; every configured repair and route.
        attempts = 1 + self.app.settings.retries.provider_retry + self.app.settings.retries.json_repair
        attempts += self.app.settings.retries.schema_repair
        routes = max(len(prompts.resolved_routes(stage)[0]) for stage in stages)
        return (
            selection.count
            * 4
            * attempts
            * routes
            * (self.app.openrouter.policy.retries + 1)
            * (2 * self.app.settings.limits.max_llm_payload_bytes + output + 65536)
        )

    def start(self) -> None:
        self.jobs.recover()
        self.stopped.clear()
        self.thread = Thread(target=self.run, name="mailhelp-learning", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stopped.set()
        if self.thread is not None:
            self.thread.join()

    def run(self):
        while not self.stopped.is_set():
            generation = self.jobs.state().generation
            try:
                worked = self.tick()
            except (Exception, LearningPaused):
                with self.jobs.lock:
                    state = self.jobs.state()
                    if state.generation == generation and state.status == "running":
                        state.status, state.message = "paused", "Lernlauf angehalten. Verbindung prüfen und fortsetzen."
                        state.version += 1
                        self.jobs.save(state)
                worked = False
            if not worked:
                self.stopped.wait(1)

    def tick(self):
        state = self.jobs.state()
        if state.status != "running":
            return False
        self.jobs.check(state.actor)
        if state.revision != self.jobs.revision():
            raise LearningConflict("Konfiguration geändert")
        selection = state.selection
        assert selection is not None
        mailbox = self.app.settings.imap.mailbox(selection.mailbox)
        with self.open_reader(self.app.settings, self.secrets, mailbox) as reader:
            if state.candidates is None:
                return self.discover(state, reader)
            if state.cursor == len(state.candidates):
                with self.jobs.lock:
                    current = self.jobs.state()
                    if current.generation != state.generation:
                        return True
                    self.jobs.check(current.actor)
                    if current.revision != self.jobs.revision():
                        raise LearningConflict("Konfiguration während des Abschlusses geändert")
                    if current.status == "running":
                        current.status, current.message = (
                            "review",
                            "Ergebnisse prüfen und Auswahl ausdrücklich übernehmen.",
                        )
                        current.version += 1
                        self.jobs.save(current)
                return True
            entry = state.candidates[state.cursor]
            mail = reader.fetch_uid(entry["folder"], entry["uid"], entry["uidvalidity"])
            analyzer = Analyzer(
                LearningCompleter(self, self.app.openrouter, state.generation),
                self.app.analyzer.prompts,
                provider_retries=self.app.settings.retries.provider_retry,
                json_repair_retries=self.app.settings.retries.json_repair,
                schema_repair_retries=self.app.settings.retries.schema_repair,
            )
            mode = LearningMode(
                reader,
                analyzer,
                selection.folders,
                self.app.settings.limits,
                self.app.orchestrator.topics,
                self.jobs.directory / "topics.yaml",
                IrrelevantTopicsConfig.model_validate(read_yaml(self.jobs.directory / "irrelevant_topics.yaml")).topics,
                self.jobs.directory / "irrelevant_topics.yaml",
                self.app.sender_store,
                decision_store=self.app.store,
                timezone=self.app.settings.timezone,
                sources=[LearningSource(reader, selection.folders, mailbox_id=selection.mailbox)],
                output_fn=lambda _: None,
            )
            classification, payload, failed = mode.classify(mail, mode._blocked_senders())
            categories = mode._categories([classification]) if classification is not None else []
        with self.jobs.lock:
            current = self.jobs.state()
            if current.generation != state.generation:
                return True
            self.jobs.check(current.actor)
            if current.status == "cancelled" or current.revision != self.jobs.revision():
                return True
            for category in categories:
                assert payload is not None
                headers = cast(dict[str, Any], payload["headers"])
                evidence = str(headers.get("subject", "Ohne Betreff"))[:500]
                card = next(
                    (card for card in current.cards if card.category.name.casefold() == category.name.casefold()), None
                )
                if card is None:
                    card = LearningCard(category=category)
                    current.cards.append(card)
                card.evidence.append(evidence)
                card.senders = sorted(set(card.senders) | sender_addresses(headers.get("from", "")))
            current.cursor += 1
            current.failures += int(failed)
            self.jobs.save(current)
        return True

    def discover(self, state, reader):
        assert state.selection is not None
        listed = reader.list_folders()
        entries = [
            candidate
            for folder in state.selection.folders
            for candidate in reader.discover_since(folder, max_count=state.selection.count, historical_start=None)
        ]
        entries.sort(key=lambda entry: (entry.received_at, entry.uid), reverse=True)
        with self.jobs.lock:
            current = self.jobs.state()
            if current.generation != state.generation:
                return False
            self.jobs.check(current.actor)
            if current.status != "running" or current.revision != self.jobs.revision():
                return False
            current.candidates = [
                {"folder": item.folder, "uid": item.uid, "uidvalidity": item.uidvalidity}
                for item in entries[: state.selection.count]
            ]
            configured = self.app.settings.imap.mailbox(state.selection.mailbox).folders
            current.folders = {
                item.name: item.role not in {"junk", "trash"} for item in listed if item.name not in configured
            }
            self.jobs.save(current)
        return True
