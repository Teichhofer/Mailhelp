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
from .changes import assemble, compact_topics, condense
from .mining import MAX_EVIDENCE, MAX_EVIDENCE_ALL, DecisionRuleMiner
from .models import RejectedRuleProposal, RuleAnalysis, RuleHistory, RuleState
from .rejections import readmit, rejection, remember
from .validation import FILES, RuleConflict, RuleValidationService

STATE = "decision-rule-learning"
HISTORY = "decision-rule-learning-history"
SCOPES = {"new": MAX_EVIDENCE, "all": MAX_EVIDENCE_ALL}
GENERIC_FAILURE = "Analyse nicht abgeschlossen. Sitzung, Prompt, Budget und KI prüfen."


def failure_message(error: Exception) -> str:
    """5.7.6: a specific, credential-free reason instead of one generic sentence."""
    from ..processing.analysis import (
        LlmInvalidJson,
        LlmProviderResponseInvalid,
        LlmSchemaValidationExceeded,
        LlmTokenLimitExceeded,
    )
    if isinstance(error, LlmTokenLimitExceeded):
        # 5.7.7: fewer decisions shrink the input, not the cut-off output; that hint misled.
        return ("Analyse nicht abgeschlossen: Die KI-Antwort wurde am Ausgabelimit abgeschnitten, auch beim "
                "verkleinerten zweiten Versuch. Später erneut versuchen oder „Nur neue Entscheidungen“ wählen.")
    if isinstance(error, LlmProviderResponseInvalid):
        return ("Analyse nicht abgeschlossen: Der KI-Anbieter lieferte keine verwertbare Antwort. "
                "Später erneut versuchen.")
    if isinstance(error, (LlmInvalidJson, LlmSchemaValidationExceeded)):
        return "Analyse nicht abgeschlossen: Die KI-Antwort entsprach nicht dem erwarteten Format."
    if isinstance(error, PermissionError):
        return "Analyse nicht abgeschlossen: Sitzung abgelaufen; erneut anmelden."
    if isinstance(error, RuleConflict):
        return "Analyse nicht abgeschlossen: Regeln oder Konfiguration wurden währenddessen geändert."
    if type(error) is ValueError and str(error):
        # Mailhelp's own checks (missing prompt, payload limit, unknown evidence) are safe to show.
        return f"Analyse nicht abgeschlossen: {error}."
    return GENERIC_FAILURE


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
                 clock: Callable[[], float] = time.time, logger: Any = None):
        self.configuration, self.analyzer, self.active = configuration, analyzer, active
        self.redact, self.payload_limit, self.clock = redact, payload_limit, clock
        self.logger = logger
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

    def history(self) -> RuleHistory:
        try:
            return self.store.load_model(HISTORY, RuleHistory, RuleHistory())
        except CorruptState:
            return RuleHistory()

    def overview(self, actor: str) -> dict[str, Any]:
        with self.store.locked():
            state, visible, history = self.state(), self.state(actor), self.history()
            miner = DecisionRuleMiner(learning_path(self.store.directory), self.redact)
            evidence, _ = miner.mine(limit=MAX_EVIDENCE_ALL)
            known = set(history.decision_ids)
            return {"status": state.status, "owned": state.owner == digest(actor),
                    "proposals": len(visible.proposals),
                    "new_decisions": min(MAX_EVIDENCE, sum(item["id"] not in known for item in evidence)),
                    "all_decisions": len(evidence),
                    "analyzed_at": history.analyzed_at,
                    "available": "decision_rule_learning" in self.analyzer().prompts.prompts}

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
        rejected: list[RejectedRuleProposal] = []
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
                state = self.begin(actor, state, payload.get("scope", "new"))
            elif action == "apply" and state.status == "review":
                # 6.0.4: rejected proposals are stored with the same confirmed, versioned action.
                rejected = self.rejections(state, payload.get("rejected", []), payload["choices"])
                if payload["choices"]:
                    self.prepare(state, payload["choices"])
                else:
                    state.status, state.evidence, state.proposals = "done", [], []
                    state.message = ("1 Vorschlag verworfen; er wird nicht wieder vorgeschlagen."
                                     if len(rejected) == 1 else f"{len(rejected)} Vorschläge verworfen; sie "
                                     "werden nicht wieder vorgeschlagen.") + " Keine Regel geändert."
            elif action == "resume" and state.status == "committing":
                state.owner = digest(actor)
            else:
                raise RuleConflict("Aktion passt nicht zum Analysestand")
            self.check(actor)
            if action == "apply" and rejected:
                self.store.save(HISTORY, remember(self.history(), rejected).model_dump(mode="json"))
            state.version += 1
            state.receipts[receipt] = content
            state.receipts = dict(list(state.receipts.items())[-100:])
            self.save(state)
            if state.status == "committing":
                self.finish(actor, state)
            return state

    def rejections(self, state: RuleState, indexes: list[Any],
                   choices: list[dict[str, Any]]) -> list[RejectedRuleProposal]:
        """6.0.4: the proposals to reject, each against its current rule; never also chosen."""
        chosen = {choice.get("index") for choice in choices}
        if (any(type(index) is not int or not 0 <= index < len(state.proposals) for index in indexes)
                or len(set(indexes)) != len(indexes) or chosen & set(indexes)):
            raise ValueError("Ungültige oder doppelte Auswahl zum Verwerfen")
        if not indexes and not choices:
            raise ValueError("Mindestens einen Vorschlag übernehmen oder verwerfen")
        result = []
        for index in indexes:
            proposal = state.proposals[index]
            old = next((topic for topic in state.documents[proposal.category]["topics"]
                        if topic["id"] == proposal.topic_id), None)
            result.append(rejection(proposal, old, self.clock()))
        return result

    def readmit(self, actor: str, version: int, key: str, value: str) -> RuleHistory:
        """6.0.4: lift one rejection; session, version and idempotency key are checked."""
        self.check(actor)
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", key) or not re.fullmatch(r"[a-f0-9]{64}", value):
            raise ValueError("Ungültige Anfrage")
        receipt, content = digest(actor + "\0" + key), digest(value)
        with self.store.locked():
            history = self.history()
            if receipt in history.receipts:
                if history.receipts[receipt] != content:
                    raise RuleConflict("Idempotenzschlüssel bereits anders verwendet")
                return history
            if version != history.rejected_version:
                raise RuleConflict("Liste der verworfenen Vorschläge inzwischen geändert; neu laden.")
            changed = readmit(history, value)
            if changed is history:
                raise RuleConflict("Dieser Vorschlag ist nicht mehr gesperrt.")
            self.check(actor)
            changed.receipts = dict(list({**history.receipts, receipt: content}.items())[-100:])
            self.store.save(HISTORY, changed.model_dump(mode="json"))
            return changed

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

    def begin(self, actor: str, previous: RuleState, scope: str = "new") -> RuleState:
        if previous.status in {"queued", "running", "committing"}:
            raise RuleConflict("Es gibt bereits einen laufenden oder unvollständigen Auftrag")
        documents = {category: RuleValidationService.parse((self.directory / filename).read_text(encoding="utf-8"),
                                                          category) for category, filename in FILES.items()}
        if scope not in SCOPES:
            raise ValueError("Unbekannte Auswahl der Entscheidungen")
        exclude = set(self.history().decision_ids) if scope == "new" else set()
        evidence, skipped = DecisionRuleMiner(learning_path(self.store.directory), self.redact).mine(
            exclude, SCOPES[scope])
        if not evidence and scope == "new" and exclude:
            raise ValueError("Keine neuen verwertbaren Entscheidungen seit der letzten Analyse; "
                             "„Alle bisherigen verwertbaren Entscheidungen“ wählen")
        if not evidence:
            raise ValueError("Keine verwertbaren Entscheidungen im Lernprotokoll vorhanden")
        self.actor = actor
        return RuleState(version=previous.version, owner=digest(actor), status="queued", documents=documents,
                         hashes=self.hashes(), evidence=evidence, skipped=skipped, scope=scope,
                         receipts=previous.receipts,
                         created_at=self.clock())

    def payload(self, documents: dict[str, Any], evidence: list[dict[str, Any]],
                retry: bool = False) -> dict[str, Any]:
        """5.7.7: strong signals in full, repeated rejections counted, unused topics in brief."""
        sent, groups = condense(evidence)
        if retry:
            # The single fallback after truncated output: half the examples, strong signals first.
            sent = sent[:max(1, len(sent) // 2)]
        return redact_data({"topics": compact_topics(documents, evidence), "decisions": sent, "groups": groups,
                            "summary": DecisionRuleMiner.counts(evidence)}, self.redact)

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
            payload = self.payload(state.documents, evidence)
            while len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > self.payload_limit() and evidence:
                evidence.pop()
                state.trimmed += 1
                payload = self.payload(state.documents, evidence)
            if not evidence:
                raise ValueError("Regeln und Belege überschreiten die KI-Nutzlastgrenze")
            state.condensed = sum(group["count"] - group["shown"] for group in payload["groups"])
            documents = state.documents
            _, analysis = analyzer.decision_rule_learning(
                payload, before_call=lambda: self.before_call(self.actor),
                assemble=lambda suggestions: assemble(documents, suggestions),
                retry_payload=self.payload(documents, evidence, retry=True))
            known = {item["id"] for item in payload["decisions"]}
            if any(set(proposal.evidence) - known for proposal in analysis.proposals):
                raise ValueError("Unbekannter Entscheidungsbeleg")
            state.proposals = RuleAnalysis.model_validate(analysis.model_dump()).proposals
            state.evidence = evidence
            state.status, state.message = "review", "Vorschläge einzeln prüfen und bearbeiten; noch nichts gespeichert."
        except Exception as error:
            state.status = "failed"
            state.message = failure_message(error)
            if self.logger is not None:
                # Only the error type and the shown reason; never decisions, mail text or credentials.
                self.logger.event("WARNING", "rule_learning", "analysis_failed", error=type(error).__name__,
                                  scope=state.scope, decisions=len(state.evidence), message=state.message)
        with self.store.locked():
            current = self.state()
            if current.owner != state.owner or current.status != "running" or current.version != state.version:
                return True
            state.version += 1
            self.save(state)
            if state.status == "review":
                history = self.history()
                history.analyzed_at = self.clock()
                history.decision_ids = list(dict.fromkeys(
                    [item["id"] for item in state.evidence] + history.decision_ids))[:10_000]
                self.store.save(HISTORY, history.model_dump(mode="json"))
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
