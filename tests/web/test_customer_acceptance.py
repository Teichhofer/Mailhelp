"""8.7.10 (AP6): acceptance 15, 17, 19 and 20 of plan 8.7 §10 with synthetic data.

15 – amounts inside a mail stay visible; 17 – usage totals do not depend on logs; 19 – roles and usage
survive a restart over the same state; 20 – heavy usage never blocks, asks for payment or a credit.
"""
from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from mailhelp.usage.valuations import UsageMeter
from mailhelp.web.auth import WebAuth
from tests.fakes.customer_mode import session_of, signed_in
from tests.fakes.shared_web_actions import web  # noqa: F401  (fixture)
from tests.fakes.shared_web_auth import SECRET
from tests.scenarios.web_scenario import mail_id, save_mail

NOW = datetime(2026, 12, 15, 11, tzinfo=UTC)
PAYMENT = re.compile(r"Guthaben|[Aa]ufladen|[Zz]ahlung|bezahlen|Rechnung des Betreibers|gesperrt|credit|top up|pay",
                     re.I)


@pytest.fixture
def customer(web, tmp_path):
    web.auth.enter_customer_mode("kunde-a")
    meter = UsageMeter(tmp_path / "state" / "usage", lambda: NOW)
    meter.valuations.add(Decimal(1), Decimal(900), "operator-cli", NOW - timedelta(days=30))
    web.site.usage.meter = meter
    web.site.clock = lambda: NOW
    return web


def test_acceptance_15_amounts_in_a_mail_stay_visible_to_customers(customer):
    save_mail(customer.store, 50, "Stadtwerke <rechnung@stadtwerke.test>", "Rechnung November 49,90 €",
              text="Bitte überweisen Sie 49,90 € bis zum 10.12.; alternativ 54.00 USD per Karte.")
    html = signed_in(customer).request("GET", "/mail/" + mail_id(50)).body.decode()
    assert "49,90 €" in html and "54.00 USD" in html and "Rechnung November 49,90 €" in html


def test_acceptance_17_usage_totals_survive_removed_logs(customer, tmp_path):
    meter = customer.site.usage.meter
    for number in range(3):
        meter.begin(f"call-{number}", "summary")
        meter.settle(f"call-{number}", "0.01")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "llm.jsonl").write_text('{"event": "response_received"}\n', encoding="utf-8")
    before = signed_in(customer).request("GET", "/verbrauch").body.decode()
    shutil.rmtree(logs)  # rotation or cleanup of the logs changes nothing
    customer.site.usage.meter = UsageMeter(tmp_path / "state" / "usage", lambda: NOW)
    after = signed_in(customer).request("GET", "/verbrauch").body.decode()
    assert "300,00 Punkte" in before
    assert re.findall(r"\d[\d.]*,\d\d Punkte", before) == re.findall(r"\d[\d.]*,\d\d Punkte", after)


def test_acceptance_19_roles_and_usage_survive_a_restart_over_the_same_state(customer, tmp_path):
    customer_browser = signed_in(customer)
    operator_browser = signed_in(customer, "operator", "Support")
    meter = customer.site.usage.meter
    meter.begin("before-restart", "summary")
    meter.settle("before-restart", "0.02")
    restarted = WebAuth(customer.store, SECRET, 30, lambda _message: None)
    restarted.enter_customer_mode("kunde-a")  # the start applies operator.yaml again
    assert restarted.authenticate(customer_browser.cookies["mh_session"]).role == "customer"
    assert restarted.is_operator(session_of(customer, operator_browser))
    reloaded = UsageMeter(tmp_path / "state" / "usage", lambda: NOW)
    assert [item.points for item in reloaded.ledger.attempts()] == [Decimal(200)]


def test_acceptance_20_heavy_usage_neither_blocks_nor_asks_for_payment(customer):
    meter = customer.site.usage.meter
    meter.begin("huge", "summary")
    meter.settle("huge", "250")  # 2.5 million points
    browser = signed_in(customer)
    usage = browser.request("GET", "/verbrauch").body.decode()
    assert "2.500.000,00 Punkte" in usage and not PAYMENT.search(usage[usage.index("<main"):])
    for path in ("/", "/mails", "/lernen", "/berichte", "/einstellungen"):
        assert browser.request("GET", path).status == 200, path
