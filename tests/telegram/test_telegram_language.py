"""7.5.3: Telegram cards, buttons and prompts in the configured language."""
from mailhelp.i18n import Locale, current, use_locale
from mailhelp.telegram.formatting import clarification_prompt, format_proposal, revision_summary
from mailhelp.telegram.presenter import ProposalPresenter
from tests.fakes.factories import build_proposal


def _texts(markup):
    return [button["text"] for row in markup["inline_keyboard"] for button in row]


def test_a_card_reads_in_english_and_stays_german_by_default():
    proposal = build_proposal(kind="event", start="2027-01-07T11:30:00+01:00", end="2027-01-08T12:30:00+01:00",
                              responsibility="unclear", certainty="uncertain", classification="non_binding",
                              status="needs_clarification", open_questions=["Wann endet der Termin?"], version=2)
    german = format_proposal(proposal, "Europe/Berlin")
    with use_locale(Locale.EN):
        english = format_proposal(proposal, "Europe/Berlin", test_mode=True)
    assert german.startswith("📅 Termin (Version 2)") and "Zuständig: Noch unklar" in german and "Beleg: „" in german
    assert english.startswith("📅 Event (Version 2)") and "Responsible: Not yet clear" in english
    assert "Certainty: Uncertain" in english and "Classification: Non-binding note" in english
    assert "❓ Open:" in english and "- When does the event end?" in english and "Evidence: “" in english
    assert "⚠️ Cannot be created automatically – please check manually." in english
    writable = build_proposal(kind="event", start="2027-01-07T11:30:00+01:00", end="2027-01-07T12:30:00+01:00")
    with use_locale(Locale.EN):
        assert "🧪 Test mode: the entry is only simulated" in format_proposal(writable, "Europe/Berlin", test_mode=True)
    assert "🕒 Jan 7, 2027, 11:30 – Jan 8, 2027, 12:30" in english


def test_task_lines_prompts_and_summaries_in_english():
    task = build_proposal(kind="task", due="2027-01-07", mail_link="message://%3Cx@example.org%3E")
    with use_locale(Locale.EN):
        card = format_proposal(task, "Europe/Berlin")
        assert card.startswith("✅ Task") and "🕒 Due: " in card and "📧 Original email (Apple Mail):" in card
        prompt = clarification_prompt(task.model_copy(update={"open_questions": []}), "Europe/Berlin")
        assert "✏️ What should be changed in “" in prompt and "/abbrechen ends the editing" in prompt
        asked = clarification_prompt(task.model_copy(update={"open_questions": ["Ist die extrahierte Information "
                                                                                 "sicher belegt?"],
                                                             "status": "needs_clarification"}), "Europe/Berlin")
        assert "Are these details correct?" in asked and "due Jan 7, 2027" in asked and "“yes” or “no”" in asked
        assert revision_summary(task, task, "Europe/Berlin") == "Applied – no visible change."
        changed = task.model_copy(update={"title": "Neu", "version": 2})
        assert revision_summary(task, changed, "Europe/Berlin").startswith("Applied:")


def test_buttons_in_english():
    presenter = ProposalPresenter("Europe/Berlin", lambda decision: "token")
    open_event = build_proposal(kind="event", start="2027-01-07T11:30:00+01:00", end="2027-01-07T12:30:00+01:00")
    task = build_proposal(kind="task")
    with use_locale(Locale.EN):
        assert "Add to calendar" in _texts(presenter.present(open_event).reply_markup)
        texts = _texts(presenter.present(task).reply_markup)
    assert "Add as task" in texts and "Edit" in texts and "Dismiss" in texts and "✓ Already done" in texts
    assert "Im Kalender anlegen" in _texts(presenter.present(open_event).reply_markup)


def test_the_dialog_sends_in_the_configured_language(monkeypatch):
    from mailhelp.telegram.dialog import TelegramDialogController
    seen = []
    controller = TelegramDialogController.__new__(TelegramDialogController)
    controller.locale = Locale.EN
    monkeypatch.setattr(TelegramDialogController, "_poll_once", lambda self, timeout: seen.append(current()))
    controller.poll_once()
    assert seen == [Locale.EN] and current() == Locale.DE
