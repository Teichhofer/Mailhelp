"""6.2.3: German names instead of internal values, counts that agree, one form of address (E1)."""
import re
from pathlib import Path

import pytest

from mailhelp.domain.proposal import ProposalStatus
from mailhelp.review.commands import CommandKind
from mailhelp.web.archive_pages import event_text
from mailhelp.web.labels import EVENTS, SOURCES, STATUSES, count_text, label

WEB = Path(__file__).resolve().parents[2] / "src" / "mailhelp" / "web"
# Mid-sentence "Sie" is always the formal address; "Ihr/Ihre/Ihnen" never occurs otherwise in page texts.
FORMAL = re.compile(r"[a-zäöüß,] Sie\b|\bIhre[nmrs]?\b|\bIhnen\b")


def test_every_status_and_command_has_a_german_name():
    assert all(STATUSES.get(str(status)) for status in ProposalStatus)
    assert all(EVENTS.get(str(kind)) for kind in CommandKind)
    assert set(SOURCES) >= {"system", "web", "telegram", "unknown"}


def test_an_unknown_value_is_marked_and_never_shown_raw():
    assert label(STATUSES, "neu_erfunden") == "unbekannt (neu_erfunden)"
    assert label(SOURCES, "web") == "Weboberfläche"


@pytest.mark.parametrize(("number", "text"), [(0, "0 Vorschläge"), (1, "1 Vorschlag"), (2, "2 Vorschläge"),
                                              (1234, "1.234 Vorschläge")])
def test_the_noun_agrees_with_the_number(number, text):
    assert count_text(number, "Vorschlag", "Vorschläge") == text


def test_an_event_names_its_kind_only_when_it_adds_something():
    row = {"at": "2026-10-02T10:00:00+00:00", "kind": "edit", "status": "pending_confirmation", "source": "telegram"}
    assert event_text(row, "Europe/Berlin") == ("02.10.2026, 12:00 Uhr · Felder bearbeitet · Wartet auf Bestätigung"
                                                " · Telegram")
    rejected = {**row, "kind": "reject", "status": "rejected", "source": "web"}
    assert event_text(rejected, "Europe/Berlin") == "02.10.2026, 12:00 Uhr · Verworfen · Weboberfläche"
    assert "Status geändert" not in event_text({**row, "kind": "state"}, "UTC")


def test_page_texts_address_the_user_informally():
    found = [f"{path.name}:{number}: {line.strip()[:80]}"
             for path in sorted([*WEB.glob("*.py"), *(WEB / "static").glob("*.js"), *(WEB / "static").glob("*.html")])
             for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if FORMAL.search(line)]
    assert found == []


def test_the_address_check_finds_the_formal_forms():
    assert FORMAL.search("Prüfen Sie erst") and FORMAL.search("deine und Ihre Regeln") and FORMAL.search("mit Ihnen")
    assert not FORMAL.search("Sie werden nach einem Neustart verwendet.")  # "sie" (they) at the start of a sentence
