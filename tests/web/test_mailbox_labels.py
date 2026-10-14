"""Several mailboxes in the web interface and Telegram (Planung 3.1, phase 5)."""
from __future__ import annotations

from types import SimpleNamespace as NS

from shared_web_details import with_mail
from web_scenario import ACCOUNT, mail_id, proposal

from mailhelp.composition import _mailbox_labels
from mailhelp.review.queries import ArchiveQueries, ArchiveQuery
from mailhelp.telegram.presenter import ProposalPresenter

WORK = "b" * 24


def move(store, number, account):
    state = store.load(f"mail-{mail_id(number)}")
    state["imap"]["account_id"] = account
    store.save(f"mail-{mail_id(number)}", state)


def labelled(web):
    labels = {ACCOUNT: (1, "Privat"), WORK: (2, "Arbeit")}
    web.site.views.mailboxes = web.site.archive.queries.mailboxes = labels
    move(web.store, 2, WORK)
    move(web.store, 3, "c" * 24)
    return labels


def test_archive_shows_and_filters_the_mailbox(web):
    queries = ArchiveQueries(web.store)
    queries.mailboxes = labelled(web)
    every = queries.search(ArchiveQuery())[1]
    assert queries.search(ArchiveQuery(postfach=2))[0][0]["id"] == mail_id(2)
    assert queries.search(ArchiveQuery(postfach=2))[1] == 1
    assert queries.search(ArchiveQuery(postfach=1))[1] == every - 2
    assert queries.search(ArchiveQuery(postfach=7))[1] == 0
    page = web.browser.request("GET", "/mails").body.decode()
    assert '<select name="postfach">' in page and '<option value="2">Arbeit</option>' in page
    assert '<span class="badge">Arbeit</span>' in page and '<span class="badge">Entferntes Postfach</span>' in page
    filtered = web.browser.request("GET", "/mails?postfach=2").body.decode()
    assert '<option value="2" selected>Arbeit</option>' in filtered and "1 gespeicherte Mails" in filtered
    assert web.browser.request("GET", "/mails?postfach=100").status == 422


def test_a_single_mailbox_shows_no_mailbox_filter_or_label(web):
    page = web.browser.request("GET", "/mails").body.decode()
    assert 'name="postfach"' not in page
    with_mail(web.store, 1, text="Hallo")
    assert "<dt>Postfach</dt>" not in web.browser.request("GET", f"/mail/{mail_id(1)}").body.decode()
    assert web.site.views.mailbox_label(ACCOUNT) == ""


def test_mail_detail_names_its_mailbox(web):
    labelled(web)
    for number, label in ((2, "Arbeit"), (3, "Entferntes Postfach")):
        with_mail(web.store, number, text="Hallo")
        page = web.browser.request("GET", f"/mail/{mail_id(number)}").body.decode()
        assert f"<dt>Postfach</dt><dd>{label}</dd>" in page


def test_telegram_cards_name_the_mailbox_of_their_mail(web):
    source = NS(account_id=WORK, mailbox=NS(label="Arbeit"))
    move(web.store, 2, WORK)
    label = _mailbox_labels(web.store, [source])
    assert label(NS(source_mail_id=mail_id(2))) == "Arbeit"
    assert label(NS(source_mail_id=mail_id(1))) == "Entferntes Postfach"
    assert label(NS(source_mail_id="f" * 24)) == ""
    presenter = ProposalPresenter("Europe/Berlin", lambda decision: "x")
    item = proposal(1, "karte", title="Rückmeldung geben")
    assert presenter.present(item, "Schule <a@b.test>", "Info").parts[0].startswith("✉️ Schule · Info")
    presenter.mailbox_of = lambda proposal: "Arbeit"
    assert presenter.present(item, "Schule <a@b.test>", "Info").parts[0].startswith("✉️ [Arbeit] Schule · Info")
