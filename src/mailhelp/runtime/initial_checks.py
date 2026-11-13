"""6.1.2: "Prüfen" in every step of the first setup – checks the entered values and changes nothing.

Neither ``.env`` nor ``config.yaml`` nor the setup draft is written. Secrets typed into the form
live only for the duration of the check. At most ten checks per minute and session protect the
mailbox against password guessing and provider lockouts.
"""
from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from .initial_setup import FIELDS, SECRET_FIELDS
from .setup_messages import CheckResult, Finding, SetupProblem, classify, finding
from .web_password import WebPassword

if TYPE_CHECKING:
    from .initial_setup import InitialDraft, InitialSetup

LIMIT, WINDOW = 10, 60.0
# Validation errors of these fields have a more specific message than "invalid".
FIELD_CODES = {"timezone": "zone.unknown"}


def invalid_findings(error: ValidationError) -> list[Finding]:
    """One finding per invalid field; the message comes from the catalogue, not from pydantic."""
    findings = []
    for item in error.errors():
        name = ".".join(str(part) for part in item["loc"])
        known = name if any(name in fields for fields in FIELDS.values()) else None
        findings.append(finding(FIELD_CODES.get(name, "invalid"), field=known, detail="" if known else name))
    return findings or [finding("invalid")]


class InitialChecks:
    def __init__(self, setup: InitialSetup, clock: Callable[[], float] = time.monotonic):
        self.setup, self.clock = setup, clock
        self._recent: dict[str, deque[float]] = {}

    def _limit(self, actor: str) -> None:
        now = self.clock()
        recent = self._recent.setdefault(actor, deque())
        while recent and now - recent[0] >= WINDOW:
            recent.popleft()
        if len(recent) >= LIMIT:
            raise SetupProblem("limit")
        recent.append(now)

    def check(self, actor: str, form: dict[str, str]) -> CheckResult:
        """The result of one step; raises PermissionError for an expired session, ValueError for a bad step."""
        step = int(form.get("step", "0"))
        if step not in FIELDS:
            raise ValueError("Ungültiger Prüfschritt.")
        self.setup._guard(actor)
        try:
            self._limit(actor)
        except SetupProblem as problem:
            return CheckResult(step=step, ok=False, findings=[finding(problem.code)])
        state = self.setup.state()
        try:
            candidate = self.setup._candidate(state, step, form)
        except ValidationError as error:
            return CheckResult(step=step, ok=False, findings=invalid_findings(error))
        except ValueError:
            return CheckResult(step=step, ok=False, findings=[finding("invalid", field="imap.port")])
        if step == 1:
            return self._web(step, form)
        env = {**self.setup.environment(), **{name: form[name] for name in SECRET_FIELDS[step] if form.get(name)}}
        found = self._probe(step, candidate, env)
        # The session is checked again: a check that outlived its session shows nothing.
        self.setup._guard(actor)
        return found if isinstance(found, CheckResult) else self._interpret(step, candidate, found)

    def check_all(self, actor: str) -> list[CheckResult]:
        """6.1: the final overview – every step with the saved values; counts as one check."""
        self.setup._guard(actor)
        try:
            self._limit(actor)
        except SetupProblem as problem:
            return [CheckResult(step=5, ok=False, findings=[finding(problem.code)])]
        state = self.setup.state()
        results = [self._web(1, {"timezone": str(state.config.get("timezone", ""))})]
        env = self.setup.environment()
        found = [self._probe(step, state, env) for step in (2, 3, 4)]
        self.setup._guard(actor)
        return results + [item if isinstance(item, CheckResult) else self._interpret(step, state, item)
                          for step, item in zip((2, 3, 4), found, strict=True)]

    def _web(self, step: int, form: dict[str, str]) -> CheckResult:
        zone, password = form.get("timezone", ""), form.get("password", "")
        # The time zone itself was validated with the configuration (FIELD_CODES: zone.unknown).
        findings = []
        if password:
            if len(password) < 12 or len(password) > 1024:
                findings.append(finding("password.too_short"))
            elif any(ord(char) < 32 for char in password):
                findings.append(finding("password.invalid"))
        elif WebPassword(self.setup.store).state().digest:
            findings.append(finding("password.kept", severity="ok"))
        else:
            findings.append(finding("password.missing"))
        ok = not any(item.severity == "error" for item in findings)
        if ok:
            findings.insert(0, finding("step1.ok", severity="ok"))
        return CheckResult(step=step, ok=ok, findings=findings, facts={"Zeitzone": zone} if ok else {})

    def _probe(self, step: int, candidate: InitialDraft, env: dict[str, str]) -> CheckResult | dict[str, Any]:
        """The probe's findings, or a failed result; the text of an error never leaves this method."""
        try:
            return self.setup._probe(step, candidate, env)
        except SetupProblem as problem:
            return CheckResult(step=step, ok=False, findings=[finding(problem.code, detail=problem.detail,
                                                                      field=problem.field)])
        except Exception as error:  # noqa: BLE001 – classified by type only
            return CheckResult(step=step, ok=False, findings=[finding(classify(error))])

    def _interpret(self, step: int, candidate: InitialDraft, found: dict[str, Any]) -> CheckResult:
        return {2: self._mailbox, 3: self._llm, 4: self._targets}[step](step, candidate, found)

    @staticmethod
    def _mailbox(step: int, candidate: InitialDraft, found: dict[str, Any]) -> CheckResult:
        findings = [finding("imap.ok", severity="ok")]
        if found.get("drafts_missing"):
            findings.append(finding("imap.drafts_missing", severity="warning",
                                    detail=found.get("drafts") or ""))
        facts = {"Server": found.get("server", ""), "Ordner gefunden": str(len(found["folders"])),
                 "Posteingang": found["inbox"], "Entwurfsordner": found["drafts"] or "nicht erkannt"}
        return CheckResult(step=step, ok=True, findings=findings, facts=facts,
                           choices={"folders": found["folders"], "inbox": [found["inbox"]],
                                    "drafts": [found["drafts"]] if found["drafts"] else []})

    @staticmethod
    def _llm(step: int, candidate: InitialDraft, found: dict[str, Any]) -> CheckResult:
        models = list(found["models"])
        if candidate.config.get("llm", {}).get("provider") == "ollama":
            if candidate.model and candidate.model not in models:
                return CheckResult(step=step, ok=False, choices={"models": models},
                                   findings=[finding("llm.ollama_model_missing", detail=", ".join(models[:20]))])
            return CheckResult(step=step, ok=True, findings=[finding("llm.ok", severity="ok")],
                               facts={"Anbieter": "Ollama", "Installierte Modelle": ", ".join(models)},
                               choices={"models": models})
        facts = {"Anbieter": "OpenRouter", "Geprüfte Modelle": ", ".join(models)}
        if found.get("balance") is not None:
            facts["Guthaben"] = f"{found['balance']:.2f} $".replace(".", ",")
        if found.get("key_remaining") is not None:
            facts["Restlimit des Schlüssels"] = f"{found['key_remaining']:.2f} $".replace(".", ",")
        return CheckResult(step=step, ok=True, findings=[finding("llm.ok", severity="ok")], facts=facts)

    @staticmethod
    def _targets(step: int, candidate: InitialDraft, found: dict[str, Any]) -> CheckResult:
        return CheckResult(step=step, ok=True, findings=[finding("target.ok", severity="ok")],
                           facts={"Kalender": found.get("calendar", ""), "Aufgaben": found.get("tasks", "")})


__all__ = ["LIMIT", "WINDOW", "InitialChecks", "invalid_findings"]
