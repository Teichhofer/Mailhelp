"""8.0: "Mit Google verbinden" from the instance through the central service (synthetic only)."""
import re
from html import unescape
from urllib.parse import urlsplit

import pytest

from mailhelp.web.hosted_google_site import PENDING, HostedGoogleSite, HostedProfiles, session_reference
from mailhelp.web.http import SECURITY_HEADERS
from tests.fakes.hosted_google import Central
from tests.fakes.shared_web_actions import web as web  # noqa: F401 - the fixture
from tests.fakes.shared_web_auth import Browser


class Profiles:
    """Setup drafts of target profiles 1 and 2 as a test double of the setup flows."""

    def __init__(self):
        self.connections = {1: "", 2: ""}
        self.version = 1
        self.saved: list[tuple] = []

    def draft(self, profile):
        if profile not in self.connections:
            raise LookupError(profile)
        return self.connections[profile], self.version

    def save(self, actor, profile, values, version, key):
        if version != self.version:
            raise ValueError("Entwurf geändert")
        self.saved.append((actor, profile, values, version))
        self.connections[profile] = values.get("google_connection", self.connections[profile])
        self.version += 1

    def target(self, profile):
        self.draft(profile)
        return f"profile:{profile}"


@pytest.fixture
def central(tmp_path):
    hub = Central(tmp_path)
    yield hub
    hub.close()


@pytest.fixture
def hosted(web, central):
    profiles = Profiles()
    client = central.client("anna")
    state = {"client": client}
    web.hosted_site = HostedGoogleSite(web.site, web.store, lambda: state["client"],
                                       HostedProfiles(profiles.draft, profiles.save, profiles.target), "/einrichtung",
                                       transport=central.transport("anna"))
    web.profiles, web.central, web.hosted_state = profiles, central, state
    yield web
    client.close()


def fields(html, action):
    block = re.search(rf'<form method="post" action="{re.escape(action)}"[^>]*>(.*?)</form>', html, re.S)[1]
    return {name: unescape(value) for name, value in re.findall(r'name="([^"]+)" value="([^"]*)"', block)}


def connect(web, profile=1, code="good"):
    """Start, Google's consent and the return to the instance; returns the completion page."""
    page = web.browser.request("GET", f"/google/verbinden?profile={profile}").body.decode()
    started = web.browser.request("POST", "/google/verbinden", fields(page, "/google/verbinden"))
    assert started.status == 303 and started.headers["Cache-Control"] == "no-store"
    back = web.central.google_return(started.headers["Location"], code)
    assert back.startswith("https://anna.inboxstride.example/einrichtung/google/abschluss?")
    parts = urlsplit(back)
    return web.browser.request("GET", f"{parts.path}?{parts.query}")


def test_a_first_connection_needs_no_google_secret_and_ends_with_an_explicit_adoption(hosted):
    page = hosted.browser.request("GET", "/google/verbinden?profile=1").body.decode()
    assert "<h1>Mit Google verbinden</h1>" in page and "legt keine Termine an" in page
    returned = connect(hosted)
    assert returned.headers["Cache-Control"] == "no-store" and returned.headers["Referrer-Policy"] == "no-referrer"
    redeemed = hosted.browser.request("POST", "/einrichtung/google/abschluss",
                                      fields(returned.body.decode(), "/einrichtung/google/abschluss"))
    assert redeemed.status == 303 and redeemed.headers["Location"] == "/google/kalender"
    choose = hosted.browser.request("GET", "/google/kalender").body.decode()
    assert "Familie" in choose and "Feiertage" not in choose  # only calendars with write access
    assert hosted.profiles.saved == []  # nothing adopted before the explicit choice
    form = fields(choose, "/google/kalender")
    adopted = hosted.browser.request("POST", "/google/kalender",
                                     {**form, "calendar": "familie@group.calendar.google.com"})
    assert adopted.status == 303 and adopted.headers["Location"] == "/einrichtung"
    ((actor, profile, values, _version),) = hosted.profiles.saved
    assert actor.startswith("web:") and profile == 1 and values["calendar_provider"] == "google"
    assert values["google_calendar"] == "familie@group.calendar.google.com"
    connection = hosted.central.service.state.read().connections[values["google_connection"]]
    assert (connection.status, connection.instance, connection.target) == ("active", "anna", "profile:1")
    assert hosted.store.load(PENDING, {}) == {}
    again = hosted.browser.request("GET", "/google/verbinden?profile=1").body.decode()
    assert "<h1>Google erneut verbinden</h1>" in again


def form_targets(response):
    policy = {**SECURITY_HEADERS, **response.headers}["Content-Security-Policy"]  # as sent (web/http.py)
    return next(part for part in policy.split("; ") if part.startswith("form-action")).split()[1:]


def test_the_connect_page_allows_its_form_to_continue_to_google(hosted):
    # Bugfix 7.9.8: browsers apply form-action to the redirect after a POST; with 'self' alone a click on
    # "Weiter zu Google" only greyed out the button. Only this page may send its form on to Google.
    page = hosted.browser.request("GET", "/google/verbinden?profile=1")
    assert form_targets(page) == ["'self'", "https://accounts.google.com"]
    started = hosted.browser.request("POST", "/google/verbinden", fields(page.body.decode(), "/google/verbinden"))
    assert urlsplit(started.headers["Location"]).netloc == "accounts.google.com"
    assert form_targets(hosted.browser.request("GET", "/einstellungen")) == ["'self'"]
    assert form_targets(hosted.browser.request("GET", "/google/kalender")) == ["'self'"]


def test_reconnecting_replaces_the_old_access_only_after_adoption(hosted):
    returned = connect(hosted)
    hosted.browser.request("POST", "/einrichtung/google/abschluss",
                           fields(returned.body.decode(), "/einrichtung/google/abschluss"))
    form = fields(hosted.browser.request("GET", "/google/kalender").body.decode(), "/google/kalender")
    hosted.browser.request("POST", "/google/kalender", {**form, "calendar": "familie@group.calendar.google.com"})
    first = hosted.profiles.connections[1]
    returned = connect(hosted, code="second")
    hosted.browser.request("POST", "/einrichtung/google/abschluss",
                           fields(returned.body.decode(), "/einrichtung/google/abschluss"))
    state = hosted.central.service.state.read()
    assert state.connections[first].status == "active"  # untouched while the new one waits
    form = fields(hosted.browser.request("GET", "/google/kalender").body.decode(), "/google/kalender")
    hosted.browser.request("POST", "/google/kalender", {**form, "calendar": "familie@group.calendar.google.com"})
    state = hosted.central.service.state.read()
    second = hosted.profiles.connections[1]
    assert second != first and state.connections[first].status == "disconnected"
    assert state.connections[second].generation == 2


def test_the_return_without_the_session_cookie_continues_only_by_a_same_origin_click(hosted):
    page = hosted.browser.request("GET", "/google/verbinden?profile=1").body.decode()
    started = hosted.browser.request("POST", "/google/verbinden", fields(page, "/google/verbinden"))
    back = urlsplit(hosted.central.google_return(started.headers["Location"]))
    stranger = Browser(hosted.app)
    answer = stranger.request("GET", f"{back.path}?{back.query}").body.decode()
    assert "Bitte im ursprünglichen Browser fortsetzen" in answer and 'action="/einrichtung' not in answer
    assert stranger.request("POST", "/einrichtung/google/abschluss", {"beleg": "x" * 20}).status in {303, 403}


def test_a_receipt_of_another_session_or_instance_is_useless(hosted, central):
    returned = connect(hosted)
    receipt = fields(returned.body.decode(), "/einrichtung/google/abschluss")["beleg"]
    other = central.client("bert")
    from mailhelp.external.hosted_oauth import HostedRefused
    with pytest.raises(HostedRefused):
        other.post("/intern/redeem", {"session": "f" * 64, "receipt": receipt})
    other.close()
    form = fields(returned.body.decode(), "/einrichtung/google/abschluss")
    hosted.store.save(PENDING, {})
    assert hosted.browser.request("POST", "/einrichtung/google/abschluss", {**form, "beleg": "falsch"}).status == 409
    assert hosted.browser.request("POST", "/einrichtung/google/abschluss", form).status == 303
    assert hosted.browser.request("POST", "/einrichtung/google/abschluss", form).status == 409  # used once


@pytest.mark.parametrize(("query", "status", "text"), [
    ("abbruch=1", 200, "Google-Verbindung abgebrochen"),
    ("beleg=%3Cscript%3E", 400, "Abschlussbeleg fehlt"),
    ("", 400, "Abschlussbeleg fehlt"),
])
def test_unusable_returns_explain_themselves(hosted, query, status, text):
    answer = hosted.browser.request("GET", f"/einrichtung/google/abschluss?{query}")
    assert answer.status == status and text in answer.body.decode()


def test_a_cancelled_or_refused_google_consent_keeps_everything(hosted):
    page = hosted.browser.request("GET", "/google/verbinden?profile=1").body.decode()
    started = hosted.browser.request("POST", "/google/verbinden", fields(page, "/google/verbinden"))
    back = hosted.central.google_return(started.headers["Location"], error="access_denied")
    assert back.endswith("?abbruch=1") and hosted.profiles.saved == []
    returned = connect(hosted, code="narrow")  # without the calendar scopes
    assert returned.status == 200 and "abgebrochen" in returned.body.decode()


def test_without_the_central_service_nothing_changes(hosted):
    hosted.hosted_state["client"] = None
    assert hosted.browser.request("GET", "/google/verbinden?profile=1").status == 503
    page = hosted.browser.request("GET", "/einstellungen").body.decode()
    csrf = re.search(r'name="csrf" value="([^"]+)"', page)[1] if 'name="csrf"' in page else ""
    for path, form in (("/google/verbinden", {"profile": "1", "key": "k" * 32}),
                       ("/einrichtung/google/abschluss", {"beleg": "x" * 20}),
                       ("/google/kalender", {"calendar": "x", "version": "1", "key": "k" * 32})):
        assert hosted.browser.request("POST", path, {**form, "csrf": csrf or hosted.auth.csrf_token(
            session_of(hosted))}).status == 503
    assert hosted.browser.request("GET", "/google/kalender").status == 503


def session_of(web):
    token = web.browser.cookies["mh_session"]
    return web.auth.authenticate(token).id


def test_outages_and_wrong_answers_keep_the_previous_connection(hosted, central):
    csrf = hosted.auth.csrf_token(session_of(hosted))
    central.down = True
    assert hosted.browser.request("POST", "/google/verbinden", {"csrf": csrf, "profile": "1",
                                                                "key": "k" * 32}).status == 503
    central.down = False
    assert hosted.browser.request("POST", "/google/verbinden", {"csrf": csrf, "profile": "7",
                                                                "key": "k" * 32}).status == 400
    assert hosted.browser.request("POST", "/google/verbinden", {"csrf": csrf, "profile": "1"}).status == 400
    assert hosted.browser.request("GET", "/google/verbinden?profile=7").status == 404
    assert hosted.browser.request("GET", "/google/verbinden?profile=100").status == 404
    returned = connect(hosted)
    form = fields(returned.body.decode(), "/einrichtung/google/abschluss")
    central.down = True
    assert hosted.browser.request("POST", "/einrichtung/google/abschluss", form).status == 503
    central.down = False
    assert hosted.browser.request("POST", "/einrichtung/google/abschluss", form).status == 303
    central.calendars = [{"id": "nur-lesen", "summary": "Nur lesen", "accessRole": "reader"}]
    assert "keinen Kalender mit Schreibrecht" in hosted.browser.request("GET", "/google/kalender").body.decode()
    central.calendars = [{"id": 5, "summary": "kaputt"}]
    assert hosted.browser.request("GET", "/google/kalender").status == 503
    central.calendars = [{"id": "familie", "summary": "Familie", "accessRole": "writer"}]
    choose = fields(hosted.browser.request("GET", "/google/kalender").body.decode(), "/google/kalender")
    assert hosted.browser.request("POST", "/google/kalender", {**choose, "calendar": "anderer"}).status == 409
    stale = {**choose, "calendar": "familie", "version": "99"}
    assert hosted.browser.request("POST", "/google/kalender", stale).status == 409
    central.down = True
    assert hosted.browser.request("POST", "/google/kalender", {**choose, "calendar": "familie"}).status == 503
    central.down = False
    assert hosted.profiles.saved == []


def test_an_expired_or_missing_pending_sign_in_asks_to_start_again(hosted):
    assert "Kein offener Google-Vorgang" in hosted.browser.request("GET", "/google/kalender").body.decode()
    csrf = hosted.auth.csrf_token(session_of(hosted))
    answer = hosted.browser.request("POST", "/google/kalender", {"csrf": csrf, "calendar": "x", "version": "1",
                                                                 "key": "k" * 32})
    assert answer.status == 409 and "Kein offener Google-Vorgang" in answer.body.decode()
    hosted.store.save(PENDING, {session_reference_of(hosted): {
        "job": "j", "version": 1, "connection": "c", "profile": 1, "expires": "2000-01-01T00:00:00+00:00"}})
    assert "Kein offener Google-Vorgang" in hosted.browser.request("GET", "/google/kalender").body.decode()


def session_reference_of(web):
    from types import SimpleNamespace
    return session_reference(SimpleNamespace(id=session_of(web)))


def test_the_previous_access_of_another_binding_is_released_after_adoption(hosted, central):
    hosted.profiles.connections[1] = "e" * 32  # e.g. bound to the setup draft before config.yaml existed
    returned = connect(hosted)
    hosted.browser.request("POST", "/einrichtung/google/abschluss",
                           fields(returned.body.decode(), "/einrichtung/google/abschluss"))
    form = fields(hosted.browser.request("GET", "/google/kalender").body.decode(), "/google/kalender")
    assert hosted.browser.request("POST", "/google/kalender",
                                  {**form, "calendar": "familie@group.calendar.google.com"}).status == 303
    assert ("internal_refused", {"instance": "anna", "route": "/intern/disconnect",
                                 "reason": "unknown_connection"}) in central.events
    assert hosted.profiles.connections[1] != "e" * 32


def adopted(web, profile=1, code="good"):
    """A complete connection of *profile*; returns its central reference."""
    returned = connect(web, profile, code)
    web.browser.request("POST", "/einrichtung/google/abschluss",
                        fields(returned.body.decode(), "/einrichtung/google/abschluss"))
    form = fields(web.browser.request("GET", "/google/kalender").body.decode(), "/google/kalender")
    web.browser.request("POST", "/google/kalender", {**form, "calendar": "familie@group.calendar.google.com"})
    return web.profiles.connections[profile]


def test_another_calendar_of_the_existing_access_needs_no_new_google_sign_in(hosted, central):
    connection = adopted(hosted)
    offer = hosted.browser.request("GET", "/google/verbinden?profile=1").body.decode()
    assert 'href="/google/kalender/wechseln?profile=1"' in offer
    jobs = len(central.service.state.read().jobs)
    central.calendars = [{"id": "familie", "summary": "Familie", "accessRole": "writer"},
                         {"id": "arbeit", "summary": "Arbeit", "accessRole": "owner"}]
    page = hosted.browser.request("GET", "/google/kalender/wechseln?profile=1").body.decode()
    assert "Arbeit" in page and "neue Bestätigung" in page
    form = fields(page, "/google/kalender/wechseln")
    assert hosted.browser.request("POST", "/google/kalender/wechseln", {**form, "calendar": "fremd"}).status == 409
    changed = hosted.browser.request("POST", "/google/kalender/wechseln", {**form, "calendar": "arbeit"})
    assert changed.status == 303 and changed.headers["Location"] == "/einrichtung"
    assert hosted.profiles.saved[-1][2] == {"google_calendar": "arbeit"}
    assert hosted.profiles.connections[1] == connection and len(central.service.state.read().jobs) == jobs
    # The form of the old version is stale now.
    assert hosted.browser.request("POST", "/google/kalender/wechseln", {**form, "calendar": "familie"}).status == 409


def test_choosing_another_calendar_fails_safely(hosted, central):
    csrf = hosted.auth.csrf_token(session_of(hosted))
    assert hosted.browser.request("GET", "/google/kalender/wechseln?profile=1").status == 404  # no connection yet
    assert hosted.browser.request("GET", "/google/kalender/wechseln?profile=100").status == 503
    adopted(hosted)
    form = fields(hosted.browser.request("GET", "/google/kalender/wechseln?profile=1").body.decode(),
                  "/google/kalender/wechseln")
    central.down = True
    assert hosted.browser.request("GET", "/google/kalender/wechseln?profile=1").status == 503
    assert hosted.browser.request("POST", "/google/kalender/wechseln", {**form, "calendar": "x"}).status == 503
    central.down = False
    assert hosted.browser.request("POST", "/google/kalender/wechseln", {"csrf": csrf, "profile": "1"}).status == 409
    hosted.hosted_state["client"] = None
    assert hosted.browser.request("GET", "/google/kalender/wechseln?profile=1").status == 503
    assert hosted.browser.request("POST", "/google/kalender/wechseln", {**form, "calendar": "x"}).status == 503
    assert len(hosted.profiles.saved) == 1  # only the first adoption


def test_disconnecting_stops_tokens_for_this_profile_only_and_keeps_the_reference(hosted, central):
    from mailhelp.external.contracts import OAuthTokenError
    from mailhelp.external.hosted_oauth import HostedTokenProvider
    first, second = adopted(hosted, 1), adopted(hosted, 2, code="second")
    provider = HostedTokenProvider(hosted.hosted_state["client"], first)
    assert provider.access_token()  # cached now
    offer = hosted.browser.request("GET", "/google/verbinden?profile=1").body.decode()
    assert "die Freigabe bei Google selbst wird nicht widerrufen" in offer
    form = fields(offer, "/google/trennen")
    answer = hosted.browser.request("POST", "/google/trennen", form)
    assert answer.status == 303 and answer.headers["Location"] == "/einrichtung"
    state = central.service.state.read()
    assert state.connections[first].status == "disconnected" and state.connections[second].status == "active"
    assert hosted.profiles.connections[1] == first  # the profile stays valid; the warning offers reconnecting
    with pytest.raises(OAuthTokenError):
        provider.access_token()
    assert hosted.browser.request("POST", "/google/trennen", form).status == 303  # a repeat changes nothing
    assert central.service.state.read().connections[second].status == "active"


def test_disconnecting_refuses_stale_forms_and_keeps_the_access_during_outages(hosted, central):
    connection = adopted(hosted)
    form = fields(hosted.browser.request("GET", "/google/verbinden?profile=1").body.decode(), "/google/trennen")
    for changed in ({"version": "99"}, {"key": ""}, {"profile": "2"}, {"profile": "x"}):
        assert hosted.browser.request("POST", "/google/trennen", {**form, **changed}).status == 409
    central.down = True
    assert hosted.browser.request("POST", "/google/trennen", form).status == 503
    central.down = False
    hosted.profiles.connections[1] = "e" * 32  # unknown to the service
    assert hosted.browser.request("POST", "/google/trennen", form).status == 409
    hosted.profiles.connections[1] = connection
    hosted.hosted_state["client"] = None
    assert hosted.browser.request("POST", "/google/trennen", form).status == 503
    assert central.service.state.read().connections[connection].status == "active"


def test_only_a_google_address_is_followed(hosted):
    hosted.hosted_state["client"] = type("Client", (), {"post": lambda self, path, data: {
        "url": "https://evil.example/login"}})()
    csrf = hosted.auth.csrf_token(session_of(hosted))
    assert hosted.browser.request("POST", "/google/verbinden", {"csrf": csrf, "profile": "1",
                                                                "key": "k" * 32}).status == 502


def test_a_profile_unknown_to_the_service_is_refused(hosted, monkeypatch):
    returned = connect(hosted)
    # The profile was removed meanwhile: no configured profile has the binding the service reports.
    monkeypatch.setattr(hosted.hosted_site, "target", lambda profile: (_ for _ in ()).throw(LookupError(profile))
                        if profile > 1 else "profile:9")
    form = fields(returned.body.decode(), "/einrichtung/google/abschluss")
    assert hosted.browser.request("POST", "/einrichtung/google/abschluss", form).status == 409
