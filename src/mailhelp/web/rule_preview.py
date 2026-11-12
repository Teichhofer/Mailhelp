"""Persistent, session-owned snapshots of the effective manual rule edits."""
from __future__ import annotations

import secrets
from typing import Any

from ..rule_learning.service import DecisionRuleLearning, digest
from ..rule_learning.validation import RuleConflict
from .pages import e
from .rule_compare import compare


def preview_name(actor: str) -> str:
    return "rule-preview-" + digest(actor)


def prepare(service: DecisionRuleLearning, actor: str, version: int,
            choices: list[dict[str, Any]], values: dict[str, str]) -> tuple[dict[str, Any], Any]:
    with service.store.locked():
        service.check(actor)
        state = service.state(actor)
        if state.status != "review" or state.version != version:
            raise RuleConflict("Analysestand veraltet; neu laden.")
        # Validate the complete candidate using the same rules as the eventual write.
        service.prepare(state.model_copy(deep=True), choices)
        edits = {key: value for key, value in values.items() if key.startswith((
            "selected-", "id-", "name-", "description-", "examples-", "exclusions-", "enabled-", "yaml-"))}
        draft = {"version": version, "key": secrets.token_hex(16), "choices": choices, "values": edits}
        service.check(actor)
        service.store.save(preview_name(actor), draft)
        return draft, state


def editing(service: DecisionRuleLearning, actor: str, version: int) -> dict[str, str]:
    draft = service.store.load(preview_name(actor), {})
    if isinstance(draft, dict) and draft.get("version") == version:
        values: dict[str, str] = draft.get("values", {})
        return values
    return {}


def confirmed(service: DecisionRuleLearning, actor: str, form: dict[str, str]) -> list[dict[str, Any]]:
    service.check(actor)
    draft = service.store.load(preview_name(actor), {})
    if (not draft or form.get("preview_key") != draft["key"] or form["key"] != draft["key"]
            or int(form["version"]) != draft["version"]):
        raise RuleConflict("Prüfstand fehlt oder wurde ersetzt. Änderungen erneut prüfen.")
    choices: list[dict[str, Any]] = draft["choices"]
    return choices  # No editable client payload is trusted at confirmation time.


def comparison(state: Any, draft: dict[str, Any]) -> str:
    body = ('<section class="rule-final"><h1>Bearbeitete Änderungen prüfen</h1>'
            '<p>Dieser Vergleich zeigt die tatsächlich ausgewählten Feld- oder YAML-Werte. '
            'Noch wurden keine Themenregeln gespeichert.</p>')
    for choice in draft["choices"]:
        proposal = state.proposals[choice["index"]]
        before = next((topic for topic in state.documents[proposal.category]["topics"]
                       if topic["id"] == proposal.topic_id), None)
        body += f'<section class="card"><h3>{e(choice["topic"]["name"])}</h3>'
        body += compare(before, choice["topic"]) + '</section>'
    return body + '</section>'
