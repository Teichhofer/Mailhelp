"""5.5.4: a short answer for the small help window, from the same model call or derived."""
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from mailhelp.config import HelpChatSettings
from mailhelp.helpdocs import SHORT_ANSWER, HelpAnswer, concise, derive_short_answer, load
from mailhelp.helpdocs.chat import ChatState, HelpChat, Turn
from mailhelp.storage import JsonStore


@pytest.mark.parametrize(("text", "expected"), [
    ("Das Intervall steuert den Abruf. Weitere Details folgen hier.", "Das Intervall steuert den Abruf."),
    # List numbers and dates are no sentence end.
    ("1. Einstellungen öffnen und den Wert prüfen. 2. Speichern.", "1. Einstellungen öffnen und den Wert prüfen."),
    ("Ab dem 3. Mai gilt das neue Intervall! Danach nichts.", "Ab dem 3. Mai gilt das neue Intervall!"),
    # A very short first sentence is joined with the next one.
    ("Ja. Das geht über die Einstellungen für den Abruf. Mehr.", "Ja. Das geht über die Einstellungen für den Abruf."),
    ("Kein Satzzeichen   am\nEnde", "Kein Satzzeichen am Ende"),
    ("Wirklich?\n\nJa, über den Bereich Mailabruf und Betrieb.", "Wirklich? Ja, über den Bereich Mailabruf und Betrieb."),
])
def test_the_first_sentence_is_derived(text, expected):
    assert derive_short_answer(text) == expected


def test_a_long_first_sentence_is_cut_at_a_word():
    sentence = "Das Abrufintervall " + "bestimmt sehr genau, " * 30 + "wie oft Mailhelp abruft."
    short = derive_short_answer(sentence)
    assert len(short) <= SHORT_ANSWER and short.endswith("…")
    assert not short[:-1].endswith((" ", ","))
    assert sentence.startswith(short[:-1])


def test_the_window_prefers_a_usable_model_short_answer():
    full = "Das Intervall steuert den Abruf. 1. Öffnen. 2. Speichern."
    assert concise(full, "  Es  steuert den Abruf. ") == "Es steuert den Abruf."
    assert concise(full, "") == "Das Intervall steuert den Abruf."
    # Too long for the window: shortened like any other text, never shown in full.
    long = "Die Kurzfassung ist leider viel zu lang geraten. " + "x" * SHORT_ANSWER
    assert concise(full, long) == "Die Kurzfassung ist leider viel zu lang geraten."


def test_the_model_contract_bounds_the_short_answer():
    assert HelpAnswer(answer="A", short_answer="B").short_answer == "B"
    assert HelpAnswer(answer="A").short_answer == ""
    with pytest.raises(ValidationError):
        HelpAnswer(answer="A", short_answer="x" * 1001)
    with pytest.raises(ValidationError):
        HelpAnswer.model_validate({"answer": "A", "short_answer": 5})


def test_a_turn_stored_before_5_5_4_still_loads():
    turn = Turn.model_validate({"question": "F?", "answer": "A.", "revision": "r"})
    assert turn.short_answer == ""
    state = ChatState.model_validate({"turns": [{"question": "F?", "answer": "A.", "revision": "r"}],
                                      "updated_at": "2026-11-11T08:00:00+00:00"})
    assert state.turns[0].short_answer == ""


def test_the_stored_short_answer_is_redacted(tmp_path):
    class Analyzer:
        prompts = SimpleNamespace(prompts={"settings_help": object()})

        def settings_help(self, question, sources, history, settings, *, before_call=lambda: None):
            before_call()
            return "call", HelpAnswer(answer="Lang mit geheim123.", short_answer="Kurz mit geheim123.",
                                      source_ids=[sources[0].id])

    with JsonStore(tmp_path) as store:
        chat = HelpChat(store, HelpChatSettings, load, Analyzer, lambda session: True,
                        redact=lambda text: text.replace("geheim123", "[entfernt]"))
        chat.submit("s" * 16, "Was bewirkt das Abrufintervall?", "a" * 32, 1, None)
        chat.run_once()
        turn = chat.state("s" * 16).turns[0]
    assert turn.short_answer == "Kurz mit [entfernt]." and turn.answer == "Lang mit [entfernt]."


# 5.5.7 regression: the real model looped on version numbers of section titles until its limit.
LOOP = "### Weiteres Postfach hinzufügen (Weboberfläche 3.5+ / 5.3+ / 4.9+ / " + "3.0+ / 5.3+ / " * 40


def test_a_looping_answer_is_recognised_and_normal_answers_are_not():
    from mailhelp.helpdocs import repetitive
    assert repetitive(LOOP)
    assert repetitive("Kurz " + "ab " * 7)
    for normal in ("1. Öffnen. 2. Prüfen. 3. Speichern.", "- a\n- b\n- c\n- d\n- e\n- f\n- g",
                   "Werte: 5, 10, 30, 60, 300 oder 86400 Sekunden.", "Ja. Ja. Ja. Gut.", ""):
        assert not repetitive(normal)


def test_the_validator_rejects_a_looping_answer_or_short_answer():
    from mailhelp.helpdocs import answer_validator
    validate = answer_validator(["a/b"], [])
    assert validate({"answer": "So geht es.", "source_ids": ["a/b"]}).answer == "So geht es."
    for value in ({"answer": LOOP}, {"answer": "So geht es.", "short_answer": "x / y / " * 10}):
        with pytest.raises(ValueError, match="wiederholt sich"):
            validate(value)


def test_an_answer_must_name_its_sections_unless_it_asks_back():
    # 5.5.7 regression: the real model returned answers without "source_ids" and "short_answer".
    from mailhelp.helpdocs import answer_validator
    validate = answer_validator(["a/b"], [])
    with pytest.raises(ValueError, match="keine verwendeten Abschnitte"):
        validate({"answer": "Richtig, aber ohne Quellen."})
    assert validate({"answer": "Welche Einstellung meinst du?", "needs_clarification": True}).source_ids == []
