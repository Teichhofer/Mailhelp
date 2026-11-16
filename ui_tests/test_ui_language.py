"""6.2.3: no core page shows ISO time stamps or internal status values."""
from __future__ import annotations

import re

from playwright.sync_api import expect

from checks import CORE_PAGES
from conftest import sign_in
from mailhelp.domain.proposal import ProposalStatus

ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
INTERNAL = re.compile(r"\b(" + "|".join(str(status) for status in ProposalStatus) + r")\b")


def findings(text: str) -> list[str]:
    return ISO.findall(text) + INTERNAL.findall(text)


def test_language623_core_pages_show_no_internal_values(page, mailhelp):
    if page.device != "desktop":
        return
    sign_in(page, mailhelp)
    problems = []
    for path in CORE_PAGES:
        page.goto(mailhelp.url + path)
        expect(page.locator("main")).to_be_visible()
        problems += [f"{path}: {item}" for item in findings(page.locator("main").inner_text())]
    assert problems == []


def test_language623_the_check_finds_what_it_looks_for():
    assert findings("2026-11-13T09:48:58Z · rejected · Verworfen") == ["2026-11-13T09:48", "rejected"]
