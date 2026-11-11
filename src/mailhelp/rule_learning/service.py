"""Session-owned analysis jobs and recoverable, revision-checked topic transactions."""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from typing import Any

from ..config import Settings, Topic, read_yaml
from ..configuration import ConfigurationService, file_hash
from ..review.learning_log import learning_path
from ..storage import CorruptState, atomic_replace
from .mining import DecisionRuleMiner
from .models import RuleAnalysis, RuleState
from .validation import FILES, RuleConflict, RuleValidationService

STATE = "decision-rule-learning"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def redact_data(value: Any, redact: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [redact_data(item, redact) for item in value]
    if isinstance(value, dict):
        return {key: redact_data(item, redact) for key, item in value.items()}
    return value


class DecisionRuleLearning:
    def __init__(self, configuration: ConfigurationService, analyzer: Callable[[], Any],
                 active: Callable[[str], bool], redact: Callable[[str], str] = lambda text: text,
                 payload_limit: Callable[[], int] = lambda: 100_000,
                 clock: Callable[[], float] = time.time):
        self.configuration, self.analyzer, self.active = configuration, analyzer, active
        self.redact, self.payload_limit, self.clock = redact, payload_limit, clock
        self.store, self.directory = configuration.store, configuration.directory
        self.actor = ""

    def state(self, actor: str | None = None) -> RuleState:
        with self.store.locked():
            try:
                state = self.store.load_model(STATE, RuleState, RuleState())
            except CorruptState:
                state = RuleState()
            if state.created_at and self.clock() - state.created_at > 86400 and state.status != "committing":
                state = RuleState(version=state.version + 1)
                self.save(state)
            if actor is None or state.owner == digest(actor):
                return state
            return RuleState(version=state.version, status="committing" if state.status == "committing" else "empty")

    def save(self, state: RuleState) -> None:
        self.store.save(STATE, state.model_dump(mode="json"))

    def hashes(self) -> dict[str, str]:
        return {name: file_hash(self.directory / name) for name in (*FILES.values(), "config.yaml")}

    def check(self, actor: str) -> None:
        if not self.active(actor):
            raise PermissionError("Sitzung abgelaufen; erneut anmelden.")

    def recover(self) -> None:
        with self.store.locked():
            state = self.state()
            if state.status in {"queued", "running"}:
                state.status, state.message = "interrupted", "Analyse unterbrochen; kein automatischer Modellaufruf."
                state.version += 1
                self.save(state)

    def change(self, actor: str, version: int, key: str, action: str, payload: dict[str, Any]) -> RuleState:
        self.check(actor)
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", key):
            raise ValueError("Ungültiger Idempotenzschlüssel")
        receipt = digest(actor + "\0" + key)
        content = digest(json.dumps([version, action, payload], sort_keys=True))
        with self.store.locked():
            state = self.state()
            if action not in {"analyze", "resume"} and state.owner != digest(actor):
                raise PermissionError("Kein eigener Analyseauftrag vorhanden.")
            if receipt in state.receipts:
                if state.owner != digest(actor):
                    raise PermissionError("Der frühere Auftrag gehört nicht zu dieser Sitzung.")
                if state.receipts[receipt] != content:
                    raise RuleConflict("Idempotenzschlüssel bereits anders verwendet")
                if state.status == "committing":
                    self.finish(actor, state)
                return state
            if version != state.version:
                raise RuleConflict("Analysestand veraltet; neu laden.")
            if payload.get("confirm") is not True:
                raise ValueError("Die Aktion muss ausdrücklich bestätigt werden")
            if action == "analyze":
                state = self.begin(actor, state)
            elif action == "apply" and state.status == "review":
                self.prepare(state, payload["choices"])
            elif action == "resume" and state.status == "committing":
                state.owner = digest(actor)
            else:
                raise RuleConflict("Aktion passt nicht zum Analysestand")
            self.check(actor)
            state.version += 1
            state.receipts[receipt] = content
            state.receipts = dict(list(state.receipts.items())[-100:])
            self.save(state)
            if state.status == "committing":
                self.finish(actor, state)
            return state

    def prepare(self, state: RuleState, choices: list[dict[str, Any]]) -> None:
        if state.hashes != self.hashes():
            raise RuleConflict("Regeln oder Postfachkonfiguration inzwischen geändert")
        settings = Settings.model_validate(read_yaml(self.directory / "config.yaml"))
        allowed = {mailbox.id for mailbox in settings.imap.configured_mailboxes()}
        commit = RuleValidationService.prepare(state.documents, choices, state.proposals, allowed)
        if state.hashes != self.hashes():
            raise RuleConflict("Dateien während der Prüfung geändert; bitte neu laden")
        state.commit, state.status = commit, "committing"
        state.evidence, state.proposals = [], []

    def begin(self, actor: str, previous: RuleState) -> RuleState:
        if previous.status in {"queued", "running", "committing"}:
            raise RuleConflict("Es gibt bereits einen laufenden oder unvollständigen Auftrag")
        documents = {category: RuleValidationService.parse((self.directory / filename).read_text(encoding="utf-8"),
                                                          category) for category, filename in FILES.items()}
        evidence, skipped = DecisionRuleMiner(learning_path(self.store.directory), self.redact).mine()
        if not evidence:
            raise ValueError("Keine verwertbaren Entscheidungen im Lernprotokoll vorhanden")
        self.actor = actor
        return RuleState(version=previous.version, owner=digest(actor), status="queued", documents=documents,
                         hashes=self.hashes(), evidence=evidence, skipped=skipped, receipts=previous.receipts,
                         created_at=self.clock())

    def before_call(self, actor: str) -> None:
        self.check(actor)
        state = self.state(actor)
        if state.status != "running" or state.hashes != self.hashes():
            raise RuleConflict("Analyse unterbrochen oder Konfiguration geändert")

    def tick(self) -> bool:
        with self.store.locked():
            state = self.state()
            if state.status != "queued":
                return False
            state.status = "running"
            state.version += 1
            self.save(state)
        try:
            self.before_call(self.actor)
            analyzer = self.analyzer()
            if "decision_rule_learning" not in analyzer.prompts.prompts:
                raise ValueError("In prompts.yaml fehlt decision_rule_learning")
            evidence = redact_data(list(state.evidence), self.redact)
            payload = redact_data({"topics": state.documents, "decisions": evidence,
                                   "summary": DecisionRuleMiner.counts(evidence)}, self.redact)
            while len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > self.payload_limit() and evidence:
                evidence.pop()
                payload["decisions"] = evidence
                payload["summary"] = DecisionRuleMiner.counts(evidence)
            if not evidence:
                raise ValueError("Regeln und Belege überschreiten die KI-Nutzlastgrenze")
            _, analysis = analyzer.decision_rule_learning(payload, before_call=lambda: self.before_call(self.actor))
            known = {item["id"] for item in evidence}
            if any(set(proposal.evidence) - known for proposal in analysis.proposals):
                raise ValueError("Unbekannter Entscheidungsbeleg")
            state.proposals = RuleAnalysis.model_validate(analysis.model_dump()).proposals
            state.evidence = evidence
            state.status, state.message = "review", "Vorschläge einzeln prüfen und bearbeiten; noch nichts gespeichert."
        except Exception:
            state.status = "failed"
            state.message = "Analyse nicht abgeschlossen. Sitzung, Prompt, Budget und KI prüfen."
        with self.store.locked():
            current = self.state()
            if current.owner != state.owner or current.status != "running" or current.version != state.version:
                return True
            state.version += 1
            self.save(state)
        return True

    def finish(self, actor: str, state: RuleState) -> None:
        """Validate the whole journal first; recover only our originals or already written outputs."""
        self.check(actor)
        if set(state.commit) != set(FILES.values()):
            raise RuleConflict("Unvollständiger oder ungültiger Übernahmeauftrag")
        for name, content in state.commit.items():
            category = next(key for key, filename in FILES.items() if filename == name)
            RuleValidationService.parse(content, category)
            if file_hash(self.directory / name) not in {state.hashes[name], digest(content)}:
                raise RuleConflict("Übernahme unterbrochen; Datei inzwischen extern geändert")
        if file_hash(self.directory / "config.yaml") != state.hashes["config.yaml"]:
            raise RuleConflict("Postfachkonfiguration inzwischen geändert")
        self.check(actor)
        for name, content in state.commit.items():
            if file_hash(self.directory / name) != digest(content):
                atomic_replace(self.directory / name, content)
        topics = RuleValidationService.parse(state.commit[FILES["relevant"]], "relevant")
        self.configuration.activate_topics([Topic.model_validate(item) for item in topics["topics"]])
        state.status, state.commit = "done", {}
        state.message = "Regeln gespeichert; neue Analysen übernehmen sie am nächsten sicheren Verarbeitungspunkt."
        self.save(state)
