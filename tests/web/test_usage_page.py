"""8.7 §7.1: the usage page shows points only – today, this month, a chosen period (Abnahme 11, 14, 20)."""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from mailhelp.usage.valuations import UsageMeter, operator_purpose
from tests.fakes.customer_mode import session_of, signed_in
from tests.fakes.shared_web_actions import web  # noqa: F401  (fixture)

NOW = datetime(2026, 12, 15, 11, tzinfo=UTC)
MONEY = re.compile(r"(USD|EUR|€|\$|Cent|usd_per_eur|Aufschlag|markup|0\.01 )")


@pytest.fixture
def usage(web, tmp_path):
    clock = {"now": NOW - timedelta(days=20)}
    meter = UsageMeter(tmp_path / "usage", lambda: clock["now"])
    meter.valuations.add(Decimal("1.25"), Decimal("25"), "operator-cli", clock["now"])
    for name, when, cost in (("old", NOW - timedelta(days=20), 0.02), ("today", NOW, 0.01),
                             ("tiny", NOW, 0.0000001), ("unclear", NOW, None)):
        clock["now"] = when
        meter.begin(name, "extraction" if name == "today" else "relevance")
        meter.settle(name, cost)
    with operator_purpose():
        meter.begin("maintenance", "diagnostic_test")
        meter.settle("maintenance", 5)
    web.site.usage.meter = meter
    web.site.clock = lambda: NOW
    return web


def text(response):
    return response.body.decode()


def test_without_a_valuation_the_page_says_recording_is_not_set_up(web):
    page = text(web.browser.request("GET", "/verbrauch"))
    assert "noch nicht eingerichtet" in page and not MONEY.search(page)


def test_today_and_this_month_in_points_with_unvalued_calls_named(usage):
    page = text(usage.browser.request("GET", "/verbrauch"))
    tiles = re.findall(r'<div class="tile">.*?</div>', page)
    assert "Heute" in tiles[0] and "10,00 Punkte" in tiles[0] and "1 Aufruf(e) noch nicht bewertbar" in tiles[0]
    assert "Laufender Monat" in tiles[1] and "10,00 Punkte" in tiles[1]  # the call of last month is outside
    assert "Einzelwerte gerundet" in page and "Erfassung seit 2026-11-25" in page
    assert "6.250" not in page  # operator maintenance is not the customer's usage
    assert not MONEY.search(page.replace("Punkte", ""))


def test_a_chosen_period_with_steps_and_days(usage):
    page = text(usage.browser.request("GET", "/verbrauch?von=2026-11-01&bis=2026-12-31"))
    assert "Zeitraum 2026-11-01 bis 2026-12-31" in page and "20,00 Punkte" in page
    assert re.search(r"<th scope=\"row\">2026-11-25</th><td>20,00 Punkte</td>", page)
    assert re.search(r"<th scope=\"row\">2026-12-15</th><td>10,00 Punkte</td>", page)
    assert "<th scope=\"row\">Relevanzprüfung</th>" in page and "<th scope=\"row\">Weitere KI-Schritte</th>" in page


@pytest.mark.parametrize("query", ["von=2026-12-31&bis=2026-12-01", "von=2025-01-01&bis=2026-12-01",
                                   "von=kaputt&bis=2026-12-01", "bis=2026-12-01"])
def test_an_invalid_period_falls_back_to_this_month(usage, query):
    page = text(usage.browser.request("GET", "/verbrauch?" + query))
    assert "Zeitraum" not in page.split("<form")[0] and 'value="2026-12-01"' in page


def test_the_operator_additionally_sees_the_valuation_in_force(usage):
    usage.auth.enter_customer_mode("kunde-a")
    customer = text(signed_in(usage).request("GET", "/verbrauch"))
    operator_browser = signed_in(usage, "operator", "Support")
    operator = text(operator_browser.request("GET", "/verbrauch"))
    assert "Bewertungsstand 1" not in customer and not MONEY.search(customer.replace("Punkte", ""))
    assert "Bewertungsstand 1, 1.25 USD je EUR, Aufschlag 25 %" in operator
    assert session_of(usage, operator_browser).role == "operator"


def test_a_valuation_without_any_call_yet_shows_zero_without_tables(web, tmp_path):
    meter = UsageMeter(tmp_path / "usage", lambda: NOW)
    meter.valuations.add(Decimal("1.25"), Decimal("25"), "operator-cli", NOW + timedelta(days=1))
    web.site.usage.meter, web.site.clock = meter, lambda: NOW
    web.auth.enter_customer_mode("kunde-a")
    page = text(signed_in(web, "operator", "Support").request("GET", "/verbrauch"))
    assert "0,00 Punkte" in page and "<table" not in page and "Erfassung seit" not in page
    assert "noch nicht bewertbar" not in page and "Bewertungsstand" not in page  # not valid yet


def test_english_points(usage):
    usage.browser.cookies["mailhelp_lang"] = "en"
    page = text(usage.browser.request("GET", "/verbrauch"))
    assert "10.00 points" in page and "10,00 Punkte" not in page and "1 call(s) cannot be valued yet" in page
