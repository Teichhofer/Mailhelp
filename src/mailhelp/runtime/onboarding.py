"""8.2: guided 3-step self-service onboarding state, starter topic presets and test-mode dry run."""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from ..config import Topic, TopicsConfig
from ..i18n import msg
from ..persistence.storage import JsonStore, atomic_replace

OnboardingStatus = Literal["not_started", "step_mailbox", "step_target", "step_topics_dryrun", "completed", "skipped"]
STATE_NAME = "onboarding"

STARTER_PRESETS: dict[str, tuple[str, Topic]] = {
    "family": (
        msg("Privat & Familie"),
        Topic(
            id="familie_privat",
            name="Privat und Familie",
            enabled=True,
            description="Persönliche Termine, Familie, Schule, Kinderbetreuung, Gesundheit und Haushalt.",
            examples=["Elternabend", "Arzttermin", "Schulausflug", "Einladung"],
            exclusions=["Allgemeine Werbenewsletter"],
        ),
    ),
    "work": (
        msg("Beruf & Projekte"),
        Topic(
            id="beruf_projekte",
            name="Beruf und Projekte",
            enabled=True,
            description="Besprechungen, Projektfristen, Kundenanfragen und berufliche Aufgaben.",
            examples=["Projektbesprechung", "Abgabefrist", "Kundentermin", "Rückruf"],
            exclusions=["Automatische Systemwerbung"],
        ),
    ),
    "club": (
        msg("Verein & Ehrenamt"),
        Topic(
            id="verein_ehrenamt",
            name="Verein und Ehrenamt",
            enabled=True,
            description="Vereinsveranstaltungen, Training, Helfereinsätze und Versammlungen.",
            examples=["Mitgliederversammlung", "Training", "Helfereinsatz", "Workshop"],
            exclusions=["Sponsorenwerbung Dritter"],
        ),
    ),
}

DEFAULT_DRYRUN_PREVIEWS: tuple[tuple[Literal["event", "task"], str, str], ...] = (
    ("event", "Elternabend / Projektbesprechung (Testmodus-Beispiel)", "Donnerstag, 19:30–21:00 Uhr · Simuliert"),
    ("task", "Unterlagen prüfen und bestätigen (Testmodus-Beispiel)", "Frist: Freitag · Simuliert"),
)


class DryRunPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["event", "task"]
    title: str = Field(min_length=1, max_length=200)
    detail: str = Field(min_length=1, max_length=200)


class OnboardingState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    version: int = 1
    status: OnboardingStatus = "not_started"
    mailbox_checked: bool = False
    mailbox_summary: str = Field(default="", max_length=300)
    target_checked: bool = False
    target_summary: str = Field(default="", max_length=300)
    selected_presets: list[str] = Field(default_factory=lambda: ["family", "work"])
    dryrun_results: list[DryRunPreview] = Field(default_factory=list, max_length=10)
    operations: dict[str, str] = Field(default_factory=dict)


def starter_topics(presets: list[str]) -> list[Topic]:
    chosen = [key for key in STARTER_PRESETS if key in presets]
    if not chosen or any(key not in STARTER_PRESETS for key in presets):
        raise ValueError("Ungültige Themenauswahl.")
    return [STARTER_PRESETS[key][1] for key in chosen]


class OnboardingService:
    def __init__(self, directory: Path, store: JsonStore, authorize: Callable[[str], bool],
                 sign: Callable[[str], str], *,
                 probe_mailbox: Callable[[dict[str, str]], str] | None = None,
                 probe_target: Callable[[dict[str, str]], str] | None = None,
                 dryrun: Callable[[list[str]], list[DryRunPreview]] | None = None) -> None:
        self.directory, self.store, self.authorize, self.sign = directory, store, authorize, sign
        self.probe_mailbox = probe_mailbox or (lambda _form: "IMAP-Postfach lesend geprüft")
        self.probe_target = probe_target or (lambda _form: "Zielsystem lesend geprüft")
        self.dryrun = dryrun or self._default_dryrun

    @staticmethod
    def _default_dryrun(presets: list[str]) -> list[DryRunPreview]:
        starter_topics(presets)
        return [DryRunPreview(kind=kind, title=title, detail=detail)
                for kind, title, detail in DEFAULT_DRYRUN_PREVIEWS]

    def state(self) -> OnboardingState:
        raw = self.store.load(STATE_NAME, {})
        return OnboardingState.model_validate(raw) if raw else OnboardingState()

    def _save(self, state: OnboardingState) -> OnboardingState:
        self.store.save(STATE_NAME, state.model_dump(mode="json"))
        return state

    def _guard(self, actor: str) -> None:
        if not self.authorize(actor):
            raise PermissionError("Sitzung abgelaufen.")

    def _begin(self, actor: str, version: int, key: str, payload: Any) -> tuple[OnboardingState, str, bool]:
        self._guard(actor)
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", key):
            raise ValueError("Ungültiger Idempotenzschlüssel.")
        signature = self.sign(json.dumps([actor, version, payload], sort_keys=True))
        before = self.state()
        if key in before.operations:
            if before.operations[key] != signature:
                raise ValueError("Idempotenzkonflikt.")
            return before, signature, True
        if before.version != version:
            raise ValueError("Versionskonflikt.")
        return before, signature, False

    @staticmethod
    def _commit(before: OnboardingState, key: str, signature: str, **updates: Any) -> OnboardingState:
        operations = dict([*before.operations.items(), (key, signature)][-100:])
        return OnboardingState.model_validate({
            **before.model_dump(mode="json"), **updates,
            "version": before.version + 1, "operations": operations})

    def record_mailbox(self, actor: str, version: int, key: str, form: dict[str, str]) -> OnboardingState:
        clean = {k: v for k, v in form.items() if k not in {"csrf", "key", "version"}}
        with self.store.locked():
            before, signature, repeated = self._begin(actor, version, key, ["mailbox", clean])
            if repeated:
                return before
            summary = self.probe_mailbox(clean).strip()[:300]
            if not summary:
                raise ValueError("Postfachprüfung ohne Ergebnis.")
            self._guard(actor)
            status = "step_target" if before.status in {"not_started", "step_mailbox"} else before.status
            return self._save(self._commit(
                before, key, signature, mailbox_checked=True, mailbox_summary=summary, status=status))

    def record_target(self, actor: str, version: int, key: str, form: dict[str, str]) -> OnboardingState:
        clean = {k: v for k, v in form.items() if k not in {"csrf", "key", "version"}}
        with self.store.locked():
            before, signature, repeated = self._begin(actor, version, key, ["target", clean])
            if repeated:
                return before
            if not before.mailbox_checked:
                raise ValueError("Zuerst Schritt 1 (Postfach) abschließen.")
            summary = self.probe_target(clean).strip()[:300]
            if not summary:
                raise ValueError("Zielprüfung ohne Ergebnis.")
            self._guard(actor)
            initial_states = {"not_started", "step_mailbox", "step_target"}
            status = "step_topics_dryrun" if before.status in initial_states else before.status
            return self._save(self._commit(
                before, key, signature, target_checked=True, target_summary=summary, status=status))

    def run_dryrun(self, actor: str, version: int, key: str, presets: list[str]) -> OnboardingState:
        with self.store.locked():
            before, signature, repeated = self._begin(actor, version, key, ["dryrun", sorted(presets)])
            if repeated:
                return before
            if not before.mailbox_checked or not before.target_checked:
                raise ValueError("Zuerst Postfach und Zielsystem prüfen.")
            starter_topics(presets)
            previews = self.dryrun(presets)[:10]
            self._guard(actor)
            return self._save(self._commit(
                before, key, signature, selected_presets=[p for p in STARTER_PRESETS if p in presets],
                dryrun_results=[item.model_dump(mode="json") for item in previews],
                status="step_topics_dryrun"))

    def activate(self, actor: str, version: int, key: str, confirm: str) -> OnboardingState:
        with self.store.locked():
            before, signature, repeated = self._begin(actor, version, key, ["activate", confirm])
            if repeated:
                return before
            if confirm != "yes":
                raise ValueError("Aktivierung ausdrücklich bestätigen.")
            if not before.mailbox_checked or not before.target_checked or not before.dryrun_results:
                raise ValueError("Vor der Aktivierung alle drei Schritte und den Probelauf abschließen.")
            topics = starter_topics(before.selected_presets)
            self._guard(actor)
            payload = TopicsConfig(topics=topics).model_dump(mode="json")
            atomic_replace(self.directory / "topics.yaml",
                           yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
            return self._save(self._commit(before, key, signature, status="completed"))

    def skip(self, actor: str, version: int, key: str) -> OnboardingState:
        with self.store.locked():
            before, signature, repeated = self._begin(actor, version, key, ["skip"])
            if repeated:
                return before
            self._guard(actor)
            return self._save(self._commit(before, key, signature, status="skipped"))


__all__ = [
    "DEFAULT_DRYRUN_PREVIEWS",
    "STARTER_PRESETS",
    "STATE_NAME",
    "DryRunPreview",
    "OnboardingService",
    "OnboardingState",
    "OnboardingStatus",
    "starter_topics",
]
