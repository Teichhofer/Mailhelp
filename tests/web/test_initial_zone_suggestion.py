"""8.7.12: only an untouched first step offers the browser's time zone.

Regression (Linux browser suite): a zone typed and checked before the deferred ``setup.js`` ran came back
from the server as the field's value, and the script then replaced "Europe/Vienna" by the browser's zone.
"""
from __future__ import annotations

import re

from mailhelp.web.initial_pages import initial_page
from tests.fakes.initial_harness import initial  # noqa: F401  (fixture)


def test_the_untouched_first_step_marks_the_zone_for_the_browser_suggestion(initial):
    html = initial_page(initial.setup.state(), "csrf", 1)
    zone = re.search(r'<input[^>]*name="timezone"[^>]*>', html).group(0)
    assert html.count("data-suggest-zone") == 1 and "data-suggest-zone" in zone


def test_returned_input_is_never_marked_for_replacement(initial):
    html = initial_page(initial.setup.state(), "csrf", 1, values={"timezone": "Europe/Vienna"})
    assert "data-suggest-zone" not in html and 'value="Europe/Vienna"' in html


def test_other_steps_carry_no_suggestion(initial):
    assert "data-suggest-zone" not in initial_page(initial.setup.state(), "csrf", 2)
