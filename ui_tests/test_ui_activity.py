"""2.2 activity reports in the browser: create, review, correct, no horizontal scrolling."""
from datetime import UTC, date, datetime

from playwright.sync_api import expect

from checks import audit
from conftest import sign_in
from mailhelp.activity.models import ReportEvent, ReportMail, ReportStatus
from mailhelp.activity.service import ActivityService
from mailhelp.activity.store import ActivityReportStore


def _report(mailhelp):
    service = ActivityService(ActivityReportStore(mailhelp.store))
    mailhelp.site.activity.service = service
    mailhelp.site.activity.suggest_folders = lambda: ["INBOX"]
    return service


def test_report_create_review_and_correct(page, mailhelp):
    service = _report(mailhelp)
    sign_in(page, mailhelp)
    page.goto(f"{mailhelp.url}/berichte")
    assert audit(page, f"v22-list-empty-{page.device}", page.mobile) == []
    page.get_by_role("link", name="Neuer Bericht").click()
    assert audit(page, f"v22-new-{page.device}", page.mobile) == []
    page.get_by_label("Titel", exact=True).fill("VLF-Vorsitz")
    page.get_by_label("Thema – worum es geht, was dazugehört, was nicht").fill(
        "Tätigkeiten als Vorsitzender des Vereins: Sitzungen, Versammlungen, Termine")
    page.get_by_label("Von", exact=True).fill("2026-01-01")
    page.get_by_label("Bis", exact=True).fill("2026-01-31")
    page.get_by_role("button", name="Mails zählen").click()
    expect(page.locator("main")).to_contain_text("Zählt die Mails")
    report = service.store.reports()[0]
    assert report.definition.folders == ["INBOX"]
    # The background run is simulated: a finished report with one date.
    report.status = ReportStatus.DONE
    service.store.save(report)
    service.store.save_mail(report.id, ReportMail(
        key="INBOX:7:1", folder="INBOX", uid=1, received_at=datetime(2026, 1, 10, 8, 0, tzinfo=UTC),
        sender="Vorstand <vorstand@verein.test>", subject="Einladung Vorstandssitzung",
        text="Die Vorstandssitzung findet am 20.01.2026 um 19 Uhr statt. " * 20, relevant=True,
        confidence="high", reason="Sitzung des Vorstands", events_extracted=True,
        events=[ReportEvent(id="e1", title="Vorstandssitzung", day=date(2026, 1, 20), start_time="19:00",
                            evidence="am 20.01.2026 um 19 Uhr")]))
    page.goto(f"{mailhelp.url}/berichte/{report.id}")
    expect(page.locator("tbody")).to_contain_text("Vorstandssitzung")
    assert audit(page, f"v22-report-{page.device}", page.mobile) == []
    page.get_by_role("link", name="Einladung Vorstandssitzung").click()
    assert audit(page, f"v22-mail-{page.device}", page.mobile) == []
    page.get_by_role("button", name="Ausschließen").click()
    expect(page.get_by_role("button", name="Wieder aufnehmen")).to_be_visible()
    page.get_by_role("link", name="← Zum Bericht").click()
    expect(page.locator("main")).to_contain_text("Noch keine Termine erkannt.")
    assert page.errors == []
