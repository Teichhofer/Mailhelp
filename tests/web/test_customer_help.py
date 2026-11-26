"""8.7.8 (AP4c): help index, section pages and chat sources follow the session's role."""
from __future__ import annotations

import re
from types import SimpleNamespace as NS

import pytest

from mailhelp.helpdocs import load
from mailhelp.helpdocs.roles import CUSTOMER_SECTIONS
from mailhelp.web.pages import CUSTOMER_VIEW
from tests.fakes.customer_mode import signed_in
from tests.fakes.shared_web_actions import web  # noqa: F401  (fixture)

OPERATOR_SECTION = "betrieb/betrieb-und-update"
CUSTOMER_SECTION = "bedienung/offene-entscheidungen"


@pytest.fixture
def customer(web):
    web.auth.enter_customer_mode("kunde-a")
    return web


def listed(browser) -> set[str]:
    html = browser.request("GET", "/hilfe/dokumentation").body.decode()
    return set(re.findall(r'href="/hilfe/dokumentation/([a-z0-9-]+/[a-z0-9-]+)"', html))


def test_the_help_index_and_sections_show_customers_only_their_part(customer):
    browser = signed_in(customer)
    assert listed(browser) == set(CUSTOMER_SECTIONS)
    assert browser.request("GET", "/hilfe/dokumentation/" + CUSTOMER_SECTION).status == 200
    refused = browser.request("GET", "/hilfe/dokumentation/" + OPERATOR_SECTION)
    assert refused.status == 404 and b"Diesen Abschnitt gibt es nicht." in refused.body
    operator = signed_in(customer, "operator", "Support")
    assert len(listed(operator)) == len(load().sections) and OPERATOR_SECTION in listed(operator)
    assert operator.request("GET", "/hilfe/dokumentation/" + OPERATOR_SECTION).status == 200


def test_english_customers_get_the_same_part_of_the_english_help(customer):
    browser = signed_in(customer)
    browser.request("GET", "/sprache?wert=en")
    assert listed(browser) == set(CUSTOMER_SECTIONS)


def test_chat_sources_name_no_operator_settings_for_customers(customer):
    help_site = customer.site.archive.help
    turn = NS(source_ids=[CUSTOMER_SECTION], revision=load().revision,
              setting_ids=["setting:imap.batch_size"])
    assert "/einstellungen?" in help_site._sources(turn)
    token = CUSTOMER_VIEW.set(True)
    try:
        sources = help_site._sources(turn)
    finally:
        CUSTOMER_VIEW.reset(token)
    assert CUSTOMER_SECTION in sources and "/einstellungen?" not in sources and "Einstellungen</p>" not in sources
