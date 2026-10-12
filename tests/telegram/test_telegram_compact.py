"""Compact Telegram communication: short cards, one question at a time, no noise."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from mailhelp.storage import JsonStore
from mailhelp.telegram.formatting import format_proposal
from mailhelp.telegram.temporal import relative_end_answer
from test_telegram_dialog import callback, controller, message, proposal

MAIL = "a" * 24
START_QUESTION = "Wann beginnt der Termin?"
END_QUESTION = "Wann endet der Termin?"


def edit(version):
    return f"proposal:{MAIL}:p1:{version}:edit"


def texts(transport):
    return [text for _, text, _ in transport.sent]


def test_open_questions_are_asked_one_after_another_without_extra_presses(tmp_path):
    """Regression: every answer resent the full card and required another
    "Klären" press for the next question, plus a separate "edit mode started"."""
    item = proposal(kind="event", open_questions=[START_QUESTION, END_QUESTION])
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        c.send_proposal(item)
        t.updates = [callback(1, edit(1))]
        c.poll_once()
        # The question is the only reply to the press.
        assert texts(t)[-1].startswith("❓ Wann beginnt der Termin?")
        assert not any("Änderungsmodus gestartet" in text for text in texts(t))

        sent = len(t.sent)
        t.updates = [message(2, "21.10.2026 12:30")]
        c.poll_once()
        card, question = t.sent[sent:]
        assert card[1].startswith("✉️ — · —\nÜbernommen:\n🕒 21.10.2026, 12:30 Uhr")
        assert question[1].startswith("❓ Wann endet der Termin?\n„Aufgabe“ · 21.10.2026, 12:30 Uhr")
        assert store.load("telegram-dialog")["version"] == 2

        # A duration is resolved against the known start without an LLM call.
        sent = len(t.sent)
        t.updates = [message(3, "nach 2h")]
        c.poll_once()
        assert len(t.sent) == sent + 1
        final = t.sent[-1]
        assert "🕒 21.10.2026, 12:30–14:30 Uhr" in final[1]
        assert [button["text"] for button in final[2]["inline_keyboard"][0]] == [
            "Im Kalender anlegen", "Ändern", "Verwerfen"]
        current = store.load(f"proposal-{MAIL}-p1")
        assert current["version"] == 3 and current["open_questions"] == []
        assert current["end"] == "2026-10-21T14:30:00Z"


def test_next_question_waits_while_the_version_is_not_shown(tmp_path):
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        pending = proposal(kind="event", open_questions=[END_QUESTION],
                           start="2026-10-21T12:30:00+00:00")
        revisions = c.revisions
        for persistence in (SimpleNamespace(), SimpleNamespace(delivered=lambda item: False)):
            revisions.persistence = persistence
            revisions._continue_clarification(pending)
        revisions.persistence = SimpleNamespace(delivered=lambda item: True)
        revisions._continue_clarification(proposal())  # nothing open: nothing to ask
        assert t.sent == [] and store.load("telegram-dialog") is None


def test_startup_overview_counts_held_back_proposals(tmp_path):
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        for name in ("p1", "p2", "p3"):
            c.send_proposal(proposal(id=name, title=f"Aufgabe {name}"))
        t.sent.clear()
        c.show_open_decisions()
        overview = t.sent[0][1]
        assert "2 weitere Vorschläge folgen nacheinander." in overview
        assert "Noch nicht gesendet" not in overview and "Zurückgehaltene" not in overview
        t.sent.clear()
        t.updates = [message(1, "/status")]
        c.poll_once()
        assert t.sent[0][1].count("Noch nicht gesendet") == 2


def test_overlong_cards_are_split_with_the_mail_line_on_every_part(tmp_path):
    item = proposal(open_questions=["Frage " + "x" * 1500 for _ in range(3)])
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        c.send_proposal(item)
        parts = texts(t)
        assert len(parts) == 2 and parts[0].startswith("✉️ — · — · Teil 1/2\n")
        assert t.sent[-1][2] is not None and t.sent[0][2] is None
        # The redisplay and the cancelled edit split the same way.
        t.updates = [message(1, "/offen")]
        for command, update_id in (("/offen", 1), ("/abbrechen", 3)):
            if command == "/abbrechen":
                t.updates = [callback(2, edit(1))]
                c.poll_once()
            t.sent.clear()
            t.updates = [message(update_id, command)]
            c.poll_once()
            assert any(text.startswith("✉️ — · — · Teil 1/2") for text in texts(t))
            assert t.sent[-1][2] is not None


def test_event_without_any_time_shows_no_time_line():
    item = proposal(kind="event", open_questions=[START_QUESTION, END_QUESTION])
    assert "🕒" not in format_proposal(item, "Europe/Berlin")


@pytest.mark.parametrize("answer,expected", [
    ("nach 3h", "21.10.2026 15:30"),
    ("Nach 2 Stunden", "21.10.2026 14:30"),
    ("+90 min", "21.10.2026 14:00"),
    ("1,5h nach Beginn", "21.10.2026 14:00"),
    ("45 Minuten später", "21.10.2026 13:15"),
    ("12 std", "22.10.2026 00:30"),
    ("17 Uhr", None),
    ("nach 0h", None),
    ("200 h", None),
])
def test_relative_end_answers_use_the_known_start(answer, expected):
    item = proposal(kind="event", start="2026-10-21T12:30:00+02:00", open_questions=[END_QUESTION])
    assert relative_end_answer(item, END_QUESTION, answer, "Europe/Berlin") == expected


def test_relative_end_needs_an_event_end_question_and_a_known_start():
    known = proposal(kind="event", open_questions=[END_QUESTION],
                     known_temporal_facts={"start": "2026-10-21T12:30:00+02:00"})
    assert relative_end_answer(known, END_QUESTION, "nach 2h", "Europe/Berlin") == "21.10.2026 14:30"
    assert relative_end_answer(known, START_QUESTION, "nach 2h", "Europe/Berlin") is None
    assert relative_end_answer(proposal(), END_QUESTION, "nach 2h", "Europe/Berlin") is None
    unknown = proposal(kind="event", open_questions=[START_QUESTION, END_QUESTION])
    assert relative_end_answer(unknown, END_QUESTION, "nach 2h", "Europe/Berlin") is None
    # "bestehende" is not the end question.
    assert relative_end_answer(known, "Welcher bestehende Eintrag?", "nach 2h", "Europe/Berlin") is None
