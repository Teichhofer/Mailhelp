"""6.0.4: rejecting a rule proposal and admitting it again, with and without JavaScript."""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from checks import audit
from conftest import sign_in
from tests.fakes.rule_learning import RuleHarness, record


@pytest.fixture
def rules(mailhelp, tmp_path):
    harness = RuleHarness(tmp_path, mailhelp.store,
                          lambda actor: actor.startswith("web:") and mailhelp.auth.active(actor[4:]))
    mailhelp.site.rule_learning.service = harness.service
    harness.log(record())
    return harness


def review(page, mailhelp, rules):
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/lernen/entscheidungen")
    page.get_by_label("Datenübertragung und kostenpflichtige Analyse ausdrücklich starten").check()
    page.get_by_role("button", name="Entscheidungen analysieren", exact=True).click()
    expect(page.get_by_text(re.compile("^Analysestand:"))).to_contain_text("Wartet")
    assert rules.service.tick()
    page.reload()
    expect(page.get_by_role("heading", name="Vorschläge prüfen", exact=True)).to_be_visible()


def reject_and_readmit(page, mailhelp, rules, label):
    page.get_by_label("Verwerfen – nicht wieder vorschlagen", exact=True).check()
    page.get_by_role("button", name="Ausgewählte Änderungen prüfen", exact=True).click()
    expect(page.get_by_role("heading", name="Wird verworfen und nicht wieder vorgeschlagen")).to_be_visible()
    page.get_by_label("Verwerfen ausdrücklich bestätigen", exact=True).check()
    page.get_by_role("button", name="Vorschläge verwerfen", exact=True).click()
    expect(page.get_by_text("1 Vorschlag verworfen", exact=False)).to_be_visible()
    assert rules.activated == [] and len(rules.service.history().rejected) == 1
    page.get_by_text("Zuvor verworfene Vorschläge anzeigen (1)", exact=True).click()
    expect(page.get_by_text("+ Ausschluss: unverbindliche werbung", exact=True)).to_be_visible()
    if label == "js":  # axe runs inside the page and needs JavaScript
        assert audit(page, f"reject604-{page.device}", page.mobile) == []
    page.get_by_role("button", name="Schule wieder zulassen", exact=True).click()
    expect(page.get_by_text("Zuvor verworfene Vorschläge anzeigen", exact=False)).to_have_count(0)
    assert rules.service.history().rejected == []


def test_reject604_reject_a_proposal_and_admit_it_again(page, mailhelp, rules):
    review(page, mailhelp, rules)
    expect(page.get_by_text("0 zur Übernahme ausgewählt · 0 zum Verwerfen markiert.", exact=True)).to_be_visible()
    reject_and_readmit(page, mailhelp, rules, "js")
    assert page.errors == []


def test_reject604_works_without_javascript(page, mailhelp, rules):
    page.cdp.send("Emulation.setScriptExecutionDisabled", {"value": True})
    review(page, mailhelp, rules)
    reject_and_readmit(page, mailhelp, rules, "nojs")
