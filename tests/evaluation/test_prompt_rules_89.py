"""8.9.5 (Planung 8.9 AP4): the contract rules v5 in the prompts, in the checkout and in the package copy.

Regressions of the audit of 26.11.2026: the task prompt asked for an administrative follow-up task to update a calendar
entry while also excluding it (rule conflict, case 20); the event prompt made every appointment in a mail a certain
own one (case 30); a recurrence and a same-day reference date were not asked for (cases 11 and 37); the relevance
stage had no rule for changes and cancellations of own appointments (cases 37 and 38). These tests only check the
configured instructions; whether a model follows them is measured with mailhelp-evaluate on corpus v5.
"""
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def step(relative, name):
    return yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))["prompts"][name]


@pytest.mark.parametrize("relative", ["prompts.yaml", "src/mailhelp/defaults/prompts.yaml"])
def test_regression_the_calendar_handling_is_the_event_not_a_second_task(relative):
    tasks = " ".join(step(relative, "task_extraction")["system_prompt"].split())
    assert "administrative Folgeaufgabe" not in tasks  # the conflicting rule until 8.9.4
    assert "Diese Kalenderbehandlung ist das Event selbst." in tasks and "bleibt eine eigene Aufgabe" in tasks


@pytest.mark.parametrize("relative", ["prompts.yaml", "src/mailhelp/defaults/prompts.yaml"])
def test_regression_participation_lists_names_and_recurrence(relative):
    events = " ".join(step(relative, "event_extraction")["system_prompt"].split())
    assert "betrifft sie deshalb grundsätzlich selbst" not in events  # until 8.9.4: every appointment was own
    assert "Eine bloße Termin- oder Sitzungsliste" in events and 'certainty "uncertain"' in events
    assert '"Hr. Lehmann"' in events and 'nie "other"' in events
    assert "übernimmt die Wiederholungsangabe wörtlich in date_text" in events
    assert 'date_text und original_date_text sind beide "03.02.2027"' in events
    assert "„Montag, den 08.03.2027“" in events


@pytest.mark.parametrize("relative", ["prompts.yaml", "src/mailhelp/defaults/prompts.yaml"])
def test_regression_changes_of_own_appointments_are_relevant(relative):
    relevance = " ".join(step(relative, "relevance")["system_prompt"].split())
    assert "keine allgemeine Veranstaltungswerbung" in relevance and "nie irrelevant" in relevance
    router = " ".join(step(relative, "action_router")["system_prompt"].split())
    assert "ergänze nie einen nicht genannten Kanal" in router and "ausdrücklich per Mail" in router


@pytest.mark.parametrize("relative", ["decisions_prompts.yaml", "src/mailhelp/defaults/decisions_prompts.yaml"])
def test_regression_the_jev_relevance_knows_changes_of_own_appointments(relative):
    prompts = yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))["prompts"]["relevance"]
    decision = " ".join(prompts["decision"]["instructions"].split())
    topic = " ".join(prompts["topic_match"]["instructions"].split())
    assert "keine allgemeine Veranstaltungswerbung" in decision and "eigenen Termins ist ein persönlicher" in topic


def test_the_package_copies_equal_the_checkout():
    for name in ("prompts.yaml", "decisions_prompts.yaml"):
        assert (ROOT / name).read_text(encoding="utf-8") == (ROOT / "src/mailhelp/defaults" / name).read_text(
            encoding="utf-8")
