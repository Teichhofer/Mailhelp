"""Planung 5.2, step V9: the check of a written entry in the browser, with a read-only recheck."""
import re
import time
from datetime import date

from playwright.sync_api import expect

from checks import audit
from conftest import sign_in
from tests.fakes.verifying_writer import SimulatedProvider, VerifyingWriter
from tests.scenarios.web_scenario import mail_id, proposal, save_mail


def test_a_deviation_shows_expected_and_actual_and_a_recheck_reads_again(page, mailhelp):
    provider = SimulatedProvider()
    item = proposal(60, "u", title="Unterlagen senden", status="confirmed", confirmed_web_actor=None,
                    due=date(2026, 11, 11))
    save_mail(mailhelp.store, 60, "Schule <schule@example.test>", "Unterlagen", [item])
    mailhelp.dialog.writers["todoist"] = VerifyingWriter(provider, script=[{"due": "2026-11-12"}])
    mailhelp.dialog.write_executor.execute(item)
    sign_in(page, mailhelp)
    page.goto(f"{mailhelp.url}/vorschlag/{mail_id(60)}/u")
    block = page.locator(".verification")
    expect(block).to_contain_text("Eintrag vorhanden, Angaben weichen ab")
    expect(block.locator("tbody tr")).to_have_count(1)
    expect(block.locator("tbody tr")).to_contain_text("12.11.2026")
    assert audit(page, "verification-52-" + page.device, page.mobile) == []
    block.get_by_role("button", name="Erneut prüfen").click()
    page.wait_for_url(re.compile(r"aktion="))
    checks = mailhelp.dialog.write_executor.verification
    for _attempt in range(100):  # the operator thread reads the entry again in the background
        if checks.load(item).state.value == "verified":
            break
        time.sleep(0.1)
    page.goto(f"{mailhelp.url}/vorschlag/{mail_id(60)}/u")
    expect(page.locator(".verification")).to_contain_text("Angelegt und geprüft")
    assert len(provider.writes) == 1 and len(provider.reads) == 2
    assert page.errors == []
