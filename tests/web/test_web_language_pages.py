"""7.5.4: the open decisions, cards, mail view and actions in the reader's language."""
import re
from dataclasses import replace
from html import unescape

from mailhelp.domain.prepared import PreparedAttachment
from mailhelp.i18n import Locale, use_locale
from mailhelp.review.commands import CommandKind
from mailhelp.web.actions import command_page, confirm_remove_page, reject_reason_block, stale_page
from mailhelp.web.open_toolbar import OpenView, no_match, toolbar
from mailhelp.web.review_pages import mail_section
from mailhelp.web.toolbar import toolbar as list_toolbar
from tests.fakes.shared_web_actions import web as web
from tests.fakes.web_routes import action_id
from tests.scenarios.web_scenario import mail_id

EN = {"accept-language": "en"}


def text(html):
    return unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>", "", html, flags=re.S)))


def english(web, path):
    return web.browser.request("GET", path, **EN).body.decode()


def test_regression_the_published_overview_is_shown_in_the_readers_language(web):
    """Before 7.5.4 the overview published by the main thread kept German cards for English readers."""
    web.site.refresh_overview()
    page = text(english(web, "/"))
    assert "Open decisions" in page and "Oct 21, 2026, 19:00–20:30" in page and "Pending confirmation" in page
    assert "19:00–20:30 Uhr" not in page and "Wartet auf Bestätigung" not in page
    german = text(web.browser.request("GET", "/").body.decode())
    assert "Offene Entscheidungen" in german and "21.10.2026, 19:00–20:30 Uhr" in german


def test_cards_buttons_and_help_of_the_open_decisions_in_english(web):
    web.site.refresh_overview()
    page = text(english(web, "/"))
    for phrase in ("Review proposals, answer questions and make decisions.", "Clarify relevance", "❔ Relevance",
                   "Is this email relevant to you?", "Add to calendar", "Add as task", "Dismiss", "Already done",
                   "What do these decisions mean?", "Creates the entry with the provider.", "Send answer",
                   "Open questions (1)", "When does the event start?", "Description and evidence",
                   "Show full evidence", "Current in Telegram", "Next in Telegram", "Recently done", "Search and sort",
                   "Newest email first", "Group by what is needed", "With attachments", "Swipe right: relevant"):
        assert phrase in page, phrase
    for german in ("Verwerfen", "Schon erledigt", "Was bedeuten", "Beschreibung und Beleg", "Offene Fragen",
                   "Suchen und sortieren", "Zuletzt erledigt", "Antwort senden"):
        assert german not in page, german


def test_detail_and_mail_pages_in_english(web):
    detail = text(english(web, f"/vorschlag/{mail_id(1)}/elternabend"))
    assert "← To the overview" in detail and "Edit fields" in detail
    assert "Source evidence from email / attachment (Email from Klassenleitung 4b)" in detail
    assert "Revision history & differences" in detail and "Technical LLM analysis & metrics" in detail
    mail = text(english(web, f"/mail/{mail_id(1)}"))
    assert " From " in mail and " Subject " in mail and " Date " in mail and "Oct 11, 2026, 10:30" in mail


def test_an_empty_open_list_follows_the_reader(web, monkeypatch):
    web.site.refresh_overview()
    assert web.site.empty_state() is None
    with use_locale(Locale.EN):
        assert web.site.empty_state() is None
        empty = replace(web.site.overview(), open=(), relevance=())
        monkeypatch.setattr(web.site.views, "overview", lambda: empty)
        monkeypatch.setattr(web.site.experience, "inbox_zero", lambda: "<p>zero</p>")
        assert web.site.empty_state() == "<p>zero</p>"


def test_a_stored_result_is_german_and_read_in_each_language(web):
    web.dialog.locale = Locale.EN
    response = web.submit(web.form("/", kind="reject", proposal_id="formular"))
    web.run()
    entry = web.commands.get(action_id(response.headers["Location"]))
    assert entry.result.message == "Vorschlag verworfen."
    web.site.refresh_overview()
    assert "Proposal dismissed." in text(english(web, "/")) and "Dismissed. Why?" in text(english(web, "/"))
    assert "Vorschlag verworfen." in text(web.browser.request("GET", "/").body.decode())
    assert "🌐 Im Web: Vorschlag verworfen." in [sent[1] for sent in web.telegram.sent]


def test_result_stale_and_removal_pages_in_english(web):
    with use_locale(Locale.EN):
        view = web.site.views.proposal(mail_id(1), "elternabend")
        stale = text(stale_page("Vorschlag inzwischen geändert", view))
        removal = text(confirm_remove_page(view, "csrf"))
        reasons = text(reject_reason_block("csrf", mail_id(1), "elternabend", 1, "advertising"))
    assert "No longer current" in stale and "Proposal changed in the meantime" in stale
    assert "Current state: version 1 – Pending confirmation." in stale
    assert "Remove entry again" in removal and "Target: Calendar" in removal and "Really remove entry" in removal
    assert "Dismissed. Why?" in reasons and "(saved: Advertising or newsletter)" in reasons
    assert "Does not concern me" in reasons


def test_the_running_action_page_in_english(web):
    response = web.submit(web.form("/", kind="confirm", proposal_id="elternabend"))
    entry = web.commands.get(action_id(response.headers["Location"]))
    with use_locale(Locale.EN):
        view = web.site.views.proposal(mail_id(1), "elternabend")
        page = text(command_page(entry, "csrf", view))
    assert "Action running" in page and "Creating the entry in the target “Calendar” can take a moment." in page


def test_tool_rows_in_english():
    with use_locale(Locale.EN):
        row = text(toolbar("/offen", OpenView(filter="", q="Elternabend", sort="alt", group=True)))
        empty = text(no_match("/offen"))
        filters = text(list_toolbar("/mails", ["x"], submit="Suchen", more=["y"], active=2, reset="/mails"))
    assert "(“Elternabend”, Oldest email first, grouped)" in row or "(„Elternabend“, Oldest email first, grouped)" in row
    assert "No matching decisions." in empty and "Reset" in empty
    assert "More filters (2 active)" in filters and "Reset" in filters


def test_attachment_states_in_english_and_unknown_ones_as_stored(web):
    mail = web.site.views.mail(mail_id(1))
    attachments = (PreparedAttachment(filename="a.pdf", extraction_status="encrypted"),
                   PreparedAttachment(filename="b.pdf", extraction_status="neu"),
                   PreparedAttachment(filename="c.png", vision="no_text"),
                   PreparedAttachment(filename="d.png", vision="neu_vision"))
    with use_locale(Locale.EN):
        page = text(mail_section(replace(mail, extracted_attachments=attachments, attachments_omitted=2,
                                         text_shortened=True)))
    assert "Encrypted / password protected" in page and " neu " in page
    assert "Image without readable text" in page and "neu_vision" in page
    assert "Attachments (4):" in page and "2 attachment(s) not analysed" in page and "shortened" in page


def test_the_choice_of_a_calendar_event_and_the_conflict_hint_in_english(web):
    view = web.site.views.proposal(mail_id(1), "elternabend")
    from mailhelp.web.actions import proposal_actions
    with use_locale(Locale.EN):
        html = text(proposal_actions("csrf")(replace(
            view, actions=frozenset({CommandKind.CHOOSE_EVENT, CommandKind.REJECT}), calendar_candidates=("A",))))
    assert "I mean this event: A" in html and "Choose the event you mean first." not in html


def test_web_commands_produce_german_results_while_telegram_speaks_english(web, monkeypatch):
    """Web commands run in the dialog thread; their results never take its language (7.5.4)."""
    from mailhelp.i18n import tr
    from mailhelp.review.results import ReviewResult, ResultStatus
    web.dialog.locale = Locale.EN
    monkeypatch.setattr(web.dialog.review, "execute",
                        lambda command: ReviewResult(status=ResultStatus.DONE, message=tr("Bereits entfernt.")))
    entry_id = action_id(web.submit(web.form("/", kind="reject", proposal_id="formular")).headers["Location"])
    web.run()
    assert web.commands.get(entry_id).result.message == "Bereits entfernt."
