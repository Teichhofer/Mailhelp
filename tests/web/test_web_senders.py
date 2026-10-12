"""Ignored senders in the web interface (1.4): one click, reversible, main thread only."""
from __future__ import annotations

import pytest
import yaml
from shared_application import settings
from shared_web_actions import MAIL1, web  # noqa: F401  (fixture)
from web_scenario import mail_id, save_mail

from mailhelp.config import Topic
from mailhelp.configuration import AdminCommand, AdminKind, ConfigurationService, SenderChange
from mailhelp.imap import FetchedMail
from mailhelp.models import IrrelevantSenders
from mailhelp.orchestrator import Orchestrator
from mailhelp.review.results import ResultStatus
from mailhelp.sender_filter import change_irrelevant_senders, sender_entry
from mailhelp.storage import JsonStore
from mailhelp.web.sender_site import LIST_PATH

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
    assert web.browser.request("POST", LIST_PATH, {"key": "e" * 32, "eintrag": "x@y.de"}).status == 403
    web.browser.cookies.clear()
    response = web.browser.request("POST", f"/mail/{MAIL1}/absender-ignorieren", fields)
    assert response.status == 403
    web.run()
    assert blocked(senders).addresses == []


def test_domain_blocks_and_mails_without_a_usable_address(web, senders):
    senders.save("irrelevant-senders", IrrelevantSenders(domains=["schule.test"]).model_dump(mode="json"))
    page = web.browser.request("GET", f"/mail/{MAIL1}").body.decode()
    assert '<span class="badge danger">Domain wird ignoriert</span>' in page
    assert f'<a href="{LIST_PATH}">Liste verwalten</a>' in page
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


def test_the_list_page_adds_normalized_entries_and_removes_them(web, senders):
    page = web.browser.request("GET", LIST_PATH).body.decode()
    assert "Derzeit wird kein Absender ignoriert." in page
    settings_page = web.browser.request("GET", "/einstellungen").body.decode()
    assert f'href="{LIST_PATH}">Ignorierte Absender</a>' in settings_page
    for entry in ("Newsletter <News@Shop.EXAMPLE>", "Werbung.Example.COM."):
        fields = {**web.form(LIST_PATH, action=LIST_PATH), "eintrag": entry}
        location, page = finish(web, web.browser.request("POST", LIST_PATH, fields))
        assert location.startswith(f"{LIST_PATH}?ergebnis=")
    assert blocked(senders) == IrrelevantSenders(addresses=["news@shop.example"],
                                                 domains=["werbung.example.com"])
    assert "„werbung.example.com“ wird ab sofort ignoriert" in page
    assert "Liste (2)" in page and '<span class="badge accent">Domain</span>' in page
    fields = web.form(LIST_PATH, action=f"{LIST_PATH}/entfernen", eintrag="news@shop.example")
    _, page = finish(web, web.browser.request("POST", f"{LIST_PATH}/entfernen", fields))
    assert blocked(senders).addresses == [] and "Liste (1)" in page
    for entry in ("a@x.de, b@x.de", "kein domain", ""):
        fields = {**web.form(LIST_PATH, action=LIST_PATH), "eintrag": entry}
        response = web.browser.request("POST", LIST_PATH, fields)
        assert response.status == 422 and "gültige E-Mail-Adresse oder Domain" in response.body.decode()


def test_without_the_configuration_service_nothing_is_offered(web):
    assert web.site.archive.configuration is None
    assert "Absender ignorieren" not in web.browser.request("GET", f"/mail/{MAIL1}").body.decode()
    fields = {"csrf": csrf(web), "key": "a" * 32, "eintrag": "x@y.de"}
    for path in (f"/mail/{MAIL1}/absender-ignorieren", LIST_PATH, f"{LIST_PATH}/entfernen"):
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
                                         "reason": "Absender-Vorfilter"}
