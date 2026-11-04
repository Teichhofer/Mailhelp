"""Versioned browser learning jobs and recoverable local configuration commits."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..config import IrrelevantTopicsConfig, Settings, Topic, TopicsConfig, read_yaml
from ..configuration import file_hash
from ..llm.learning import _topic_id, topics_document
from ..mailbox.sender_filter import change_irrelevant_senders
from ..models import IrrelevantSenders, LearnedCategory
from ..storage import atomic_replace

FILES = ("config.yaml", "topics.yaml", "irrelevant_topics.yaml", "irrelevant-senders.json")


class LearningSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mailbox: int = Field(ge=1, le=99)
    folders: list[str] = Field(min_length=1, max_length=100)
    count: int = Field(ge=1, le=1000)
    budget_usd: float = Field(gt=0, le=1000, allow_inf_nan=False)
    # User-supplied ceiling, never a guessed or hard-coded provider price.
    usd_per_million_tokens: float = Field(gt=0, le=10000, allow_inf_nan=False)


class LearningCard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: LearnedCategory
    evidence: list[str] = Field(default_factory=list, max_length=1000)
    senders: list[str] = Field(default_factory=list, max_length=1000)


class LearningJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    version: int = 0
    generation: int = Field(default=0, ge=0)
    status: Literal["empty", "running", "paused", "cancelled", "review", "committing", "done"] = "empty"
    actor: str = ""
    selection: LearningSelection | None = None
    revision: str = ""
    candidates: list[dict] | None = None
    cursor: int = 0
    failures: int = 0
    reserved_tokens: int = 0
    cards: list[LearningCard] = Field(default_factory=list)
    folders: dict[str, bool] = Field(default_factory=dict)
    operations: dict[str, str] = Field(default_factory=dict)
    message: str = ""
    commit: dict[str, str] = Field(default_factory=dict)
    before: dict[str, str] = Field(default_factory=dict)
    choices: dict[str, dict] = Field(default_factory=dict)


class LearningConflict(ValueError):
    pass


class LearningJobs:
    def __init__(self, configuration, active, estimate):
        self.configuration, self.active, self.estimate = configuration, active, estimate
        self.store = configuration.store
        self.lock = self.store._thread_lock

    @property
    def directory(self):
        return self.configuration.directory

    def state(self) -> LearningJob:
        return self.store.load_model("web-learning", LearningJob, LearningJob())

    def save(self, state: LearningJob) -> None:
        self.store.save("web-learning", state.model_dump(mode="json"))

    def hashes(self) -> dict[str, str]:
        return {name: file_hash(self.directory / name) if (self.directory / name).exists() else "" for name in FILES}

    def revision(self) -> str:
        return hashlib.sha256(json.dumps(self.hashes(), sort_keys=True).encode()).hexdigest()

    def recover(self) -> None:
        with self.lock:
            state = self.state()
            if state.status == "committing":
                self.finish_commit(state)
            elif state.status == "running":
                state.status, state.message = "paused", "Nach Neustart pausiert; mit gültiger Sitzung fortsetzen."
                state.version += 1
                self.save(state)

    def check(self, actor: str) -> None:
        if not self.active(actor):
            raise LearningConflict("Sitzung abgelaufen; erneut anmelden.")

    def change(self, actor: str, version: int, key: str, action: str, payload: dict) -> LearningJob:
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", key):
            raise LearningConflict("Ungültiger Idempotenzschlüssel")
        digest = hashlib.sha256(json.dumps([actor, version, action, payload], sort_keys=True).encode()).hexdigest()
        with self.lock:
            self.check(actor)
            state = self.state()
            if key in state.operations:
                if state.operations[key] != digest:
                    raise LearningConflict("Idempotenzkonflikt")
                return state
            if version != state.version:
                raise LearningConflict("Lernstand geändert; neu laden.")
            self._action(state, actor, action, payload)
            self.check(actor)
            state.version += 1
            state.operations[key] = digest
            state.operations = dict(list(state.operations.items())[-200:])
            self.save(state)
            if state.status == "committing":
                self.finish_commit(state)
            return state

    def _action(self, state, actor, action, payload):
        if action == "start":
            if state.status in {"running", "paused", "committing"}:
                raise LearningConflict("Es gibt bereits einen offenen Lernlauf.")
            selection = LearningSelection.model_validate(payload)
            settings = Settings.model_validate(read_yaml(self.directory / "config.yaml"))
            mailbox = settings.imap.mailbox(selection.mailbox)
            if mailbox is None or not mailbox.enabled or len(set(selection.folders)) != len(selection.folders):
                raise LearningConflict("Ungültiges Postfach oder doppelte Ordner")
            known = (
                self.store.load("mailbox-folders", {})
                .get("mailboxes", {})
                .get(str(selection.mailbox), {})
                .get("folders", [])
            )
            names = {item["name"] for item in known}
            if not set(selection.folders) <= names | set(mailbox.folders):
                raise LearningConflict("Ordnerliste zuerst über den Postfachabruf aktualisieren.")
            estimate = self.estimate(selection)
            if estimate * selection.usd_per_million_tokens / 1000000 > selection.budget_usd:
                raise LearningConflict("Budget reicht für den geschätzten Lauf nicht aus.")
            fresh = LearningJob(status="running", actor=actor, selection=selection, revision=self.revision(),
                                generation=state.generation + 1)
            state.__dict__.update(fresh.model_dump(exclude={"version", "operations"}))
            state.selection = selection
        elif action in {"pause", "resume", "cancel"}:
            allowed = {"pause": {"running"}, "resume": {"paused"}, "cancel": {"running", "paused", "review"}}
            if state.status not in allowed[action]:
                raise LearningConflict("Aktion passt nicht zum Lernstand.")
            if action == "resume" and state.revision != self.revision():
                raise LearningConflict("Konfiguration geändert; neuen Lernlauf starten.")
            state.status = {"pause": "paused", "resume": "running", "cancel": "cancelled"}[action]
            state.actor, state.message = actor, ""
        elif action == "edit" and state.status == "review":
            index = payload["index"]
            if type(index) is not int or not 0 <= index < len(state.cards):
                raise LearningConflict("Ungültige Karte")
            LearnedCategory(name=payload["name"], description=payload["description"])
            if payload["kind"] not in {"relevant", "irrelevant", "skip"}:
                raise LearningConflict("Ungültige Themenart")
            state.choices[str(index)] = payload
        elif action == "folder" and state.status == "review":
            if payload["name"] not in state.folders or type(payload["selected"]) is not bool:
                raise LearningConflict("Ungültiger Ordner")
            state.folders[payload["name"]] = payload["selected"]
        elif action == "apply" and state.status == "review":
            self.prepare_commit(
                state,
                {
                    "cards": [value for value in state.choices.values() if value["kind"] != "skip"],
                    "folders": [name for name, selected in state.folders.items() if selected],
                },
            )
        else:
            raise LearningConflict("Ungültige Aktion")

    def prepare_commit(self, state: LearningJob, payload: dict) -> None:
        if state.revision != self.revision() or set(payload) != {"cards", "folders"}:
            raise LearningConflict("Konfiguration oder Auswahl geändert; neu prüfen.")
        assert state.selection is not None
        documents = {
            name: (self.directory / name).read_text(encoding="utf-8")
            for name in FILES
            if (self.directory / name).exists()
        }
        groups = {
            name: [Topic.model_validate(item) for item in read_yaml(self.directory / name)["topics"]]
            for name in ("topics.yaml", "irrelevant_topics.yaml")
        }
        blocked = IrrelevantSenders.model_validate_json(documents.get("irrelevant-senders.json", "{}"))
        seen = set()
        for choice in payload["cards"]:
            if set(choice) != {"index", "kind", "name", "description", "global", "block_senders"}:
                raise LearningConflict("Ungültige Themenauswahl")
            index = choice["index"]
            if type(index) is not int or not 0 <= index < len(state.cards) or index in seen:
                raise LearningConflict("Ungültiger oder doppelter Themenbeleg")
            seen.add(index)
            if choice["kind"] not in {"relevant", "irrelevant"}:
                raise LearningConflict("Ungültige Themenart")
            card = state.cards[index]
            target = "topics.yaml" if choice["kind"] == "relevant" else "irrelevant_topics.yaml"
            used = {item.id for item in groups[target]}
            scope = None if choice["global"] is True else [state.selection.mailbox]
            category = card.category.model_copy(update={"name": choice["name"], "description": choice["description"]})
            groups[target].append(
                Topic(
                    id=_topic_id(category.name, used),
                    name=category.name,
                    description=category.description,
                    examples=category.examples,
                    mailboxes=scope,
                    enabled=True,
                )
            )
            if choice["kind"] == "irrelevant" and choice["block_senders"] is True and card.senders:
                blocked = change_irrelevant_senders(
                    blocked, True, card.senders, [], None if scope is None else state.selection.mailbox
                )
        for name, topics in groups.items():
            model = TopicsConfig if name == "topics.yaml" else IrrelevantTopicsConfig
            documents[name] = topics_document(model(topics=topics).topics)
        documents["irrelevant-senders.json"] = blocked.model_dump_json(indent=2) + "\n"
        selected = payload["folders"]
        if not isinstance(selected, list) or not set(selected) <= set(state.folders):
            raise LearningConflict("Ungültige Ordnerauswahl")
        import yaml

        raw = read_yaml(self.directory / "config.yaml")
        section = raw["imap"]
        if "mailboxes" in section:
            section = next(box for box in section["mailboxes"] if box["id"] == state.selection.mailbox)
        section["folders"] = list(dict.fromkeys([*section["folders"], *selected]))
        Settings.model_validate(raw)
        documents["config.yaml"] = yaml.safe_dump(raw, allow_unicode=True, sort_keys=False)
        state.before, state.commit, state.status = self.hashes(), documents, "committing"

    def finish_commit(self, state: LearningJob) -> None:
        # Roll forward only our unchanged inputs or already installed outputs.
        for name, content in state.commit.items():
            path = self.directory / name
            current = file_hash(path) if path.exists() else ""
            after = hashlib.sha256(content.encode()).hexdigest()
            if current not in {state.before[name], after}:
                raise LearningConflict("Übernahme unterbrochen; Datei wurde außerhalb des Lernlaufs geändert.")
        for name, content in state.commit.items():
            atomic_replace(self.directory / name, content)
        state.status, state.message, state.commit = (
            "done",
            "Auswahl gemeinsam gespeichert. Konfiguration neu laden.",
            {},
        )
        self.save(state)


__all__ = ["LearningJob", "LearningJobs", "LearningSelection", "LearningCard", "LearningConflict"]
