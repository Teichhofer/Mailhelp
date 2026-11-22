"""8.3: Regression tests for all German-on-English and localization bugs found on 8.2.1."""
from __future__ import annotations

import re
from html import unescape
from pathlib import Path

from mailhelp.domain.mail import MailState, Relevance, Summary
from mailhelp.domain.proposal import ProposalSource
from mailhelp.i18n import Locale, msg, use_locale
from mailhelp.i18n.en import EN as EN_CATALOG
from mailhelp.review.consistency import hints as consistency_hints
from mailhelp.web.archive_pages import _hints, analysis_section
from mailhelp.web.pages import e, login_page
from mailhelp.web.reconciliation_pages import sources_fragment, target_text
from tests.fakes.initial_harness import InitialHarness
from tests.fakes.initial_harness import request as initial_request
from tests.fakes.shared_setup import configured as configured  # noqa: F401
from tests.fakes.shared_web_actions import web as web  # noqa: F401
from tests.scenarios.web_scenario import mail_id

EN_HDR = {"accept-language": "en"}


def _plain(html: str) -> str:
    return unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>", "", html, flags=re.S)))


def test_b1_login_page_title_is_translated_in_english():
    with use_locale(Locale.EN):
        html = login_page("csrf-1", False)
    assert "<title>Sign in · Mailhelp</title>" in html
    assert "<title>Anmelden · Mailhelp</title>" not in html


def test_b2_decision_model_reason_is_translated_on_english_pages(web):
    state = web.store.load_model(f"mail-{mail_id(1)}", MailState)
    assert state is not None
    record = {
        "summary": {"sentences": ["Summary"], "deadlines": []},
        "relevance": {
            "decision": "relevant",
            "topic_ids": ["schule"],
            "reason": "Decision-Modell: typisierte Relevanz- und Themenentscheidung.",
        },
        "source": "JEV",
        "topics": {"schule": "School"},
    }
    with use_locale(Locale.EN):
        html = analysis_section(mail_id(1), state, record)
    assert "Decision-Modell: typisierte Relevanz- und Themenentscheidung." not in html
    assert "Decision model: typed relevance and topic decision." in html
    # Also verify B6: status label instead of raw enum value
    assert "pending_confirmation" not in html
    assert "Pending confirmation" in html


def test_b3_consistency_hints_and_heading_are_translated_in_english(web):
    state = web.store.load_model(f"mail-{mail_id(1)}", MailState)
    assert state is not None
    state.proposals = []
    state.relevance = Relevance(decision="relevant", topic_ids=["schule"], reason="Decision-Modell: typisierte Relevanz- und Themenentscheidung.")
    state.summary = Summary(sentences=["Recital"], deadlines=["2026-12-09, 16:00–17:30"])
    found = consistency_hints(state)
    assert found
    with use_locale(Locale.EN):
        html = _hints(found)
    assert "Prüfhinweise" not in html
    assert "Die Zusammenfassung nennt eine Frist" not in html
    assert "Zusammenfassung:" not in html
    assert "Review hints" in html
    assert "Summary: 2026-12-09, 16:00–17:30" in html


def test_b4_b5_reconciliation_source_mail_and_provider_labels_in_english(web):
    state = web.store.load_model(f"mail-{mail_id(1)}", MailState)
    assert state is not None
    proposal = state.proposals[0]
    proposal.target_provider = "google"
    proposal.sources = [ProposalSource(mail_id=mail_id(1), proposal_id=proposal.id, subject="Violin recital", sent_at=None)]
    with use_locale(Locale.EN):
        src_html = sources_fragment(proposal, [], "Europe/Berlin")
        target = target_text(proposal)
    assert "Quellenmail" not in src_html
    assert "Source email" in src_html
    assert "Time no longer stored" in src_html
    assert "Google Kalender" not in target
    assert "Google Calendar" in target


def test_b7_web_password_page_and_errors_are_translated_in_english(web):
    html = web.browser.request("GET", "/einstellungen/web-passwort", **EN_HDR).body.decode()
    assert "<title>Web password · Mailhelp</title>" in html
    assert "Web-Passwort ändern" not in html
    assert "Neues Passwort" not in html
    assert "Passwort speichern" not in html
    assert "Change web password" in html


def test_b8_setup_and_initial_wizard_and_message_str_trap(configured, tmp_path):
    # 1. Message(str) inside e() and join()
    with use_locale(Locale.EN):
        assert e(msg("noch nicht geprüft")) == "not checked yet"

    # 2. /einrichtung in English
    html = configured.web.browser.request("GET", "/einrichtung", **EN_HDR).body.decode()
    plain = _plain(html)
    assert "<h2>Änderungsliste</h2>" not in html
    assert "noch nicht geprüft" not in plain
    assert ": fehlt</li>" not in html

    # 3. Initial setup wizard /einrichtung/schritt/1 in English
    harness = InitialHarness(tmp_path / "initial")
    try:
        resp = initial_request(harness, "GET", "/einrichtung/schritt/1")
        assert "<title>Ersteinrichtung · Mailhelp</title>" in resp.body.decode()
        from mailhelp.web.http import Request

        en_resp = harness.app(
            Request(
                "GET",
                "/einrichtung/schritt/1",
                {"host": "127.0.0.1:8765", "cookie": f"mh_session={harness.token}; mailhelp_lang=en"},
                "",
                b"",
            )
        )
        en_html = en_resp.body.decode()
        assert "<title>Initial setup · Mailhelp</title>" in en_html
        assert "<title>Ersteinrichtung · Mailhelp</title>" not in en_html
    finally:
        harness.close()


def test_b9_b10_b11_credentials_status_and_help_title_in_english(configured):
    # B9: /einstellungen/zugangsdaten
    creds_html = configured.web.browser.request("GET", "/einstellungen/zugangsdaten", **EN_HDR).body.decode()
    assert "KI-Anbieter" not in creds_html
    assert "IMAP-Passwort" not in creds_html
    assert "OpenRouter API-Schlüssel" not in creds_html

    # B10: /status
    status_html = configured.web.browser.request("GET", "/status", **EN_HDR).body.decode()
    assert "Google Kalender" not in status_html
    assert "IMAP-Postfach" not in status_html
    assert "Jev (Relevanz)" not in status_html

    # B11: /hilfe/dokumentation
    help_html = configured.web.browser.request("GET", "/hilfe/dokumentation", **EN_HDR).body.decode()
    assert "<title>Help · Mailhelp</title>" in help_html
    assert "<title>Hilfe · Mailhelp</title>" not in help_html


def test_b12_proposal_evaluation_no_topic_and_sender_removed_in_english(configured):
    html = configured.web.browser.request("GET", "/lernen/vorschlaege", **EN_HDR).body.decode()
    assert "Ohne Thema" not in html


def test_b15_b16_catalog_data_labels_and_english_docs():
    # B15: No German data-label attributes in EN catalog values
    for key, val in EN_CATALOG.items():
        assert 'data-label="Geltungsbereich"' not in val, key
        assert 'data-label="Beispiele / Ausschlüsse"' not in val, key
        assert 'data-label="Beschreibung"' not in val, key

    # B16: No leftover German prose in docs/en/
    web_settings_en = Path("docs/en/Web-Einstellungen.md").read_text(encoding="utf-8")
    assert "Errors are in Deutsch" not in web_settings_en
    assert "TT.MM.JJJJ" not in web_settings_en
    targets_en = Path("docs/en/Ziele-einrichten.md").read_text(encoding="utf-8")
    assert "Frist: 12.05.2026, 18:00 Uhr" not in targets_en
