"""8.7.4: learning in points for customer sessions (Plan Lernen in Punkten §4, §5).

Synthetic mailbox, synthetic provider and synthetic sessions only. Customers see points, never money,
tokens, models or operator links; the server alone turns the points limit into the run's USD limit.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace as NS
from urllib.parse import urlencode

import pytest

from mailhelp.config import read_yaml
from mailhelp.runtime import learning_jobs
from mailhelp.runtime.learning_jobs import POINTS, LearningConflict, LearningJob, _changed
from mailhelp.runtime.learning_worker import LearningPaused
from mailhelp.usage.valuations import SCOPE, UsageMeter, usage_scope
from mailhelp.web.learning_pages import cost_hint
from tests.fakes.customer_mode import session_of, signed_in
from tests.fakes.learning_harness import learning  # noqa: F401  (fixture)
from tests.fakes.rule_learning import RuleHarness, record

FORBIDDEN = ("USD", "EUR", "€", "Cent", "usd_", "Tokens", "Kosten", "kostenpflicht", "prompts.yaml",
             "/dienst/neu-laden", "budget", "price", "Preis")
START = datetime(2020, 1, 1, tzinfo=UTC)


class Customer:
    """The learning harness in customer mode with a priced, valued instance."""

    def __init__(self, h):
        self.h = h
        h.auth.enter_customer_mode("kunde")
        web = NS(app=h.web, store=h.store, auth=h.auth)
        self.browser = signed_in(web)
        self.session = session_of(web, self.browser)
        self.operator = signed_in(web, "operator", "Support")
        self.operator_session = session_of(web, self.operator)
        h.site.usage.meter = self.meter = UsageMeter(h.directory / "usage")
        self.meter.valuations.add(Decimal(1), Decimal(900), "operator", START)
        h.site.learning_price = Decimal("0.5")
        h.configuration.restricted = lambda actor: not h.auth.is_operator(actor.removeprefix("web:"))
        self.activated = []
        h.configuration.activate_topics = self.activated.append
        self.sequence = 0

    @property
    def actor(self):
        return "web:" + self.session.id

    def page(self, query="", browser=None):
        response = (browser or self.browser).request("GET", "/lernen/postfach" + (("?" + query) if query else ""))
        assert response.status == 200
        return response.body.decode()

    def estimate(self, points="10000000", **extra):
        return self.page(urlencode(dict(mailbox=1, count=2, folders="INBOX", points=points, **extra)))

    def post(self, action, browser=None, session=None, **extra):
        self.sequence += 1
        session = session or self.session
        return (browser or self.browser).request("POST", "/lernen/postfach", {
            "csrf": self.h.auth.csrf_token(session.id), "action": action,
            "version": self.h.jobs.state().version, "key": f"customerkey{self.sequence:04d}", **extra})

    def selection(self, points="10000000", revision=1, **patch):
        return json.dumps({"mailbox": 1, "folders": ["INBOX"], "count": 2, "points": points,
                           "revision": revision} | patch)


@pytest.fixture
def customer(learning):  # noqa: F811
    return Customer(learning)


def money_free(page: str, models: set[str]) -> None:
    hits = [word for word in (*FORBIDDEN, *models) if word in page]
    assert hits == [], hits


def models_of(h) -> set[str]:
    return {route.model for stage in ("relevance", "learning_classification", "learning_abstraction")
            for route in h.app.analyzer.prompts.resolved_routes(stage)[0]}


def test_acceptance_14_customer_learning_pages_show_points_only(customer):
    h, models = customer.h, models_of(customer.h)
    form = customer.page()
    assert "Punktegrenze für diesen Lauf" in form and 'name="points"' in form
    money_free(form, models)
    page = customer.estimate()
    assert "Geschätzter Verbrauch: etwa 200,00 Punkte; ungünstigster Fall: höchstens" in page
    assert "Lesenden Lernlauf starten (verbraucht Punkte)" in page
    hidden = json.loads(re.search(r'name="selection" value="([^"]+)"', page).group(1).replace("&quot;", '"'))
    assert hidden == {"mailbox": 1, "folders": ["INBOX"], "count": 2, "points": "10000000", "revision": 1}
    money_free(page, models)
    for path in ("/lernen", "/api/lernen", "/api/lernen/uebersicht", "/lernen/vorschlaege"):
        response = customer.browser.request("GET", path)
        assert response.status == 200, path
        money_free(response.body.decode(), models)
    assert customer.post("start", selection=customer.selection()).status == 303
    running = customer.page()
    assert "Reserviert: 0,00 Punkte der Punktegrenze von 10.000.000,00 Punkte." in running
    assert "Tatsächlich verbraucht: 0,00 Punkte." in running
    money_free(running, models)
    assert h.store.load(POINTS) == {"schema_version": 1, "generation": 1, "points": "10000000", "revision": 1}


def test_a_too_low_points_limit_names_the_minimum_and_offers_no_start(customer):
    page = customer.estimate(points="200")
    assert "Bitte mindestens 201,00 Punkte angeben." in page and "Lernlauf starten" not in page
    assert "Lernlauf starten" in customer.estimate(points="201")
    assert "Angaben für die Schätzung prüfen." in customer.estimate(points="0")
    assert "Angaben für die Schätzung prüfen." in customer.page("mailbox=7&count=2&folders=INBOX&points=500")
    assert "Lernlauf starten" not in customer.page("mailbox=1&prepare=1")


def test_without_price_or_valuation_the_operator_has_not_set_it_up(customer):
    customer.h.site.learning_price = None
    page = customer.estimate()
    assert "vom Betreiber noch nicht eingerichtet" in page and 'name="points"' not in page
    response = customer.post("start", selection=customer.selection())
    assert response.status == 409 and "vom Betreiber noch nicht eingerichtet" in response.body.decode()
    customer.h.site.learning_price = Decimal("0.5")
    customer.h.site.usage.meter = None
    assert "vom Betreiber noch nicht eingerichtet" in customer.estimate()
    assert customer.h.jobs.state().status == "empty"


@pytest.mark.parametrize("patch", [
    {"budget_usd": 1000}, {"usd_per_million_tokens": 0.001}, {"points": 10000000}, {"revision": "1"},
    {"points": "0"}, {"points": "1e9"},
])
def test_injected_money_fields_and_malformed_limits_refuse_the_whole_start(customer, patch):
    response = customer.post("start", selection=customer.selection(**patch))
    assert response.status == 409 and "USD" not in response.body.decode()
    assert customer.h.jobs.state().status == "empty" and customer.h.store.load(POINTS) is None


def test_the_raw_json_is_refused_unless_it_is_an_object(customer):
    for raw in ("[1]", "broken"):
        assert customer.post("start", selection=raw).status == 409
    assert customer.h.jobs.state().status == "empty"


def test_a_new_valuation_between_estimate_and_start_refuses_the_start(customer):
    page = customer.estimate()
    assert '&quot;revision&quot;: 1' in page
    customer.meter.valuations.add(Decimal(2), Decimal(900), "operator", datetime(2021, 1, 1, tzinfo=UTC))
    response = customer.post("start", selection=customer.selection(revision=1))
    assert response.status == 409 and "Bewertung geändert, bitte Schätzung prüfen." in response.body.decode()
    assert customer.h.jobs.state().status == "empty"
    assert customer.post("start", selection=customer.selection(points="1000000", revision=2)).status == 303
    assert customer.h.jobs.state().selection.budget_usd == 200  # 1,000,000 points at 2 USD/EUR, factor 10
    # The running run keeps the revision it started with; a later change does not re-value it.
    customer.meter.valuations.add(Decimal(1), Decimal(900), "operator", datetime(2022, 1, 1, tzinfo=UTC))
    assert customer.h.store.load(POINTS)["revision"] == 2
    assert "der Punktegrenze von 1.000.000,00 Punkte" in customer.page()


def test_a_repeated_key_starts_once_and_an_ended_session_starts_nothing(customer):
    h = customer.h
    form = {"csrf": h.auth.csrf_token(customer.session.id), "action": "start", "version": 0,
            "key": "repeatedkey01", "selection": customer.selection()}
    assert customer.browser.request("POST", "/lernen/postfach", form).status == 303
    assert customer.browser.request("POST", "/lernen/postfach", form).status == 303
    assert h.jobs.state().generation == 1 and h.jobs.state().version == 1
    h.change("cancel", actor=customer.actor)
    h.auth.revoke(customer.session.id)
    response = customer.post("start", selection=customer.selection())
    assert response.status == 403 and h.jobs.state().status == "cancelled"


def test_the_run_stops_before_the_points_limit_and_shows_points(customer):
    h = customer.h
    assert customer.post("start", selection=customer.selection(points="201")).status == 303
    assert h.jobs.state().selection.budget_usd <= 0.0201
    h.client.policy.retries = 20  # each call reserves for every retry: the first one exceeds the limit
    seen = []
    h.client.before = lambda: seen.append(SCOPE.get())
    with pytest.raises(LearningPaused):
        while h.worker.tick():
            pass
    state = h.jobs.state()
    assert state.status == "paused" and state.message.startswith("Angehalten: Budget")
    page = customer.page()
    assert "Angehalten: Punktegrenze, Sitzung oder Konfiguration prüfen." in page and "Budget" not in page
    assert seen == []  # the first reservation already exceeds the limit: no call is sent
    h.jobs.recover()  # a restart keeps the bound limit
    assert "der Punktegrenze von 201,00 Punkte" in customer.page()


def test_actual_usage_counts_learning_calls_since_the_start_and_names_unclear_ones(customer):
    h, meter = customer.h, customer.meter
    meter.begin("before", "relevance")  # mail processing, not the run
    assert customer.post("start", selection=customer.selection()).status == 303
    with usage_scope("learning"):
        meter.begin("a:1", "relevance")
        meter.begin("b:1", "learning_abstraction")
    meter.settle("a:1", "0.01")
    meter.begin("c:1", "relevance")
    meter.settle("c:1", "0.5")
    page = customer.page()
    assert "Tatsächlich verbraucht: 100,00 Punkte. Bekannte Teilsumme; 1 Aufruf(e) noch nicht bewertbar." in page
    seen = []
    h.client.before = lambda: seen.append(SCOPE.get())
    while h.worker.tick() and not seen:
        pass
    assert seen and set(seen) == {"learning"}  # every learning call is recorded as learning usage


def test_customer_review_adoption_reloads_topics_without_operator_link(customer):
    h = customer.h
    assert customer.post("start", selection=customer.selection()).status == 303
    while h.worker.tick():
        pass
    review = customer.page()
    assert "Ergebnisse prüfen" in review
    money_free(review, models_of(h))
    assert customer.post("edit", index="0", kind="relevant", name="Camping",
                         description="Synthetic booking category").status == 303
    assert customer.post("folder", name="Archive", selected="on").status == 303
    assert customer.post("apply").status == 303
    done = customer.page()
    assert h.jobs.state().status == "done" and "/dienst/neu-laden" not in done
    assert "Neue Analysen übernehmen die Themen am nächsten sicheren Verarbeitungspunkt" in done
    assert customer.activated and customer.activated[-1][-1].name == "Camping"
    assert "Archive" in read_yaml(h.directory / "config.yaml")["imap"]["folders"]


def test_an_adoption_touching_operator_settings_is_refused_completely(customer, monkeypatch):
    h = customer.h
    assert customer.post("start", selection=customer.selection()).status == 303
    while h.worker.tick():
        pass
    before = h.jobs.hashes()
    customer.post("folder", name="Archive", selected="on")
    monkeypatch.setattr(learning_jobs, "customer_may_change", lambda name: name != "imap.folders")
    response = customer.post("apply")
    assert response.status == 409 and "nur der Betreiber" in response.body.decode()
    assert h.jobs.hashes() == before and h.jobs.state().status == "review" and customer.activated == []


def test_the_changed_settings_are_named_per_field_and_mailbox():
    boxes = {"imap": {"mailboxes": [{"id": 1, "folders": ["INBOX"]}, {"id": 2, "folders": ["INBOX"]}]}}
    changed = {"imap": {"mailboxes": [{"id": 1, "folders": ["INBOX"]}, {"id": 2, "folders": ["INBOX", "A"]}]}}
    assert _changed(boxes, changed) == {"imap.mailboxes.1.folders"}
    assert _changed({"a": [1]}, {"a": [1, 2]}) == {"a"} and _changed({"a": 1}, {"a": 1, "b": 2}) == {"b"}
    assert _changed({"a": {"x": 1}}, {"a": {"x": 1}}) == set()


def test_the_operator_keeps_the_usd_form_and_sees_points_in_addition(customer):
    h = customer.h
    page = customer.page(browser=customer.operator)
    assert "Preisobergrenze USD je Million Tokens" in page and 'name="points"' not in page
    query = urlencode(dict(mailbox=1, count=2, folders="INBOX", price=0.5, budget=1000))
    assert "kostenpflichtig starten" in customer.page(query, browser=customer.operator)
    h.store.save(POINTS, {"schema_version": 1, "generation": 1, "points": "5", "revision": 1})
    selection = dict(mailbox=1, folders=["INBOX"], count=2, budget_usd=1000, usd_per_million_tokens=0.5)
    response = customer.post("start", browser=customer.operator, session=customer.operator_session,
                             selection=json.dumps(selection))
    assert response.status == 303 and h.store.load(POINTS) is None  # a USD run never inherits a points limit
    running = customer.page(browser=customer.operator)
    assert "Reserviert: 0 Tokens, 0.000000 USD des gewählten Budgets." in running
    assert '<p class="meta">Reserviert: 0,00 Punkte. Tatsächlich verbraucht: 0,00 Punkte.</p>' in running
    assert "Reserviert: 0,00 Punkte." in customer.page()  # the customer sees the operator's run in points only


def test_a_customer_cannot_start_with_a_usd_selection_nor_the_operator_with_points(customer):
    usd = dict(mailbox=1, folders=["INBOX"], count=2, budget_usd=1000, usd_per_million_tokens=0.5)
    assert customer.post("start", selection=json.dumps(usd)).status == 409
    assert customer.post("start", browser=customer.operator, session=customer.operator_session,
                         selection=customer.selection()).status == 409
    assert customer.h.jobs.state().status == "empty"


def test_a_self_operated_instance_keeps_the_usd_page_and_its_state_format(learning):  # noqa: F811
    h = learning
    page = h.browser.request("GET", "/lernen/postfach").body.decode()
    assert "Preisobergrenze USD je Million Tokens" in page and "Punkte" not in page
    h.review()
    assert set(h.store.load("web-learning")) == set(LearningJob.model_fields) and h.store.load(POINTS) is None
    assert "Punkte" not in h.browser.request("GET", "/lernen/postfach").body.decode()


def test_the_overview_and_decision_learning_speak_of_points_for_customers(customer):
    h = customer.h
    rules = RuleHarness(h.directory, h.store, h.jobs.active)
    h.site.rule_learning.service = rules.service
    rules.log(record())
    overview = customer.browser.request("GET", "/lernen").body.decode()
    assert "Verbraucht Punkte" in overview and "Kostenpflichtig" not in overview
    page = customer.browser.request("GET", "/lernen/entscheidungen").body.decode()
    assert "Mehr Belege, mehr Punkte" in page and "Analyse ausdrücklich starten (verbraucht Punkte)" in page
    money_free(page, set())
    rules.service.change(customer.actor, 0, "analyze-points", "analyze", {"confirm": True})
    rules.service.tick()
    review = customer.browser.request("GET", "/lernen/entscheidungen").body.decode()
    assert "Neue Analyse vorbereiten (verbraucht Punkte)" in review
    operator = customer.operator.request("GET", "/lernen/entscheidungen").body.decode()
    assert "kostenpflichtige Analyse ausdrücklich starten" in operator and "höhere Kosten" in operator
    rules.analyzer.prompts.prompts.clear()
    missing = customer.browser.request("GET", "/lernen").body.decode()
    assert "Lernen aus Entscheidungen ist vom Betreiber noch nicht eingerichtet." in missing
    assert "decision_rule_learning" not in missing
    assert "fehlt der Schritt decision_rule_learning" in customer.operator.request("GET", "/lernen").body.decode()
    csrf = h.auth.csrf_token(customer.session.id)
    state = rules.service.state(customer.actor)
    queued = customer.browser.request("POST", "/lernen/entscheidungen", {
        "csrf": csrf, "action": "analyze", "version": state.version, "key": "analyze-again", "confirm": "yes",
        "scope": "all"})
    assert queued.status == 303
    rules.service.tick()
    failed = customer.browser.request("GET", "/lernen/entscheidungen").body.decode()
    assert "prompts.yaml" not in failed and "vom Betreiber noch nicht eingerichtet" in failed


def test_the_cost_hint_has_a_points_wording():
    assert "Verbraucht Punkte" in cost_hint(True) and "Kostenpflichtig" in cost_hint()


def test_a_conflict_text_is_shown_in_customer_words(customer, monkeypatch):
    h = customer.h

    def refuse(*_args, **_kwargs):
        raise LearningConflict("Budget reicht für den geschätzten Lauf nicht aus.")

    monkeypatch.setattr(h.jobs, "change", refuse)
    response = customer.post("start", selection=customer.selection())
    assert "Die Punktegrenze reicht für die Schätzung nicht aus." in response.body.decode()
    operator = customer.post("cancel", browser=customer.operator, session=customer.operator_session)
    assert "Budget reicht für den geschätzten Lauf nicht aus." in operator.body.decode()
