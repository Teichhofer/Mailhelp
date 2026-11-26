"""8.7.7 (AP4b): reports and re-analysis speak of points for customers, never of costs or money."""
from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest

from mailhelp.activity.models import FolderProgress, ReportStatus
from mailhelp.activity.service import ActivityService
from mailhelp.activity.store import ActivityReportStore
from mailhelp.config import ReanalysisSettings
from mailhelp.runtime.reanalysis_worker import ReanalysisWorker
from mailhelp.usage.valuations import UsageMeter
from mailhelp.web.reanalysis_site import ReanalysisSite
from tests.fakes.activity_fakes import definition
from tests.fakes.customer_mode import signed_in
from tests.fakes.log_fakes import RecordingLogger
from tests.fakes.reanalysis_fakes import DONE_STEPS, ReanalysisAnalyzer, ReanalysisEngine
from tests.fakes.shared_web_actions import web  # noqa: F401  (fixture)
from tests.scenarios.web_scenario import mail_id, proposal, save_mail

MONEY = re.compile(r"USD|EUR|€|\bCent\b|[Kk]ostenpflichtig|Kosten|Strom|usd_")
CREATED = datetime(2026, 1, 10, 8, 30, tzinfo=UTC)


def main(html: str) -> str:
    return html[html.index("<main"):html.index("</main>")]


def rows(*modes):
    return [{"stage": stage, "status": "success", "mode": mode, "cost_usd": "0.02", "start": 0, "end": 3600,
             "power_watts": 300, "electricity_price": 0.35}
            for stage in ("activity_relevance", "activity_events") for mode in modes]


@pytest.fixture
def reports(web, tmp_path):
    service = ActivityService(ActivityReportStore(web.store), clock=lambda: CREATED)
    web.site.activity.service = service
    web.site.usage.meter = UsageMeter(tmp_path / "usage")
    web.site.usage.meter.valuations.add(Decimal(1), Decimal(900), "operator", datetime(2020, 1, 1, tzinfo=UTC))
    web.site.archive.metrics = NS(records=lambda: (rows("standard"), 0))
    report = service.create(definition(), [], [])
    report.status = ReportStatus.READY
    report.folders = [FolderProgress(folder="INBOX", uids=[1, 2, 3, 4])]
    service.store.save(report)
    web.auth.enter_customer_mode("kunde-a")
    return web, service, report


def test_customers_see_the_report_estimate_and_start_in_points(reports):
    web, service, report = reports
    customer = signed_in(web)
    html = main(customer.request("GET", f"/berichte/{report.id}").body.decode())
    # 4 mails × 0.02 USD per step and both steps = 0.16 USD → 0.16 EUR × 10 × 1000 = 1,600 points
    assert "Geschätzter Verbrauch: bis etwa 1.600,00 Punkte bei vollständig relevanten Mails" in html
    assert "Bericht starten (verbraucht Punkte)" in html and not MONEY.search(html)
    for path in ("/berichte", "/berichte/neu", f"/berichte/{report.id}/export.xlsx"):
        assert customer.request("GET", path).status == 200, path
    operator = main(signed_in(web, "operator", "Support").request("GET", f"/berichte/{report.id}").body.decode())
    assert "Geschätzt bis etwa 0.1600 USD" in operator and "Bericht kostenpflichtig starten" in operator


@pytest.mark.parametrize(("records", "meter", "expected"), [
    ([], True, "Noch keine ausreichenden Messwerte für beide Schritte"),
    (rows("local"), True, "Der Verbrauch in Punkten lässt sich noch nicht schätzen."),
    (rows("standard"), False, "Der Verbrauch in Punkten lässt sich noch nicht schätzen."),
])
def test_without_points_basis_the_customer_estimate_says_so_without_money(reports, records, meter, expected):
    web, _service, report = reports
    web.site.archive.metrics = NS(records=lambda: (records, 0))
    if not meter:
        web.site.usage.meter = None
    html = main(signed_in(web).request("GET", f"/berichte/{report.id}").body.decode())
    assert expected in html and not MONEY.search(html)


def test_disabled_reports_name_the_operator_for_customers(reports):
    web, _service, _report = reports
    web.site.activity.service = None
    html = main(signed_in(web).request("GET", "/berichte").body.decode())
    assert "der Betreiber kann sie einschalten" in html and "prompts.yaml" not in html
    operator = main(signed_in(web, "operator", "Support").request("GET", "/berichte").body.decode())
    assert "prompts.yaml" in operator


def test_the_reanalysis_offer_speaks_of_points_for_customers(web):
    save_mail(web.store, 40, "Schule <schule@example.test>", "Klassenfahrt",
              [proposal(40, "alt", title="Elternabend vorbereiten")], text="Bitte das Formular abgeben.",
              steps=DONE_STEPS)
    worker = ReanalysisWorker(web.store, ReanalysisSettings(max_jobs_per_day=2), ReanalysisEngine(
        web.store, ReanalysisAnalyzer("Formular abgeben"), 40), RecordingLogger(), lambda account: None,
        lambda message: None, lambda actor: web.auth.active(actor.removeprefix("web:")))
    ReanalysisSite(web.site, worker)
    web.auth.enter_customer_mode("kunde-a")
    html = main(signed_in(web).request("GET", f"/mail/{mail_id(40)}").body.decode())
    assert "Höchstens 5 KI-Aufrufe, die Punkte verbrauchen" in html and "Seite „Verbrauch“" in html
    assert not MONEY.search(html) and "Auswertung" not in html
    operator = main(signed_in(web, "operator", "Support").request("GET", f"/mail/{mail_id(40)}").body.decode())
    assert "kostenpflichtige Modellaufrufe" in operator
