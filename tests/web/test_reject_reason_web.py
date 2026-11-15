"""Web interface tests for rejection reasons (Planung 6.5, D2, 3.2)."""
from __future__ import annotations

from mailhelp.domain.proposal import ProposalStatus
from tests.scenarios.web_scenario import mail_id

MAIL1 = mail_id(1)
MAIL6 = mail_id(6)


def test_rejecting_proposal_shows_reject_reasons_on_result_card(web):
    # Reject the open elternabend proposal
    form = web.form("/", kind="reject", proposal_id="elternabend")
    response = web.submit(form)
    assert response.status == 303
    web.run()

    html = web.browser.request("GET", "/").body.decode()
    assert "Vorschlag verworfen." in html
    assert "Verworfen. Warum?" in html
    assert "Betrifft mich nicht" in html
    assert "Nur zur Information" in html
    assert "Werbung oder Rundschreiben" in html
    assert "Falsch erkannt (Datum, Inhalt)" in html
    assert "Anderer Grund" in html


def test_selecting_and_replacing_reason_in_web(web):
    # Reject the open elternabend proposal
    form = web.form("/", kind="reject", proposal_id="elternabend")
    web.submit(form)
    web.run()

    # Choose 'not_for_me'
    reason_form = web.form("/", kind="reject_reason", proposal_id="elternabend", reason="not_for_me")
    response = web.submit(reason_form)
    assert response.status == 303
    web.run()

    # Proposal on disk is updated
    current = web.dialog.repository.load_current(MAIL1, "elternabend")
    assert current is not None
    assert current.reject_reason == "not_for_me"

    # Feedback on detached card
    html = web.browser.request("GET", "/").body.decode()
    assert "Grund gespeichert: Betrifft mich nicht." in html
    assert 'class="button small primary" type="submit" aria-pressed="true">Betrifft mich nicht</button>' in html

    # Replace with 'advertising'
    replace_form = web.form("/", kind="reject_reason", proposal_id="elternabend", reason="advertising")
    response2 = web.submit(replace_form)
    assert response2.status == 303
    web.run()

    current2 = web.dialog.repository.load_current(MAIL1, "elternabend")
    assert current2 is not None
    assert current2.reject_reason == "advertising"

    html2 = web.browser.request("GET", "/").body.decode()
    assert "Grund gespeichert: Werbung oder Rundschreiben." in html2
    assert 'class="button small primary" type="submit" aria-pressed="true">Werbung oder Rundschreiben</button>' in html2


def test_reject_reason_on_detail_page(web):
    # Mail 6 has rejected proposal 'werbung'
    detail_url = f"/vorschlag/{MAIL6}/werbung"
    html = web.browser.request("GET", detail_url).body.decode()
    assert "Verworfen. Warum?" in html

    reason_form = web.form(detail_url, kind="reject_reason", proposal_id="werbung", reason="info_only")
    response = web.submit(reason_form)
    assert response.status == 303
    web.run()

    current = web.dialog.repository.load_current(MAIL6, "werbung")
    assert current is not None
    assert current.reject_reason == "info_only"


def test_reject_reason_stale_version_and_unknown_reason(web):
    detail_url = f"/vorschlag/{MAIL6}/werbung"
    form = web.form(detail_url, kind="reject_reason", proposal_id="werbung", reason="other")

    # Stale version
    stale_form = dict(form, version="99")
    response = web.submit(stale_form)
    assert response.status == 409
    assert "Dieser Vorschlag wurde inzwischen geändert oder ist nicht verworfen." in response.body.decode()

    # Unknown reason
    bad_form = dict(form, reason="bogus")
    bad_response = web.submit(bad_form)
    assert bad_response.status == 422


def test_reject_reason_csrf_and_session_protection(web):
    detail_url = f"/vorschlag/{MAIL6}/werbung"
    form = web.form(detail_url, kind="reject_reason", proposal_id="werbung", reason="other")

    # Bad CSRF
    bad_csrf_form = dict(form, csrf="invalid")
    response = web.submit(bad_csrf_form)
    assert response.status == 403

    # Revoked session
    web.auth.revoke_all()
    response_revoked = web.submit(form)
    assert response_revoked.status == 403


def test_reject_shows_sender_hint_on_detached_card(web):
    # MAIL1 sender has proposal 'elternabend'.
    # Add 4 additional rejected proposals for this sender so total is 5 rejected
    from datetime import UTC, datetime

    from mailhelp import state_names
    from mailhelp.domain.proposal import Proposal, ProposalKind
    mail1_view = web.site.views.mail(MAIL1)
    sender = mail1_view.sender

    for i in range(4):
        pid = f"extra_{i}"
        prop = Proposal(
            id=pid,
            version=1,
            source_mail_id=MAIL1,
            kind=ProposalKind.TASK,
            responsibility="user",
            certainty="certain",
            classification="new",
            title=f"Extra {i}",
            evidence="Quelle",
            target="inbox",
            status=ProposalStatus.REJECTED,
        )
        web.store.save(state_names.proposal(MAIL1, pid), prop.model_dump(mode="json"))

    # Now reject the open 'elternabend' proposal
    form = web.form("/", kind="reject", proposal_id="elternabend")
    response = web.submit(form)
    assert response.status == 303
    web.run()

    html = web.browser.request("GET", "/").body.decode()
    assert "data-sender-hint" in html
    assert "Künftig aussortieren?" in html
    assert f"/lernen/absender-hinweis?sender=" in html


def test_command_cards_detached_without_sender_hint_lookup(web):
    from mailhelp.web.command_cards import CommandCards
    form = web.form("/", kind="reject", proposal_id="elternabend")
    web.submit(form)
    web.run()

    # Pass sender_hint_lookup=None explicitly
    cards = CommandCards(web.site.commands._entries(), "test_csrf", "/", sender_hint_lookup=None)
    html = cards.detached(set())
    assert "Verworfen. Warum?" in html
    assert "data-sender-hint" not in html


def test_review_site_sender_hint_edge_cases(web):
    from mailhelp.config.configuration import ConfigurationService
    from tests.fakes.shared_application import settings

    # 1. Non-existent mail -> None
    assert web.site.review._sender_hint("0" * 24) is None

    # 2. With configuration service and learning settings
    tmp = web.store.directory.parent
    cfg = ConfigurationService(tmp, web.store, settings(tmp),
                               lambda actor: True, lambda active: None, senders=web.store)
    web.site.archive.configuration = cfg
    web.site.review._sender_hint(MAIL1)


