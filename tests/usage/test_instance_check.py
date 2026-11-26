"""8.7.9 (AP5): the operator's setup check of a customer instance – read-only and without secrets."""
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import yaml

from mailhelp import cli
from mailhelp.app.instance_check import check_instance
from mailhelp.persistence.storage import JsonStore
from mailhelp.usage.valuations import USAGE_DIRECTORY, Valuations
from mailhelp.web.auth import SESSIONS

NOW = datetime(2026, 11, 26, 12, tzinfo=UTC)


def session(number: int, role: str | None, *, instance: str | None = "kunde", expires=NOW + timedelta(days=1)):
    return {"id": f"{number:016x}", "token_hash": "a" * 64, "device": "Gerät", "created_at": NOW.isoformat(),
            "last_used_at": NOW.isoformat(), "expires_at": expires.isoformat(), "role": role, "instance": instance}


def run(directory, state):
    lines: list[str] = []
    code = check_instance(directory, state, out=lines.append, clock=lambda: NOW)
    return code, "\n".join(lines)


@pytest.fixture
def instance(tmp_path):
    state = tmp_path / "data" / "production"
    (tmp_path / "operator.yaml").write_text(yaml.safe_dump(
        {"schema_version": 1, "customer_mode": True, "instance": "kunde", "learning_usd_per_million_tokens": "1.2"}))
    return tmp_path, state


def test_a_fresh_customer_instance_names_every_missing_step_without_secrets(instance):
    directory, state = instance
    (directory / "operator.yaml").write_text(yaml.safe_dump({"schema_version": 1, "customer_mode": True,
                                                             "instance": "kunde"}))
    code, text = run(directory, state)
    assert code == 1 and "OK: Kundenmodus aktiv, Instanz kunde" in text
    for missing in ("FEHLT: Bewertungsstand fehlt", "FEHLT: Preisannahme für Lernläufe fehlt",
                    "FEHLT: Ersteinrichtung offen", "FEHLT: Kein Betreiberzugang: mailhelp --pair --operator"):
        assert missing in text, missing
    assert "4 Schritt(e) offen." in text and not state.exists()  # reading creates nothing


def test_a_ready_instance_counts_only_valid_sessions_of_its_own_instance(instance):
    directory, state = instance
    Valuations(state / USAGE_DIRECTORY).add(Decimal(1), Decimal(900), "operator-cli", NOW - timedelta(days=1))
    (directory / "config.yaml").write_text("{}")
    with JsonStore(state) as store:
        store.save(SESSIONS, {"schema_version": 1, "sessions": [
            session(1, "operator"), session(2, "customer"), session(3, "customer"),
            session(4, "operator", instance="andere"), session(5, "operator", expires=NOW - timedelta(seconds=1)),
            session(6, None)]})
    code, text = run(directory, state)
    assert code == 0 and "Bereit für die Abnahme." in text
    assert "OK: Bewertungsstand 1: 1 USD je EUR, Aufschlag 900 %" in text
    assert "OK: Preisannahme für Lernläufe: 1.2 USD je Million Tokens" in text
    assert "OK: 1 gültige Betreibersitzung(en)" in text and "HINWEIS: 2 gültige Kundensitzung(en)" in text
    assert "a" * 64 not in text and f"{1:016x}" not in text


def test_damaged_session_state_counts_as_no_access(instance):
    directory, state = instance
    state.mkdir(parents=True)
    (state / (SESSIONS + ".json")).write_text("{kaputt", encoding="utf-8")
    code, text = run(directory, state)
    assert code == 1 and "FEHLT: Kein Betreiberzugang" in text


def test_a_self_operated_instance_and_an_invalid_operator_file(tmp_path):
    assert run(tmp_path, tmp_path / "state")[0] == 0
    assert "selbst betriebene Instanz" in run(tmp_path, tmp_path / "state")[1]
    (tmp_path / "operator.yaml").write_text("customer_mode: [")
    code, text = run(tmp_path, tmp_path / "state")
    assert code == 2 and text.startswith("FEHLT: operator.yaml ist ungültig")


def test_the_cli_runs_the_check_before_the_first_setup(instance, monkeypatch, capsys):
    directory, _state = instance
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--check-instance", "--config-directory", str(directory)])
    assert cli.main() == 1 and "FEHLT: Ersteinrichtung offen" in capsys.readouterr().out


def test_a_damaged_valuation_counts_as_missing(instance):
    directory, state = instance
    (state / USAGE_DIRECTORY).mkdir(parents=True)
    (state / USAGE_DIRECTORY / "valuations.json").write_text("{kaputt", encoding="utf-8")
    code, text = run(directory, state)
    assert code == 1 and "FEHLT: Bewertungsstand fehlt" in text
