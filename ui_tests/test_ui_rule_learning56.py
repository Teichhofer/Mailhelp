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


def start_review(page, mailhelp, rules, scope=None):
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/themen")
    page.get_by_role("link", name="Aus Entscheidungen lernen", exact=True).click()
    expect(page.get_by_role("radio", name=re.compile("^Nur neue Entscheidungen"))).to_be_checked()
    if scope is not None:
        page.get_by_role("radio", name=re.compile("^" + scope)).check()
    page.get_by_label("Datenübertragung und kostenpflichtige Analyse ausdrücklich starten").check()
    page.get_by_role("button", name="Entscheidungen analysieren", exact=True).click()
    expect(page.get_by_text(re.compile("^Analysestand:"))).to_contain_text("Wartet")
    assert rules.service.tick()
    page.reload()
    expect(page.get_by_role("heading", name="Vorschläge prüfen", exact=True)).to_be_visible()


def choose(page):
    page.get_by_label("Diesen Vorschlag übernehmen", exact=True).check()
    page.get_by_label("Ausgewählte Regeländerungen ausdrücklich bestätigen", exact=True).check()


def test_rule56_old_new_hand_edit_and_confirmation_are_usable(page, mailhelp, rules):
    original = rules.service.hashes()
    start_review(page, mailhelp, rules)
    assert rules.service.hashes() == original
    # 5.7.3: the left column is the shared comparison; the action bar counts the selection.
    expect(page.get_by_role("heading", name="Bisherige Regel und Vorschlag", exact=True)).to_be_visible()
    expect(page.get_by_text("0 von 1 Vorschlägen ausgewählt.", exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="Vorgeschlagene Regel · bearbeiten", exact=True)).to_be_visible()
    selection = page.locator('label').filter(has=page.locator('input[name="selected-0"]')).bounding_box()
    next_label = page.locator('label[for="rule-0-id"]').bounding_box()
    assert next_label["y"] >= selection["y"] + selection["height"]
    assert audit(page, "rule-learning56-review-" + page.device, page.mobile) == []
    choose(page)
    expect(page.get_by_text("1 von 1 Vorschlägen ausgewählt.", exact=True)).to_be_visible()
    page.get_by_label("Diesen Vorschlag übernehmen", exact=True).uncheck()
    expect(page.get_by_text("0 von 1 Vorschlägen ausgewählt.", exact=True)).to_be_visible()
    page.get_by_label("Diesen Vorschlag übernehmen", exact=True).check()
    page.get_by_label(re.compile("^Name")).fill("Manuell: Schultermine")
    page.get_by_label(re.compile("^Beispiele")).fill("Verbindlicher Elternabend\nAusflug")
    page.get_by_label(re.compile("^Ausschlüsse")).fill("Unverbindlicher Newsletter")
    page.get_by_role("button", name="Ausgewählte Änderungen prüfen und übernehmen", exact=True).click()
    expect(page.get_by_text(re.compile("^Analysestand:"))).to_contain_text("Übernommen")
    assert rules.activated[0][0].name == "Manuell: Schultermine"
    assert rules.activated[0][0].examples == ["Verbindlicher Elternabend", "Ausflug"]
    assert len(rules.analyzer.calls) == 1 and mailhelp.writer.created == []
    assert page.errors == []


def test_rule56_yaml_error_and_external_conflict_keep_files_and_inputs(page, mailhelp, rules):
    start_review(page, mailhelp, rules)
    choose(page)
    page.get_by_label(re.compile("^Name")).fill("Nicht verlieren")
    page.get_by_text("Vollständiges Themen-YAML bearbeiten (optional)", exact=True).click()
    page.get_by_label("YAML ersetzt die Feldwerte vollständig", exact=True).fill("id: [")
    original = rules.service.hashes()
    page.get_by_role("button", name="Ausgewählte Änderungen prüfen und übernehmen", exact=True).click()
    expect(page.get_by_text(re.compile("YAML-Syntaxfehler"))).to_be_visible()
    expect(page.get_by_label(re.compile("^Name"))).to_have_value("Nicht verlieren")
    expect(page.get_by_label("YAML ersetzt die Feldwerte vollständig", exact=True)).to_have_value("id: [")
    assert rules.service.hashes() == original
    page.get_by_text("Vollständiges Themen-YAML bearbeiten (optional)", exact=True).click()
    page.get_by_label("YAML ersetzt die Feldwerte vollständig", exact=True).fill("")
    with (rules.directory / "topics.yaml").open("a", encoding="utf-8") as stream:
        stream.write("# externally changed\n")
    changed = rules.service.hashes()
    choose(page)
    page.get_by_role("button", name="Ausgewählte Änderungen prüfen und übernehmen", exact=True).click()
    expect(page.get_by_text(re.compile("inzwischen geändert"))).to_be_visible()
    assert rules.service.hashes() == changed and rules.activated == []


def test_rule56_review_and_apply_work_without_javascript(page, mailhelp, rules):
    page.cdp.send("Emulation.setScriptExecutionDisabled", {"value": True})
    # 5.7.6: the scope is an ordinary radio choice and works without scripts.
    start_review(page, mailhelp, rules, scope="Alle bisherigen verwertbaren Entscheidungen")
    expect(page.get_by_text(re.compile(r"aus 1 Entscheidungen \(alle bisherigen\)"))).to_be_visible()
    choose(page)
    page.get_by_label(re.compile("^Beschreibung")).fill("Ohne JavaScript von Hand bearbeitet")
    page.get_by_role("button", name="Ausgewählte Änderungen prüfen und übernehmen", exact=True).click()
    expect(page.get_by_text(re.compile("^Analysestand:"))).to_contain_text("Übernommen")
    assert rules.activated[0][0].description == "Ohne JavaScript von Hand bearbeitet"
    assert mailhelp.writer.created == []
