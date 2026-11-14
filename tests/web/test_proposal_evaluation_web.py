"""Web tests for proposal evaluation and acceptance rates (Planung 6.5, 3.1)."""
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mailhelp import state_names
from mailhelp.domain.proposal import ProposalKind, ProposalStatus
from mailhelp.models import MailState, Proposal
from tests.fakes.shared_web_auth import Browser, signed_in, site


def _seed_proposals(store):
    now = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    mid = "000000000000000000000001"
    mail_1 = MailState(
        id=mid,
        config_fingerprint="0" * 64,
        created_at=now,
        updated_at=now,
        imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 1},
        mail={"headers": {"from": "sender@test.de", "subject": "Termin"}},
        relevance={"decision": "relevant", "topic_ids": ["schule"], "reason": "Test"},
    )
    store.save(state_names.mail(mid), mail_1.model_dump(mode="json"))

    prop_1 = Proposal(
        id="p1",
        version=1,
        source_mail_id=mid,
        kind=ProposalKind.EVENT,
        responsibility="user",
        certainty="certain",
        classification="new",
        title="Schulfest",
        evidence="Quelle",
        target="inbox",
        status=ProposalStatus.CREATED,
        start=now,
        end=now + timedelta(hours=1),
    )
    store.save(state_names.proposal(mid, "p1"), prop_1.model_dump(mode="json"))

    prop_2 = Proposal(
        id="p2",
        version=1,
        source_mail_id=mid,
        kind=ProposalKind.TASK,
        responsibility="user",
        certainty="certain",
        classification="new",
        title="Kuchen mitbringen",
        evidence="Quelle",
        target="inbox",
        status=ProposalStatus.REJECTED,
    )
    store.save(state_names.proposal(mid, "p2"), prop_2.model_dump(mode="json"))


def test_proposal_evaluation_empty_and_populated(site):
    browser, _ = signed_in(site)
    store = site.site.views.store

    # 1. Empty state
    res = browser.request("GET", "/lernen/vorschlaege")
    assert res.status == 200
    html = res.body.decode()
    assert "In diesem Zeitraum liegen keine entschiedenen Vorschläge vor." in html

    # 2. Populated state
    _seed_proposals(store)
    res = browser.request("GET", "/lernen/vorschlaege")
    assert res.status == 200
    html = res.body.decode()
    assert "Annahmequote gesamt" in html
    assert "Aufgaben" in html
    assert "Termine" in html
    assert "50 %" in html  # 1 accepted of 2 decided = 50%
    assert "sender@test.de" in html
    assert "Verlauf je Woche" in html
    assert "Gründe für Ablehnungen" in html

    # 3. Test sorting options and invalid days
    for sort_topic in ("name", "quote", "decided"):
        r = browser.request("GET", f"/lernen/vorschlaege?days=30&sort_topic={sort_topic}")
        assert r.status == 200
    for sort_sender in ("name", "quote", "decided", "rejected"):
        r = browser.request("GET", f"/lernen/vorschlaege?days=30&sort_sender={sort_sender}")
        assert r.status == 200
    r_invalid = browser.request("GET", "/lernen/vorschlaege?days=invalid")
    assert r_invalid.status == 200

    # 4. Learning overview card links to /lernen/vorschlaege
    res_overview = browser.request("GET", "/lernen")
    assert res_overview.status == 200
    html_overview = res_overview.body.decode()
    assert "/lernen/vorschlaege" in html_overview
    assert "50 % Annahmequote" in html_overview

    # 5. Proposal without mail state -> "Absender entfernt"
    prop_no_mail = Proposal(
        id="p3",
        version=1,
        source_mail_id="000000000000000000000002",
        kind=ProposalKind.TASK,
        responsibility="user",
        certainty="certain",
        classification="new",
        title="Ohne Mail",
        evidence="Quelle",
        target="inbox",
        status=ProposalStatus.CREATED,
    )
    store.save(state_names.proposal("000000000000000000000002", "p3"), prop_no_mail.model_dump(mode="json"))
    res_removed = browser.request("GET", "/lernen/vorschlaege")
    assert "Absender entfernt" in res_removed.body.decode()


def test_proposal_evaluation_only_accepted_no_reasons(site):
    browser, _ = signed_in(site)
    store = site.site.views.store
    mid = "000000000000000000000010"
    prop = Proposal(
        id="p10",
        version=1,
        source_mail_id=mid,
        kind=ProposalKind.TASK,
        responsibility="user",
        certainty="certain",
        classification="new",
        title="Nur angenommen",
        evidence="Quelle",
        target="inbox",
        status=ProposalStatus.CREATED,
    )
    store.save(state_names.proposal(mid, "p10"), prop.model_dump(mode="json"))
    res = browser.request("GET", "/lernen/vorschlaege")
    assert res.status == 200
    html = res.body.decode()
    assert "100 %" in html
    assert "Gründe für Ablehnungen" not in html


def test_sender_hints_web_and_actions(site):
    browser, _ = signed_in(site)
    store = site.site.views.store
    now = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)

    # Seed 5 rejected proposals from spam@promo.com
    for i in range(5):
        mid = f"{i + 20:024x}"
        pid = f"p_spam_{i}"
        prop = Proposal(
            id=pid,
            version=1,
            source_mail_id=mid,
            kind=ProposalKind.TASK,
            responsibility="user",
            certainty="certain",
            classification="new",
            title=f"Promo {i}",
            evidence="Quelle",
            target="inbox",
            status=ProposalStatus.REJECTED,
            reject_reason="advertising",
        )
        mail = MailState(
            id=mid,
            config_fingerprint="0" * 64,
            created_at=now - timedelta(days=2),
            updated_at=now - timedelta(days=2),
            imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 1},
            mail={"headers": {"from": "spam@promo.com", "subject": f"Promo {i}"}},
            relevance={"decision": "relevant", "topic_ids": ["werbung"], "reason": "Test"},
            proposals=[prop],
        )
        store.save(state_names.mail(mid), mail.model_dump(mode="json"))
        store.save(state_names.proposal(mid, pid), prop.model_dump(mode="json"))

    # Also a corrupt mail state, a None mail state, and a mail from another sender
    store.save("mail-000000000000000000000099", {"corrupt": "data"})
    store.save("mail-000000000000000000000088", None)
    other_mid = f"{98:024x}"
    other_mail = MailState(
        id=other_mid,
        config_fingerprint="0" * 64,
        created_at=now,
        imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 1},
        mail={"headers": {"from": "other@example.org", "subject": "Other"}},
    )
    store.save(state_names.mail(other_mid), other_mail.model_dump(mode="json"))

    # 1. /lernen/vorschlaege shows sender hint
    res = browser.request("GET", "/lernen/vorschlaege")
    assert res.status == 200
    html = res.body.decode()
    assert "Hinweise zu Absendern" in html
    assert "spam@promo.com" in html
    assert "5 von 5 Vorschlägen verworfen" in html
    assert "/lernen/absender-hinweis?sender=spam%40promo.com" in html

    # 2. Preview page
    r_empty_sender = browser.request("GET", "/lernen/absender-hinweis")
    assert r_empty_sender.status == 404
    r_unknown_sender = browser.request("GET", "/lernen/absender-hinweis?sender=unknown%40other.com")
    assert r_unknown_sender.status == 404

    r_preview = browser.request("GET", "/lernen/absender-hinweis?sender=spam%40promo.com")
    assert r_preview.status == 200
    html_preview = r_preview.body.decode()
    assert "Absender: spam@promo.com" in html_preview
    assert "Gespeicherte Mails dieses Absenders (5)" in html_preview
    assert "In Vorfilter aufnehmen" in html_preview
    assert "Nicht mehr vorschlagen" in html_preview
    assert "Verworfen: Promo 0" in html_preview

    # 3. Dismiss hint (including empty sender check)
    csrf = browser.csrf("/lernen/absender-hinweis?sender=spam%40promo.com")
    r_dismiss_empty = browser.request("POST", "/lernen/absender-hinweis/nicht-mehr-vorschlagen",
                                      {"csrf": csrf, "sender": ""})
    assert r_dismiss_empty.status == 303

    r_dismiss = browser.request("POST", "/lernen/absender-hinweis/nicht-mehr-vorschlagen",
                                {"csrf": csrf, "sender": "spam@promo.com"})
    assert r_dismiss.status == 303
    assert r_dismiss.headers["Location"] == "/lernen/vorschlaege"

    # Now it is under dismissed hints
    res_dismissed = browser.request("GET", "/lernen/vorschlaege")
    html_dismissed = res_dismissed.body.decode()
    assert "Zuvor verworfene Absender-Hinweise (1)" in html_dismissed
    assert "Wieder zulassen" in html_dismissed

    # 4. Restore hint (including empty sender check)
    csrf_restore = browser.csrf("/lernen/vorschlaege")
    r_restore_empty = browser.request("POST", "/lernen/absender-hinweis/wieder-zulassen",
                                      {"csrf": csrf_restore, "sender": ""})
    assert r_restore_empty.status == 303

    r_restore = browser.request("POST", "/lernen/absender-hinweis/wieder-zulassen",
                                {"csrf": csrf_restore, "sender": "spam@promo.com"})
    assert r_restore.status == 303
    assert r_restore.headers["Location"] == "/lernen/vorschlaege"

    res_restored = browser.request("GET", "/lernen/vorschlaege")
    assert "Hinweise zu Absendern" in res_restored.body.decode()

    # 5. Apply sender filter without configuration service -> 503
    csrf_preview = browser.csrf("/lernen/absender-hinweis?sender=spam%40promo.com")
    r_apply_no_cfg = browser.request("POST", "/lernen/absender-hinweis/uebernehmen",
                                     {"csrf": csrf_preview, "sender": "spam@promo.com"})
    assert r_apply_no_cfg.status == 503

    # With configuration service:
    from mailhelp.configuration import ConfigurationService
    from tests.fakes.shared_application import settings
    tmp_path = store.directory.parent
    cfg_service = ConfigurationService(
        tmp_path, store, settings(tmp_path),
        lambda actor: True, lambda active: None, senders=store,
    )
    site.site.archive.configuration = cfg_service
    # path.exists() is False before file is created
    r_no_hash = browser.request("GET", "/lernen/absender-hinweis?sender=spam%40promo.com")
    assert r_no_hash.status == 200

    # Create irrelevant-senders.json file so expected_hash is computed
    (cfg_service.directory / "irrelevant-senders.json").write_text("{}", encoding="utf-8")

    # Invalid sender (no email address) -> 422
    r_invalid_sender = browser.request("POST", "/lernen/absender-hinweis/uebernehmen",
                                       {"csrf": csrf_preview, "sender": "ungueltiger-name"})
    assert r_invalid_sender.status == 422

    # Invalid AdminCommand (e.g. invalid key format) -> 422
    r_invalid_key = browser.request("POST", "/lernen/absender-hinweis/uebernehmen",
                                    {"csrf": csrf_preview, "sender": "spam@promo.com", "key": "short"})
    assert r_invalid_key.status == 422

    # Valid sender -> queued AdminCommand
    r_apply_ok = browser.request("POST", "/lernen/absender-hinweis/uebernehmen",
                                 {"csrf": csrf_preview, "sender": "spam@promo.com"})
    assert r_apply_ok.status in {200, 303}

    # Now verify preview page with expected_hash and configuration active
    r_preview_with_cfg = browser.request("GET", "/lernen/absender-hinweis?sender=spam%40promo.com")
    assert r_preview_with_cfg.status == 200

    # Also home page with configuration active
    r_home_with_cfg = browser.request("GET", "/lernen/vorschlaege")
    assert r_home_with_cfg.status == 200


def test_learning_run_hint_web(site):
    browser, _ = signed_in(site)
    store = site.site.views.store
    now = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)

    # Seed 20 rejections in decisions.jsonl
    log_dir = store.directory / "learning"
    log_dir.mkdir(parents=True, exist_ok=True)
    import json
    lines = [
        json.dumps({
            "id": f"d_{i}",
            "kind": "reject",
            "mail_id": f"m_{i}",
            "proposal_id": f"p_{i}",
            "recorded_at": (now - timedelta(days=1)).isoformat(),
        })
        for i in range(20)
    ]
    (log_dir / "decisions.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Banner visible on /lernen, /lernen/vorschlaege, and /
    for path in ("/lernen", "/lernen/vorschlaege", "/"):
        res = browser.request("GET", path)
        assert res.status == 200
        assert "Lernlauf empfohlen:" in res.body.decode()
        assert "20 neue Ablehnungen" in res.body.decode()

    # Dismiss banner
    csrf = browser.csrf("/lernen")
    r_dismiss = browser.request("POST", "/lernen/hinweis-ausblenden", {"csrf": csrf})
    assert r_dismiss.status == 303
    assert r_dismiss.headers["Location"] == "/lernen"

    # Banner now hidden
    for path in ("/lernen", "/lernen/vorschlaege", "/"):
        res = browser.request("GET", path)
        assert res.status == 200
        assert "Lernlauf empfohlen:" not in res.body.decode()


