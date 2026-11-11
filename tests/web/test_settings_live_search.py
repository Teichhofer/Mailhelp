"""5.3 H4: the authenticated live search endpoint returns public metadata only."""
import json
from urllib.parse import quote

from tests.fakes.shared_web_actions import web as web  # noqa: F401 - the fixture
from tests.fakes.shared_web_auth import Browser


def live(web, query):
    response = web.browser.request("GET", "/api/einstellungen/suche?suche=" + quote(query))
    return response, json.loads(response.body)


def test_matches_arrive_as_bounded_structured_results(web):
    response, data = live(web, "timeouts")
    assert response.status == 200 and response.cache == "no-store"
    assert data["query"] == "timeouts" and data["total"] > len(data["results"]) == 10
    assert data["all"] == "/einstellungen?suche=timeouts"
    assert set(data["results"][0]) == {"id", "label", "area", "summary", "key", "href", "path"}
    assert all(item["href"].startswith("/") for item in data["results"])


def test_the_query_is_bounded_and_an_empty_query_finds_nothing(web):
    _response, data = live(web, "  " + "z" * 120)
    assert data["query"] == "z" * 80 and data["total"] == 0 and data["results"] == []
    assert live(web, "")[1] == {"query": "", "total": 0, "all": "/einstellungen?suche=", "results": []}


def test_pages_are_found_and_nothing_but_metadata_is_returned(web):
    _response, data = live(web, "Elternbriefe")
    assert data["results"][0]["id"] == "page:iserv"
    assert "setting:iserv.accounts[].label" in {item["id"] for item in data["results"]}
    assert data["results"][0]["key"] is None and data["results"][0]["path"] == "Eigene Seite"
    body = json.dumps(data)
    assert "csrf" not in body and "password" not in body.casefold()


def test_without_a_session_the_search_answers_401(web):
    stranger = Browser(web.app)
    response = stranger.request("GET", "/api/einstellungen/suche?suche=Zeitzone", accept="application/json")
    assert response.status == 401 and json.loads(response.body) == {"error": "nicht angemeldet"}


def test_the_search_field_offers_the_live_region_on_the_overview_and_areas(web):
    for path in ("/einstellungen", "/einstellungen?bereich=abruf"):
        page = web.browser.request("GET", path).body.decode()
        assert 'data-live-search="/api/einstellungen/suche"' in page
        assert 'id="settings-live-status" role="status" aria-live="polite"' in page
        assert 'id="settings-live-results"' in page
