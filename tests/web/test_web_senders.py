"""Ignored senders in the web interface (1.4): one click, reversible, main thread only."""
from __future__ import annotations

import pytest
import yaml

from mailhelp.config import Topic
from mailhelp.config.configuration import AdminCommand, AdminKind, ConfigurationService, SenderChange
from mailhelp.domain.relevance import IrrelevantSenders
from mailhelp.mailbox.imap import FetchedMail
from mailhelp.mailbox.sender_filter import change_irrelevant_senders, sender_entry
from mailhelp.persistence.storage import JsonStore
from mailhelp.processing.orchestrator import Orchestrator
from mailhelp.review.results import ResultStatus
from mailhelp.web.sender_site import LIST_PATH
from tests.fakes.shared_application import settings
from tests.fakes.shared_web_actions import MAIL1, web  # noqa: F401  (fixture)
from tests.scenarios.web_scenario import mail_id, save_mail

SENDER = "klasse4b@schule.test"


@pytest.fixture
def senders(web, tmp_path):
    with JsonStore(tmp_path / "config") as store:
        service = ConfigurationService(tmp_path, web.store, settings(tmp_path),
                                       web.dialog.review.web_authorizer, lambda active: None,
                                       senders=store)
        web.site.archive.configuration = web.dialog.review.configuration = service
        (tmp_path / "config.yaml").write_text(yaml.safe_dump(service.active.model_dump(mode="json")),
                                              encoding="utf-8")
        yield store


def blocked(store) -> IrrelevantSenders:
    return store.load_model("irrelevant-senders", IrrelevantSenders, IrrelevantSenders())


def finish(web, response):
    """Run the queued command in the main thread and follow the result redirect."""
    assert response.status == 303 and response.headers["Location"].startswith("/aktion/")
    web.run()
    done = web.browser.request("GET", response.headers["Location"])
    assert done.status == 303
    return done.headers["Location"], web.browser.request("GET", done.headers["Location"]).body.decode()


def csrf(web) -> str:
    return web.auth.csrf_token(web.auth.sessions()[0].id)


def post(web, path, action, **match):
    return web.browser.request("POST", action, web.form(path, action=action, **match))


def test_ignoring_and_allowing_a_sender_from_the_mail_page(web, senders):
    page = web.browser.request("GET", f"/mail/{MAIL1}").body.decode()
    assert "🚫 Absender ignorieren" in page and f"Neue Mails von {SENDER} werden dann" in page
    location, page = finish(web, post(web, f"/mail/{MAIL1}", f"/mail/{MAIL1}/absender-ignorieren"))
    assert location.startswith(f"/mail/{MAIL1}?ergebnis=")
    assert f"„{SENDER}“ wird ab sofort ignoriert" in page
    assert '<span class="badge danger">Absender wird ignoriert</span>' in page
    assert "Absender wieder zulassen" in page and "🚫 Absender ignorieren" not in page
    assert blocked(senders).addresses == [SENDER]

    _, page = finish(web, post(web, f"/mail/{MAIL1}", f"/mail/{MAIL1}/absender-zulassen"))
    assert f"„{SENDER}“ wird künftig wieder normal verarbeitet." in page
    assert "🚫 Absender ignorieren" in page and blocked(senders).addresses == []


def test_ignoring_twice_keeps_one_entry(web, senders):
    # The second request comes from a page that still showed the old button.
    stale = web.form(f"/mail/{MAIL1}", action=f"/mail/{MAIL1}/absender-ignorieren")
    _, page = finish(web, post(web, f"/mail/{MAIL1}", f"/mail/{MAIL1}/absender-ignorieren"))
    assert "wird ab sofort ignoriert" in page
    _, page = finish(web, web.browser.request("POST", f"/mail/{MAIL1}/absender-ignorieren", stale))
    assert f"„{SENDER}“ wird bereits ignoriert." in page and blocked(senders).addresses == [SENDER]
    _, page = finish(web, post(web, f"/mail/{MAIL1}", f"/mail/{MAIL1}/absender-zulassen"))
    stale = {**stale, "key": "d" * 32}
    _, page = finish(web, web.browser.request("POST", f"/mail/{MAIL1}/absender-zulassen", stale))
    assert f"„{SENDER}“ stand nicht auf der Liste." in page


def test_sender_changes_need_a_session_and_the_csrf_token(web, senders):
    fields = web.form(f"/mail/{MAIL1}", action=f"/mail/{MAIL1}/absender-ignorieren")
    for changed in ({**fields, "csrf": "falsch"}, {"key": fields["key"]}):
        assert web.browser.request("POST", f"/mail/{MAIL1}/absender-ignorieren", changed).status == 403
    assert web.browser.request("POST", f"{LIST_PATH}/regel", {"key": "e" * 32, "wert": "x@y.de"}).status == 403
    web.browser.cookies.clear()
    response = web.browser.request("POST", f"/mail/{MAIL1}/absender-ignorieren", fields)
    assert response.status == 403
    web.run()
    assert blocked(senders).addresses == []


def test_domain_blocks_and_mails_without_a_usable_address(web, senders):
    senders.save("irrelevant-senders", IrrelevantSenders(domains=["schule.test"]).model_dump(mode="json"))
    page = web.browser.request("GET", f"/mail/{MAIL1}").body.decode()
    assert '<span class="badge danger">Domain wird ignoriert</span>' in page
    assert f'<a href="{LIST_PATH}">Regeln verwalten</a>' in page
    save_mail(web.store, 9, "—", "Ohne Absender", text="Text")
    page = web.browser.request("GET", f"/mail/{mail_id(9)}").body.decode()
    assert "Keine Absenderadresse erkennbar." in page
    fields = {"csrf": csrf(web), "key": "f" * 32}
    response = web.browser.request("POST", f"/mail/{mail_id(9)}/absender-ignorieren", fields)
    assert response.status == 422 and "keine gültige Absenderadresse" in response.body.decode()
    response = web.browser.request("POST", f"/mail/{'e' * 24}/absender-ignorieren", fields)
    assert response.status == 404
    response = web.browser.request("POST", f"/mail/{MAIL1}/absender-ignorieren", {**fields, "key": "kurz"})
    assert response.status == 422


def test_the_list_page_shows_the_simple_lists_and_removes_their_entries(web, senders):
    page = web.browser.request("GET", LIST_PATH).body.decode()
    assert "Derzeit wird kein Absender ignoriert." in page
    settings_page = web.browser.request("GET", "/einstellungen").body.decode()
    assert f'href="{LIST_PATH}"><strong>Absender-Regeln</strong>' in settings_page
    senders.save("irrelevant-senders", IrrelevantSenders(addresses=["news@shop.example"],
                                                         domains=["werbung.example.com"]).model_dump(mode="json"))
    page = web.browser.request("GET", LIST_PATH).body.decode()
    assert "Ignorierte Absender (2)" in page and '<span class="badge accent">Domain</span>' in page
    fields = web.form(LIST_PATH, action=f"{LIST_PATH}/entfernen", eintrag="news@shop.example")
    location, page = finish(web, web.browser.request("POST", f"{LIST_PATH}/entfernen", fields))
    assert location.startswith(f"{LIST_PATH}?ergebnis=")
    assert blocked(senders).addresses == [] and "Ignorierte Absender (1)" in page
    for entry in ("a@x.de, b@x.de", "kein domain", ""):
        fields = {**web.form(LIST_PATH, action=f"{LIST_PATH}/entfernen"), "eintrag": entry}
        response = web.browser.request("POST", f"{LIST_PATH}/entfernen", fields)
        assert response.status == 422 and "gültige E-Mail-Adresse oder Domain" in response.body.decode()


def test_without_the_configuration_service_nothing_is_offered(web):
    assert web.site.archive.configuration is None
    assert "Absender ignorieren" not in web.browser.request("GET", f"/mail/{MAIL1}").body.decode()
    fields = {"csrf": csrf(web), "key": "a" * 32, "eintrag": "x@y.de"}
    for path in (f"/mail/{MAIL1}/absender-ignorieren", f"/mail/{MAIL1}/absender-vip", f"{LIST_PATH}/entfernen",
                 f"{LIST_PATH}/regel"):
        assert web.browser.request("POST", path, fields).status == 503
    assert web.browser.request("GET", LIST_PATH).status == 503


def command(action="add", **patch):
    return AdminCommand(kind=AdminKind.SENDERS, actor="web:" + "a" * 16, idempotency_key="key-senders",
                        patch={"action": action, "addresses": [SENDER], **patch}, acknowledged=True)


def test_reconciling_a_sender_change_after_a_restart(tmp_path):
    with JsonStore(tmp_path / "state") as state, JsonStore(tmp_path / "config") as store:
        service = ConfigurationService(tmp_path, state, settings(tmp_path), lambda actor: True,
                                       lambda active: None, senders=store)
        assert service.reconcile(command()).status == ResultStatus.FAILED
        assert service.reconcile(command("remove")).status == ResultStatus.DONE
        assert service.execute(command()).status == ResultStatus.DONE
        assert service.reconcile(command()).status == ResultStatus.DONE
        assert service.reconcile(command(addresses=[])).status == ResultStatus.FAILED
        unavailable = ConfigurationService(tmp_path, state, settings(tmp_path), lambda actor: True,
                                           lambda active: None)
        assert unavailable.reconcile(command()).status == ResultStatus.FAILED
        assert unavailable.execute(command()).status == ResultStatus.INVALID
        assert unavailable.blocked_senders() == IrrelevantSenders()
        assert service.execute(command(domains=["Nicht gültig"])).status == ResultStatus.INVALID


def test_commands_and_entries_are_validated():
    with pytest.raises(ValueError, match="Dateihash"):
        AdminCommand(kind=AdminKind.SETTINGS, actor="web:" + "a" * 16, idempotency_key="key-settings",
                     patch={})
    with pytest.raises(ValueError, match="Mindestens eine"):
        SenderChange(action="add")
    with pytest.raises(ValueError):
        SenderChange(action="add", addresses=["Gross@Example.com"])
    assert sender_entry("  Name <A@B.de> ") == ("address", "a@b.de")
    assert sender_entry("B.de.") == ("domain", "b.de")
    for value in ("a@b.de c@d.de", "<>", "-x-.de"):
        with pytest.raises(ValueError):
            sender_entry(value)
    current = IrrelevantSenders(addresses=["a@b.de"], domains=["c.de"])
    assert change_irrelevant_senders(current, True, ["a@b.de"], ["c.de"]) == current
    assert change_irrelevant_senders(current, False, ["a@b.de"], []) == IrrelevantSenders(domains=["c.de"])


class NoLlm:
    def relevance(self, mail, topics):
        raise AssertionError("Ein ignorierter Absender darf keinen KI-Aufruf auslösen")


def test_the_next_mail_of_an_ignored_sender_is_sorted_out_without_llm(tmp_path):
    with JsonStore(tmp_path / "state") as state, JsonStore(tmp_path / "config") as store:
        service = ConfigurationService(tmp_path, state, settings(tmp_path), lambda actor: True,
                                       lambda active: None, senders=store)
        assert service.execute(command(mail_id=MAIL1)).status == ResultStatus.DONE
        orchestrator = Orchestrator(NoLlm(), state, object(), 1,
                                    [Topic(id="x", name="X", enabled=True, description="X")], 10_000,
                                    sender_store=store)
        raw = (f"From: Klassenleitung <{SENDER.upper()}>\nSubject: Neu\n"
               "Message-ID: <neu@schule.test>\n\nText").encode()
        result = orchestrator.process(FetchedMail("INBOX", 1, 50, raw))
    assert result.state["relevance"] == {"decision": "irrelevant", "topic_ids": [],
                                         "reason": "Vorfilter: klasse4b@schule.test"}


# --- 7.7.3: rules ---------------------------------------------------------------------------------

def rules(store):
    return blocked(store).rules


def save_form(web, query):
    """The preview of a rule; its page carries the form that saves exactly this rule."""
    page = web.browser.request("GET", f"{LIST_PATH}?{query}&vorschau=1").body.decode()
    return page, web.form(f"{LIST_PATH}?{query}&vorschau=1", action=f"{LIST_PATH}/regel")


def test_the_old_address_leads_to_the_rules_page(web, senders):
    response = web.browser.request("GET", "/einstellungen/ignorierte-absender")
    assert response.status == 303 and response.headers["Location"] == LIST_PATH


def test_a_rule_is_previewed_saved_once_changed_switched_and_removed(web, senders):
    save_mail(web.store, 20, "Bank <no-reply@bank.test>", "Kontoauszug", text="x")
    page, fields = save_form(web, "art=pattern&wert=No-Reply@*&aktion=ignore&notiz=Bankpost")
    assert "Diese Regel würde 1 der letzten" in page
    location, page = finish(web, web.browser.request("POST", f"{LIST_PATH}/regel", fields))
    assert location.startswith(f"{LIST_PATH}?ergebnis=") and "„no-reply@*“ wird künftig ohne KI-Aufruf aussortiert." in page
    [rule] = rules(senders)
    assert (rule.kind, rule.value, rule.note, rule.origin) == ("pattern", "no-reply@*", "Bankpost", "manual")
    assert "Ignorierte Absender (1)" in page and "Treffer: 0 · zuletzt: nie" in page and "Bankpost" in page
    # The same rule again changes nothing; the version check refuses a form from before the change.
    _, fields = save_form(web, "art=pattern&wert=no-reply@*&aktion=ignore")
    _, page = finish(web, web.browser.request("POST", f"{LIST_PATH}/regel", fields))
    assert "Diese Regel gibt es bereits." in page
    _, stale = save_form(web, "art=pattern&wert=no-reply@*&aktion=vip")
    web.store.save("prefilter-hits", {"schema_version": 1, "rules": {rule.id: {"count": 3, "last": "2026-11-17T10:00:00+00:00"}},
                                      "trial": {}})
    _, fields = save_form(web, "art=pattern&wert=no-reply@*&aktion=allow_only")
    _, page = finish(web, web.browser.request("POST", f"{LIST_PATH}/regel", fields))
    assert "Regel für „no-reply@*“ geändert." in page and "Ausnahmen (1)" in page and "Treffer: 3 · zuletzt: 17.11.2026" in page
    _, page = finish(web, web.browser.request("POST", f"{LIST_PATH}/regel", stale))
    assert "Absenderfilter inzwischen geändert." in page and rules(senders)[0].action == "allow_only"
    for step, expected in (("disable", "Regel ausgeschaltet."), ("enable", "Regel eingeschaltet."),
                           ("entfernen", "Regel für „no-reply@*“ entfernt.")):
        fields = web.form(LIST_PATH, action=f"{LIST_PATH}/regel/{step}", regel=rule.id)
        _, page = finish(web, web.browser.request("POST", f"{LIST_PATH}/regel/{step}", fields))
        assert expected in page
    assert rules(senders) == []


def test_regression_the_preview_of_the_complete_form_is_shown(web, senders):
    """7.7.3: the browser sends all six fields; the result notice allowed five and failed."""
    query = "art=pattern&wert=no-reply%40*&aktion=ignore&postfach=&notiz=&vorschau=1"
    response = web.browser.request("GET", f"{LIST_PATH}?{query}")
    assert response.status == 200 and "Diese Regel würde" in response.body.decode()


def test_a_disabled_rule_is_marked_and_unusable_rules_are_refused(web, senders):
    _, fields = save_form(web, "art=subject&wert=Automatische Antwort:&aktion=ignore")
    finish(web, web.browser.request("POST", f"{LIST_PATH}/regel", fields))
    fields = web.form(LIST_PATH, action=f"{LIST_PATH}/regel/disable")
    _, page = finish(web, web.browser.request("POST", f"{LIST_PATH}/regel/disable", fields))
    assert '<span class="badge">aus</span>' in page and "Einschalten" in page
    page = web.browser.request("GET", f"{LIST_PATH}?art=pattern&wert=(a%2B)%2B@x&aktion=ignore&vorschau=1").body.decode()
    assert "Diese Regel ist ungültig." in page and "Regel speichern" not in page
    page = web.browser.request("GET", f"{LIST_PATH}?art=domain&wert=gmail.com&aktion=ignore&vorschau=1").body.decode()
    assert "großer Mailanbieter" in page
    bad = {"csrf": csrf(web), "key": "b" * 32, "art": "subject", "wert": "Angebot", "aktion": "vip"}
    _, page = finish(web, web.browser.request("POST", f"{LIST_PATH}/regel", bad))
    assert "Regel nicht geändert: ungültig oder nicht schreibbar." in page
    incomplete = {"csrf": csrf(web), "key": "c" * 32, "art": "address", "wert": " "}
    assert web.browser.request("POST", f"{LIST_PATH}/regel", incomplete).status == 422
    nothing = {"csrf": csrf(web), "key": "d" * 32, "regel": "0" * 16}
    _, page = finish(web, web.browser.request("POST", f"{LIST_PATH}/regel/entfernen", nothing))
    assert "Diese Regel gibt es nicht mehr." in page
    _, page = finish(web, web.browser.request("POST", f"{LIST_PATH}/regel/enable", {**nothing, "key": "e" * 32}))
    assert "Regel nicht geändert" in page


def test_an_exception_of_schema_2_becomes_a_vip_rule(web, senders):
    from mailhelp.domain.relevance import SenderRules
    senders.save("irrelevant-senders", IrrelevantSenders(mailboxes={"1": SenderRules(allow=[SENDER])})
                 .model_dump(mode="json"))
    page = web.browser.request("GET", LIST_PATH).body.decode()
    assert "Ausnahmen (1)" in page and "hebt nur die Sperre auf" in page
    fields = web.form(LIST_PATH, action=f"{LIST_PATH}/ausnahme-vip")
    _, page = finish(web, web.browser.request("POST", f"{LIST_PATH}/ausnahme-vip", fields))
    assert f"„{SENDER}“ gilt jetzt als VIP-Absender." in page and "VIP-Absender (1)" in page
    [rule] = rules(senders)
    assert (rule.action, rule.mailbox, rule.origin) == ("vip", 1, "migration")
    assert blocked(senders).mailboxes["1"].allow == []
    again = {**fields, "key": "f" * 32, "stand": ""}
    _, page = finish(web, web.browser.request("POST", f"{LIST_PATH}/ausnahme-vip", again))
    assert "Regel nicht geändert" in page


def test_the_mail_page_ignores_the_domain_or_makes_the_sender_a_vip(web, senders):
    page = web.browser.request("GET", f"/mail/{MAIL1}").body.decode()
    assert "🌐 Domain schule.test ignorieren" in page and "⭐ Als VIP einstufen" in page
    location, page = finish(web, post(web, f"/mail/{MAIL1}", f"/mail/{MAIL1}/absender-vip"))
    assert location.startswith(f"/mail/{MAIL1}?ergebnis=") and f"„{SENDER}“ gilt künftig ohne Relevanzprüfung" in page
    assert "⭐ VIP-Absender" in page and rules(senders)[0].origin == "mail"
    senders.save("irrelevant-senders", IrrelevantSenders().model_dump(mode="json"))
    _, page = finish(web, post(web, f"/mail/{MAIL1}", f"/mail/{MAIL1}/domain-ignorieren"))
    assert "Wird durch eine Regel ignoriert" in page and rules(senders)[0].value == "schule.test"
    save_mail(web.store, 21, "Freund <freund@gmail.com>", "Hallo", text="x")
    page = web.browser.request("GET", f"/mail/{mail_id(21)}").body.decode()
    assert "Domain gmail.com ignorieren" not in page and "⭐ Als VIP einstufen" in page
    fields = {"csrf": csrf(web), "key": "a" * 32}
    response = web.browser.request("POST", f"/mail/{mail_id(21)}/domain-ignorieren", fields)
    assert response.status == 422 and "nicht möglich" in response.body.decode()
    save_mail(web.store, 22, "a@x.test, b@y.test", "Zwei", text="x")
    assert web.browser.request("POST", f"/mail/{mail_id(22)}/absender-vip", fields).status == 422
    assert web.browser.request("POST", f"/mail/{'e' * 24}/absender-vip", fields).status == 404


def test_header_filters_are_switched_tried_and_lists_excepted(web, senders):
    page = web.browser.request("GET", LIST_PATH).body.decode()
    assert "Kopfzeilen-Vorfilter" in page and "Keine Verteiler-Ausnahmen." in page
    fields = {**web.form(LIST_PATH, action=f"{LIST_PATH}/kopfzeilen", filter="lists"), "modus": "trial"}
    _, page = finish(web, web.browser.request("POST", f"{LIST_PATH}/kopfzeilen", fields))
    assert "Newsletter und Verteiler: Probelauf." in page and blocked(senders).headers.lists == "trial"
    assert "Probelauf seit" in page and "0 Mails wären aussortiert worden" in page
    fields = {**web.form(LIST_PATH, action=f"{LIST_PATH}/verteiler/hinzufuegen"), "verteiler": "Eltern.Schule.test"}
    _, page = finish(web, web.browser.request("POST", f"{LIST_PATH}/verteiler/hinzufuegen", fields))
    assert "Verteiler &lt;eltern.schule.test&gt; wird nie vorgefiltert." in page
    assert blocked(senders).headers.list_exceptions == ["<eltern.schule.test>"]
    fields = web.form(LIST_PATH, action=f"{LIST_PATH}/verteiler/entfernen")
    _, page = finish(web, web.browser.request("POST", f"{LIST_PATH}/verteiler/entfernen", fields))
    assert "Ausnahme für Verteiler &lt;eltern.schule.test&gt; entfernt." in page
    fields = {**web.form(LIST_PATH, action=f"{LIST_PATH}/kopfzeilen", filter="automated"), "modus": "on"}
    _, page = finish(web, web.browser.request("POST", f"{LIST_PATH}/kopfzeilen", fields))
    assert "Automatische Systemmails: an." in page and blocked(senders).headers.automated == "on"
    wrong = {**web.form(LIST_PATH, action=f"{LIST_PATH}/kopfzeilen", filter="lists"), "modus": "immer"}
    assert web.browser.request("POST", f"{LIST_PATH}/kopfzeilen", wrong).status == 422
    empty = {**web.form(LIST_PATH, action=f"{LIST_PATH}/verteiler/hinzufuegen"), "verteiler": "<>"}
    _, page = finish(web, web.browser.request("POST", f"{LIST_PATH}/verteiler/hinzufuegen", empty))
    assert "Regel nicht geändert" in page
