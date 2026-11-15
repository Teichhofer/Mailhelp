"""7.0: the refactoring changes no output. Core pages and Telegram texts from synthetic data stay byte-equal.

The reference files under ``tests/golden/output`` were written before the first refactoring step. Only
values that differ on every run (session and form tokens, fingerprints, expiry times) are replaced by
placeholders. ``MAILHELP_UPDATE_GOLDEN=1`` rewrites the files; within 7.0 that is not allowed.
"""
from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
import time_machine

from mailhelp import __version__
from mailhelp.domain.proposal import Proposal
from mailhelp.persistence.storage import JsonStore
from tests.fakes.shared_web_actions import MAIL1, Web
from tests.scenarios.web_scenario import populate

OUTPUT = Path(__file__).parent / "output"
FIXED = datetime(2026, 11, 15, 8, 0, tzinfo=UTC)
PAGES = {
    "uebersicht": "/", "offen-termine": "/offen?filter=events", "mails": "/mails", "mail": f"/mail/{MAIL1}",
    "vorschlag": f"/vorschlag/{MAIL1}/elternabend", "verlauf": "/verlauf", "lernen": "/lernen",
    "auswertung": "/auswertung", "status": "/status", "einstellungen": "/einstellungen", "abgleich": "/abgleich",
}
VOLATILE = [
    (re.compile(r'(type="hidden" name="[a-z_]+" value=")[0-9a-f]{32,}'), r"\1<token>"),
    (re.compile(r'(data-fingerprint=")[^"]+'), r"\1<fingerprint>"),
    (re.compile(r'(data-scope=")[0-9a-f]+'), r"\1<scope>"),
    (re.compile(r'(data-(?:session-)?expires=")[0-9.]+'), r"\1<expires>"),
    (re.compile(r"(decision:)[0-9a-f]{16,}"), r"\1<token>"),
]


def normalize(text: str) -> str:
    for pattern, replacement in VOLATILE:
        text = pattern.sub(replacement, text)
    # Every patch raises the version shown on the status page.
    return text.replace(f"<dd>{__version__}</dd>", "<dd><version></dd>")


def compare(name: str, actual: str) -> None:
    path = OUTPUT / name
    if os.environ.get("MAILHELP_UPDATE_GOLDEN") == "1":
        path.parent.mkdir(exist_ok=True)
        path.write_text(actual, encoding="utf-8", newline="\n")
    assert path.read_text(encoding="utf-8") == actual, f"{name} differs from the frozen output"


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    monkeypatch.setattr("mailhelp.web.site.SETTLE_SECONDS", 0)
    with time_machine.travel(FIXED, tick=False), JsonStore(tmp_path) as store:
        populate(store)
        yield Web(store)


@pytest.mark.parametrize("name", PAGES)
def test_core_pages_are_unchanged(frozen, name):
    response = frozen.browser.request("GET", PAGES[name])
    assert response.status == 200
    compare(f"{name}.html", normalize(response.body.decode("utf-8")))


def test_telegram_messages_are_unchanged(frozen):
    messages = {}
    for name in sorted(frozen.store.names("proposal-")):
        proposal = frozen.store.peek_model(name, Proposal)
        shown = frozen.dialog.presenter.present(proposal, "Synthetischer Absender", "Synthetischer Betreff")
        messages[name] = {"parts": list(shown.parts), "markup": shown.reply_markup}
    assert len(messages) > 3
    compare("telegram.json", normalize(json.dumps(messages, ensure_ascii=False, indent=2, sort_keys=True) + "\n"))


# 7.0.7: the proposal evaluation page with every sort order, captured before its refactoring.
EVALUATION = {
    "vorschlaege-standard": "", "vorschlaege-thema-name": "?days=0&sort_topic=name",
    "vorschlaege-thema-quote": "?days=30&sort_topic=quote", "vorschlaege-absender-name": "?sort_sender=name",
    "vorschlaege-absender-quote": "?sort_sender=quote", "vorschlaege-absender-entschieden": "?sort_sender=decided",
}


@pytest.mark.parametrize("name", EVALUATION)
def test_proposal_evaluation_page_is_unchanged(frozen, name):
    response = frozen.browser.request("GET", "/lernen/vorschlaege" + EVALUATION[name])
    assert response.status == 200
    compare(f"{name}.html", normalize(response.body.decode("utf-8")))


def test_proposal_evaluation_hints_and_dismissed_senders_are_unchanged(frozen):
    from mailhelp.review.proposal_evaluation import SenderHint, evaluate_proposals
    from mailhelp.web.proposal_evaluation_pages import proposal_evaluation_page

    hint = SenderHint("verein@example.test", 6, 1, 5, 1 / 6, "irrelevant", "filter",
                      "Von verein@example.test hast du 5 von 6 Vorschlägen verworfen.")
    report = evaluate_proposals(frozen.store, days=0)
    page = proposal_evaluation_page(report, {}, hints=[hint], dismissed=["alt@example.test"], csrf="c" * 64)
    compare("vorschlaege-hinweise.html", normalize(page))


# 7.0.7: every tab of the mailbox settings page, captured before its refactoring.
@pytest.mark.parametrize("tab", ["targets", "filters", "topics", "replies", "notifications"])
def test_mailbox_settings_page_is_unchanged(profiled, tab):
    response = profiled.web.browser.request("GET", f"/einstellungen/postfaecher/1?tab={tab}")
    assert response.status == 200
    compare(f"postfach-{tab}.html", normalize(response.body.decode("utf-8")))
