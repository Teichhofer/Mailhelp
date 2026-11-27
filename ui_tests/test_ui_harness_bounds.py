"""8.7.13: the harness waits for what it claims to wait for, and never without a time limit.

Regressions of the Linux browser suite (the CI job hung for hours, help-window tests failed now and then):

* ``wait_for_function`` counts a returned promise as true, even one that resolves to false. Async conditions
  therefore passed at once; a reload overtook the closing of the help window, and a test went offline while
  the new service worker was still activating.
* A navigation stuck behind that worker left the renderer silent. The coverage collection in the teardown is
  a DevTools call without a time limit and waited until the job was cancelled.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError

from conftest import Page, wait_until

UI_TESTS = Path(__file__).resolve().parent


@pytest.fixture
def blank(browser):
    context = browser.new_context()
    page = Page(context.new_page(), "desktop")
    page.page.set_content("<p>Bereit</p>")
    try:
        yield page
    finally:
        context.close()


def test_playwright_counts_a_promise_of_false_as_true(blank):
    # The reason for wait_until: should Playwright ever await the promise, this documents the change.
    blank.wait_for_function("async () => false", timeout=1000)


def test_wait_until_waits_for_an_async_condition(blank):
    blank.evaluate("setTimeout(() => { window.ready = true; }, 300)")
    wait_until(blank, "async () => window.ready === true")
    assert blank.evaluate("window.ready") is True


def test_wait_until_fails_on_an_async_condition_that_stays_false(blank):
    started = time.monotonic()
    with pytest.raises(PlaywrightError):
        wait_until(blank, "async () => false", timeout=700)
    assert time.monotonic() - started < 10


def test_wait_until_passes_the_argument_and_retries_after_an_error(blank):
    blank.evaluate("window.calls = 0")
    wait_until(blank, """async (limit) => {
      window.calls += 1;
      if (window.calls < limit) throw new Error('not yet');
      return true;
    }""", 3)
    assert blank.evaluate("window.calls") >= 3


def test_no_browser_test_hands_an_async_condition_to_wait_for_function():
    found = []
    for path in sorted(UI_TESTS.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for call in re.finditer(r"wait_for_function\(\s*f?(\"\"\"(.*?)\"\"\"|\"(.*?)\")", text, re.S):
            body = call.group(2) or call.group(3) or ""
            if re.search(r"\basync\b|\bawait\b|\.then\(|Promise|serviceWorker\.ready|getRegistration", body):
                found.append((path.name, body.strip().splitlines()[0]))
    # Allowed: the poll inside wait_until, whose promise it never returns, and the documentation above.
    assert found == [("conftest.py", "arg => {{"), ("test_ui_harness_bounds.py", "async () => false")]


def test_settle_collects_from_an_answering_page_and_skips_a_silent_one(blank):
    assert blank.responsive()
    blank.settle()
    blank.evaluate("setTimeout(() => { for (;;) {} }, 0)")  # the renderer stops answering
    started = time.monotonic()
    blank.settle()
    assert not blank.responsive()
    assert time.monotonic() - started < 20
