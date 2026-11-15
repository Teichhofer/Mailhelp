"""Tests for Telegram summary deadlines line (Planung 6.7, D4, 3.4, E3).

Verifies D4:
- Telegram summary notification contains deadlines line when future deadlines exist
- At most 3 future deadlines are included
- Past deadlines are omitted
- When all deadlines are past or list is empty, no Fristen line is appended
- Older states without deadlines remain unchanged
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from mailhelp.domain.extraction import Summary
from mailhelp.domain.mail import MailImapIdentity, MailState
from mailhelp.domain.relevance import Relevance
from mailhelp.processing.orchestrator import Orchestrator
from tests.fakes.shared_services import AnalyzerStub, Notify


def _sample_state(deadlines: list[str] | None = None) -> MailState:
    mail_data = {
        "headers": {"sender": "sender@example.test", "subject": "Test Betreff"},
        "extracted_text": "Text",
        "date_context": {
            "date_context_status": "valid",
            "received_at": "2026-11-14T12:00:00+00:00",
            "header_date": "2026-11-14T12:00:00+00:00",
            "user_timezone": "Europe/Berlin",
        },
    }
    summary = Summary(
        sentences=["Dies ist der erste Satz.", "Dies ist der zweite Satz."],
        deadlines=deadlines if deadlines is not None else [],
    )
    relevance = Relevance(
        decision="relevant",
        topic_ids=["schule"],
        reason="Beleg",
    )
    return MailState(
        id="a" * 24,
        config_fingerprint="0" * 64,
        imap=MailImapIdentity(account_id="0" * 24, folder="INBOX", uidvalidity=1, uid=1),
        mail=mail_data,
        relevance=relevance,
        summary=summary,
    )


def _orchestrator(clock_dt: datetime = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)) -> Orchestrator:
    clock = lambda: clock_dt.timestamp()
    store = SimpleNamespace(load=lambda *args: None, save=lambda *args: None)
    return Orchestrator(
        AnalyzerStub("relevant"),
        store,
        Notify(),
        1,
        [],
        SimpleNamespace(max_llm_payload_bytes=500000),
        clock=clock,
        user_timezone="Europe/Berlin",
    )


def test_notification_text_without_deadlines():
    orch = _orchestrator()
    state = _sample_state(deadlines=[])
    text = orch.notification_text(state)
    assert "• Dies ist der erste Satz." in text
    assert "• Dies ist der zweite Satz." in text
    assert "Fristen:" not in text


def test_notification_text_with_future_deadlines():
    orch = _orchestrator()
    state = _sample_state(deadlines=["15.03.2027", "2027-04-20"])
    text = orch.notification_text(state)
    assert "• Dies ist der erste Satz." in text
    assert "\nFristen: 15.03.2027; 2027-04-20" in text


def test_notification_text_filters_past_deadlines():
    orch = _orchestrator()
    # 2020-01-01 is in the past, 2027-03-15 is in the future
    state = _sample_state(deadlines=["01.01.2020", "15.03.2027"])
    text = orch.notification_text(state)
    assert "01.01.2020" not in text
    assert "\nFristen: 15.03.2027" in text


def test_notification_text_all_past_deadlines_omits_line():
    orch = _orchestrator()
    state = _sample_state(deadlines=["01.01.2020", "2020-05-10"])
    text = orch.notification_text(state)
    assert "Fristen:" not in text


def test_notification_text_limits_to_three_deadlines():
    orch = _orchestrator()
    state = _sample_state(
        deadlines=["01.01.2027", "02.01.2027", "03.01.2027", "04.01.2027", "05.01.2027"]
    )
    text = orch.notification_text(state)
    assert "Fristen: 01.01.2027; 02.01.2027; 03.01.2027" in text
    assert "04.01.2027" not in text
    assert "05.01.2027" not in text


def test_notification_text_with_unparseable_deadline_kept_as_future():
    orch = _orchestrator()
    state = _sample_state(deadlines=["Ende nächster Woche"])
    text = orch.notification_text(state)
    assert "\nFristen: Ende nächster Woche" in text


def test_future_deadlines_with_clock_fallback():
    orch = _orchestrator()
    orch.clock = lambda: "invalid"  # will cause TypeError/Exception
    state = _sample_state(deadlines=["2099-01-01"])
    deadlines = orch._future_deadlines(state)
    assert deadlines == ["2099-01-01"]


def test_future_deadlines_none_summary():
    orch = _orchestrator()
    state = _sample_state()
    state.summary = None
    assert orch._future_deadlines(state) == []


def test_future_deadlines_without_prepared_mail():
    orch = _orchestrator()
    state = _sample_state(deadlines=["2027-05-01", "01.05.2027", "99.99.2027", "2020-01-01", "01.01.2020"])
    state.mail = None
    # 2027-05-01 (ISO), 01.05.2027 (German), 99.99.2027 (fails ValueError on both)
    # The past dates (2020) are excluded
    assert orch._future_deadlines(state) == ["2027-05-01", "01.05.2027", "99.99.2027"]
