"""Details with the complete mail, and the return to the overview after an action."""
from __future__ import annotations

import threading

from shared_review import command
from shared_web_actions import MAIL1, Web, web  # noqa: F401  (fixture)
from shared_web_details import with_mail as with_mail
from web_scenario import mail_id, populate

from mailhelp.models import MailState
from mailhelp.review.commands import CommandKind
from mailhelp.review.views import ReviewViews
from mailhelp.storage import JsonStore


def test_every_card_has_details_with_the_complete_mail(web):
    with_mail(web.store, 1)
    overview = web.browser.request("GET", "/").body.decode()
    assert f'href="/vorschlag/{MAIL1}/elternabend">Details</a>' in overview
    assert f'href="/mail/{mail_id(7)}">Details</a>' in overview
    page = web.browser.request("GET", f"/vorschlag/{MAIL1}/elternabend").body.decode()
    assert '<h2 id="mail-titel">Mail</h2>' in page and ">Details</a>" not in page
    assert "Klassenleitung 4b &lt;klasse4b@schule.test&gt;" in page
    assert "06.10.2026, 12:41 Uhr" in page
    assert "https://evil.test/x &lt;b&gt;klicken&lt;/b&gt;" in page and 'href="https://evil' not in page
    assert "2 Anhang/Anhänge nicht ausgewertet" in page and "gekürzt" in page


def test_a_removed_mail_text_is_explained(web):
    page = web.browser.request("GET", f"/vorschlag/{mail_id(2)}/zahnarzt").body.decode()
    assert "nicht mehr gespeichert" in page and "mail-text" not in page


def test_mail_page_for_a_relevance_question(web):
    with_mail(web.store, 7, text="Vereinsnews")
    page = web.browser.request("GET", f"/mail/{mail_id(7)}").body.decode()
    assert "Vereinsnews" in page and 'value="relevance"' in page and ">Details</a>" not in page
    answered = web.browser.request("GET", f"/mail/{mail_id(5)}").body.decode()
    assert 'value="relevance"' not in answered and "Kinderturnen" in answered
    assert web.browser.request("GET", "/mail/" + "e" * 24).status == 404


def test_mail_view_without_headers_or_with_odd_content(tmp_path):
    with JsonStore(tmp_path) as store:
        populate(store)
        state = store.load_model(f"mail-{mail_id(1)}", MailState)
        for content, received in (
                ({"headers": {"from": "A <a@x.test>", "subject": "S"}, "imap_received_at": "kaputt"}, None),
                ({"headers": "kaputt", "date_header_parsed": 5, "metadata": [], "text": 7}, None)):
            store.save(f"mail-{mail_id(1)}", state.model_copy(update={
                "mail": content, "display_headers": None}).model_dump(mode="json"))
            view = ReviewViews(store, "UTC").mail(mail_id(1))
            assert view.received is received and view.text is None
            assert (view.attachments_omitted, view.text_shortened) == (0, False)
        assert view.sender == "—"


def test_result_notice_only_for_the_own_finished_action(web):
    location = web.submit(web.form("/", kind="reject", proposal_id="formular")).headers["Location"]
    entry_id = location.rsplit("/", 1)[1]
    unfinished = web.browser.request("GET", f"/?ergebnis={entry_id}").body.decode()
    assert "notice-ok" not in unfinished
    web.run()
    assert "Vorschlag verworfen." in web.browser.request("GET", f"/?ergebnis={entry_id}").body.decode()
    for query in ("ergebnis=kaputt", "ergebnis=" + "0" * 32, "x=1"):
        assert "notice-ok" not in web.browser.request("GET", f"/?{query}").body.decode()
    # The result of another session's action is never shown.
    other, _ = web.commands.submit(command(CommandKind.REJECT, mail_id=MAIL1, proposal_id="elternabend",
                                           actor="web:fremd", key="key-fremd-01"))
    web.commands.finish(other.id, web.commands.get(entry_id).result)
    assert "notice-ok" not in web.browser.request("GET", f"/?ergebnis={other.id}").body.decode()


def test_the_progress_page_waits_briefly_for_a_quick_result(web, monkeypatch):
    monkeypatch.setattr("mailhelp.web.site.SETTLE_SECONDS", 3)
    location = web.submit(web.form("/", kind="reject", proposal_id="formular")).headers["Location"]
    worker = threading.Timer(0.2, web.run)
    worker.start()
    response = web.browser.request("GET", location)
    worker.join()
    assert response.status == 303 and response.headers["Location"].startswith("/?ergebnis=")


def test_detail_of_a_proposal_without_mail_record(web):
    from web_scenario import proposal
    item = proposal(40, "solo", title="Ohne Mail")
    web.store.save(f"proposal-{item.source_mail_id}-solo", item.model_dump(mode="json"))
    page = web.browser.request("GET", f"/vorschlag/{item.source_mail_id}/solo").body.decode()
    assert "Ohne Mail" in page and 'id="mail-titel"' not in page


def test_old_proposal_detail_is_not_limited_to_recent_window(web):
    """Regression: a ninth completed proposal remains addressable by identity."""
    from web_scenario import proposal, save_mail
    for number in range(10, 22):
        item = proposal(number, "done", status="rejected")
        save_mail(web.store, number, "Synthetic", f"Archived {number}", [item])
    response = web.browser.request("GET", f"/vorschlag/{mail_id(10)}/done")
    assert response.status == 200
    assert "Archived 10" in response.body.decode()
