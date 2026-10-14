"""Report filters, measured estimates and local evidence checks with synthetic data."""
from datetime import UTC, date, datetime

import pytest
from activity_fakes import definition

from mailhelp.action_normalization import evidence_date_matches
from mailhelp.activity.costs import estimate
from mailhelp.activity.models import ActivityReport, FolderProgress, ReportEvent, ReportMail
from mailhelp.activity.presentation import ReportFilter, fingerprint, highlighted_text


def source():
    return ReportMail(key="INBOX:7:1", folder="INBOX", uid=1, sender="School <school@example.test>",
                      received_at=datetime(2026, 1, 10, tzinfo=UTC), relevant=True, confidence="low",
                      text="<script>alert(1)</script> Am 20. Januar\n um 19 Uhr.", events=[
                          ReportEvent(id="e1", title="Meeting", day=date(2026, 1, 20),
                                      evidence="Am 20. Januar um 19 Uhr"),
                          ReportEvent(id="e2", title="Cancelled", day=date(2026, 2, 20), cancelled=True),
                          ReportEvent(id="e3", title="Excluded", day=date(2026, 1, 21), excluded=True)])


def test_filters_select_month_sender_uncertainty_and_excluded_dates():
    mail = source()
    assert len(ReportFilter().rows([mail])) == 1
    assert len(ReportFilter.parse("excluded=on").rows([mail])) == 3
    assert len(ReportFilter.parse("month=2026-02&excluded=on&sender=SCHOOL").rows([mail])) == 1
    assert ReportFilter.parse("month=2027-01").rows([mail]) == []
    assert ReportFilter.parse("sender=nobody").rows([mail]) == []
    assert ReportFilter.parse("month=bad").month == ""
    assert len(ReportFilter.parse("uncertain=on").rows([mail])) == 1
    mail.user_relevant = True
    assert ReportFilter.parse("uncertain=on").rows([mail]) == []
    mail.user_relevant, mail.confidence = None, "high"
    assert ReportFilter.parse("uncertain=on").rows([mail]) == []


def test_highlights_quotes_but_never_mail_html_or_overlapping_matches():
    mail = source()
    mail.events.append(mail.events[0].model_copy(update={"id": "e4"}))
    text = highlighted_text(mail)
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert text.count("<mark>") == 1 and "<mark>Am 20. Januar\n um 19 Uhr</mark>" in text
    report = ActivityReport(id="a" * 32, definition=definition())
    before = fingerprint(report, [mail])
    mail.events[0].excluded = True
    assert fingerprint(report, [mail]) != before


@pytest.mark.parametrize("quote,day,expected", [
    ("am 20. Januar um 19 Uhr", "2026-01-20", True),
    ("am 20. Januar um 19 Uhr", "2026-01-21", False),
    ("20. Januar 2025", "2026-01-20", False),
    ("Dienstag, 20. Januar 2026", "2026-01-20", True),
    ("Montag, 20. Januar 2026", "2026-01-20", False),
    ("am 20.1.2026", "2026-01-20", True),
    ("am 20.1.", "2026-01-20", True),
    ("Dienstag 20.01.2026", "2026-01-20", True),
    ("2026-01-20", "2026-01-20", True),
    ("am 31. Februar", "2026-02-28", False),
    ("morgen", "2026-01-11", True),
    ("gestern", "2026-01-11", False),
    ("Sitzung", "2026-01-20", True),
])
def test_evidence_dates_check_explicit_weekdays_and_relative_mail_context(quote, day, expected):
    assert evidence_date_matches(date.fromisoformat(day), quote, date(2026, 1, 10)) is expected


def test_estimates_use_measured_steps_and_local_electricity():
    report = ActivityReport(id="a" * 32, definition=definition(), folders=[FolderProgress(folder="INBOX", uids=[1, 2])])
    assert "nur Aufrufzahlen" in estimate(report, [])
    rows = [{"stage": stage, "status": "success", "mode": "standard", "cost_usd": "0.02"}
            for stage in ("activity_relevance", "activity_events")]
    assert "0.0800 USD" in estimate(report, rows)
    rows[1].update(mode="local", start=0, end=3600, power_watts=1000, electricity_price=0.3)
    assert "0.0400 USD, 0.6000 EUR Strom" in estimate(report, rows)
    rows[0]["cost_usd"] = None
    assert "nur Aufrufzahlen" in estimate(report, rows)
    for row in rows:
        row.update(mode="standard", cost_usd="0")
    assert "0.0000 USD" in estimate(report, rows)
