"""5.9.7: the number of processed mails, computed from the stored states on every call."""
from datetime import UTC, datetime

from mailhelp.domain.processing import ProcessingSteps
from mailhelp.review.views import ReviewViews, count_processed, german_number
from mailhelp.storage import JsonStore
from mailhelp.web.status_pages import _processed_sentence
from tests.fakes.shared_telegram_dialog import message
from tests.scenarios.web_scenario import save_mail


def steps(completion, **others):
    return ProcessingSteps(completion=completion, **others)


def fill(store):
    # A relevant mail, an irrelevant mail and a duplicate count once each; a mail being
    # analysed again (completion back to pending) does not count until it is completed again.
    save_mail(store, 1, "a@example.test", "Relevant", steps=steps("completed"))
    save_mail(store, 2, "b@example.test", "Irrelevant", steps=steps("completed", summary="skipped"))
    save_mail(store, 3, "c@example.test", "Duplikat", steps=steps("completed", relevance="skipped"))
    save_mail(store, 4, "d@example.test", "Neuanalyse", steps=steps("pending"))
    # Retention cleans the full mail but keeps the state: still processed.
    save_mail(store, 5, "e@example.test", "Bereinigt", steps=steps("completed"), mail=None)


def test_processed_mails_include_irrelevant_and_duplicates_but_not_a_reanalysis(tmp_path):
    with JsonStore(tmp_path) as store:
        fill(store)
        system = ReviewViews(store, "Europe/Berlin").system()
        assert (system.mails_processed, system.mails_total) == (4, 5)
        assert count_processed(store) == 4
    # A restart reads the same states: no counter file, nothing counted twice.
    with JsonStore(tmp_path) as store:
        assert count_processed(store) == 4 and ReviewViews(store, "Europe/Berlin").system().mails_processed == 4


def test_the_sentence_uses_german_thousands_and_the_last_mail():
    from types import SimpleNamespace as NS
    from zoneinfo import ZoneInfo
    zone = ZoneInfo("Europe/Berlin")
    assert german_number(1234567) == "1.234.567" and german_number(12) == "12"
    last = datetime(2026, 11, 12, 6, 45, tzinfo=UTC)
    assert (_processed_sentence(NS(mails_processed=1234, last_processed=last), zone)
            == "Bisher 1.234 Mails verarbeitet, zuletzt am 12.11.2026, 07:45 Uhr.")
    assert _processed_sentence(NS(mails_processed=1, last_processed=None), zone) == "Bisher 1 Mail verarbeitet."


def test_status_page_and_telegram_status_show_the_count(web):
    fill(web.store)
    html = web.browser.request("GET", "/status").body.decode()
    assert "<dt>Verarbeitet (abgeschlossen)</dt><dd>4</dd>" in html
    assert "Bisher 4 Mails verarbeitet, zuletzt am" in html
    # The open work stays first (6.2.9: as the figure "Offene Vorschläge" above the summary).
    assert html.index("Offene Vorschläge") < html.index("Bisher 4 Mails verarbeitet")
    web.telegram.updates = [message(1, "/status")]
    web.run()
    assert web.telegram.sent[-1][1].startswith("📊 Bisher 4 Mails verarbeitet.\n")
    before = len(web.telegram.sent)
    web.telegram.updates = [message(2, "/offen")]
    web.run()
    assert not any(text.startswith("📊") for _, text, _ in web.telegram.sent[before:])
