"""4.4: lock-free admission answers, card results and acknowledgements in the overview."""
import json
from datetime import UTC, datetime

import mailhelp.review.incoming as incoming
from mailhelp.review.commands import CommandKind
from mailhelp.review.inbox import CommandEntry
from mailhelp.review.results import ResultStatus, ReviewResult
from mailhelp.storage import JsonStore
from mailhelp.web.auth import SESSIONS, WebAuth
from mailhelp.web.command_cards import CommandCards
from tests.fakes.series_fakes import batch, series
from tests.fakes.shared_web_actions import web as web
from tests.fakes.shared_web_auth import SECRET, Browser
from tests.fakes.web_routes import action_id, progress_link
from tests.scenarios.web_scenario import mail_id


def test_outdated_versions_are_refused_as_json_before_admission(web):
    later = web.form("/", kind="already_done", proposal_id="formular")
    web.submit(web.form("/", kind="reject", proposal_id="formular"))
    web.run()
    web.site.refresh_overview()
    response = web.submit(later, accept="application/json")
    body = json.loads(response.body)
    assert response.status == 409 and "inzwischen geändert" in body["error"]
    assert "current_version" in body and web.commands.queued() == []


def test_an_answered_relevance_question_is_refused_with_its_own_message(web):
    fields = web.form("/", kind="relevance", decision="irrelevant")
    state = web.store.load(f"mail-{mail_id(7)}")
    state["relevance_dialog"]["version"] = 2
    web.store.save(f"mail-{mail_id(7)}", state)
    web.site.refresh_overview()
    response = web.submit(fields)
    assert response.status == 409 and "Relevanzfrage ist bereits beantwortet" in response.body.decode()
    assert web.commands.queued() == []


def test_a_conflicting_intent_committed_concurrently_is_refused(web, monkeypatch):
    fields = web.form("/", kind="reject", proposal_id="elternabend")
    web.submit(fields)
    # Another browser commits between the lock-free precheck and the receipt.
    monkeypatch.setattr(web.commands, "existing", lambda command: None)
    response = web.submit({**fields, "kind": "already_done"})
    assert response.status == 422 and "anderen Angaben" in response.body.decode()
    assert len(web.commands.queued()) == 1


def test_a_full_disk_answers_503_and_the_same_attempt_can_be_resent(web, monkeypatch):
    fields = web.form("/", kind="reject", proposal_id="elternabend")
    real = incoming.atomic_json
    def full(path, *args, **kwargs):
        if path.parent.name == "receipts":
            raise OSError(28, "synthetic full disk")
        return real(path, *args, **kwargs)
    monkeypatch.setattr(incoming, "atomic_json", full)
    response = web.submit(fields)
    assert response.status == 503 and "nicht sicher gespeichert" in response.body.decode()
    assert web.commands.queued() == []
    monkeypatch.setattr(incoming, "atomic_json", real)
    assert web.submit(fields).status == 303 and len(web.commands.queued()) == 1


def test_failures_stay_on_the_card_until_acknowledged_by_any_paired_device(web):
    location = web.submit(web.form("/", kind="reject", proposal_id="elternabend")).headers["Location"]
    entry_id = action_id(location)
    acknowledge = f"/aktion/{entry_id}/gesehen"
    csrf = web.auth.csrf_token(web.auth.authenticate(web.browser.cookies["mh_session"]).id)
    assert web.browser.request("POST", acknowledge, {"csrf": csrf}).status == 404  # Still running.
    web.commands.finish(entry_id, ReviewResult(status=ResultStatus.STALE, message="Synthetisch veraltet"))
    for _ in range(2):  # Reloading never hides the failure.
        page = web.browser.request("GET", "/").body.decode()
        assert "Synthetisch veraltet" in page and "Zur Kenntnis genommen" in page
    assert web.browser.request("POST", acknowledge, {"csrf": "wrong"}).status == 403
    assert web.browser.request("POST", "/aktion/" + "0" * 32 + "/gesehen", {"csrf": csrf}).status == 404
    assert Browser(web.app).request("POST", acknowledge, {"csrf": csrf}).status in {401, 403}
    response = web.browser.request("POST", acknowledge, {"csrf": csrf})
    assert response.status == 303 and response.headers["Location"] == "/"
    assert web.commands.get(entry_id).acknowledged
    assert "Synthetisch veraltet" not in web.browser.request("GET", "/").body.decode()


def test_a_detected_earlier_creation_offers_the_version_bound_choice_on_the_card(web):
    location = web.submit(web.form("/", kind="confirm", proposal_id="elternabend")).headers["Location"]
    web.commands.finish(action_id(location), ReviewResult(
        status=ResultStatus.NEEDS_DUPLICATE_CONFIRMATION, message="Wurde schon einmal angelegt."))
    page = web.browser.request("GET", "/").body.decode()
    assert "Wurde schon einmal angelegt." in page
    assert "Erneut anlegen" in page and "Nicht erneut anlegen" in page
    choice = web.form("/", kind="confirm_duplicate", proposal_id="elternabend")
    assert choice["version"] == "1" and choice["key"]
    assert web.writer.created == 0


def test_a_running_local_action_page_names_no_external_target(web):
    location = web.submit(web.form("/", kind="reject", proposal_id="elternabend")).headers["Location"]
    page = web.browser.request("GET", progress_link(location)).body.decode()
    assert "Wird ausgeführt" in page and "Die Anlage im Ziel" not in page


def test_series_commands_appear_on_every_member_card_only():
    items = series()
    entry = CommandEntry(id="d" * 32, command=batch(CommandKind.SERIES_CONFIRM, items[:2]),
                         received_at=datetime(2026, 11, 7, tzinfo=UTC))
    cards = CommandCards([entry], "csrf", "/")
    source = items[0].source_mail_id
    assert cards.matching(source, "p0") == [entry] == cards.matching(source, "p1")
    assert cards.matching(source, "p2") == [] and cards.matching("f" * 24, "p0") == []


def test_damaged_input_is_reported_in_the_operator_log_without_its_content(web):
    location = web.submit(web.form("/", kind="reject", proposal_id="elternabend")).headers["Location"]
    receipt = web.store.directory / "commands/receipts" / f"{action_id(location)}.json"
    incoming_copy = next((web.store.directory / "commands/incoming").glob("*.json"))
    incoming_copy.unlink()
    receipt.write_text("secret damaged payload", encoding="utf-8")
    web.run()
    events = [(key, fields) for key, fields in web.dialog.logger.events if key[2] == "command_input_damaged"]
    assert len(events) == 1 and events[0][0][0] == "ERROR"
    assert "secret" not in str(events) and web.commands.incoming.problems == []


def test_session_snapshot_ignores_damaged_state_and_follows_deletion(tmp_path):
    with JsonStore(tmp_path) as store:
        (tmp_path / f"{SESSIONS}.json").write_text("{damaged", encoding="utf-8")
        auth = WebAuth(store, SECRET, 30, lambda message: None)
        assert auth._session_snapshot == () and auth.authenticate_fast("token") is None
        token = auth._new_session("synthetic-agent")
        assert auth.authenticate_fast(token) is not None
        store.save(SESSIONS, {"sessions": "not a list"})
        assert auth.authenticate_fast(token) is None
        store.delete(SESSIONS)
        assert auth._session_snapshot == () and auth.authenticate_fast(token) is None


def test_reload_fallback_targets_the_page_without_the_card_fragment(web):
    """Regression: a refresh to the redirect URL with its #card anchor never reloaded."""
    location = web.submit(web.form("/", kind="reject", proposal_id="elternabend")).headers["Location"]
    assert "#v-" in location
    overview = web.browser.request("GET", location).body.decode()
    target = location.split("#", 1)[0].replace("&", "&amp;")
    assert f'<meta http-equiv="refresh" content="1; url={target}">' in overview
    detail = web.browser.request("GET", f"/vorschlag/{mail_id(1)}/elternabend").body.decode()
    assert f'<meta http-equiv="refresh" content="1; url=/vorschlag/{mail_id(1)}/elternabend">' in detail
    assert 'content="1"' not in overview + detail


def test_a_series_group_opens_while_a_member_shows_an_action(web):
    """Regression: without JavaScript the member's result was hidden in a closed group."""
    items = series()
    for item in items:
        web.dialog.persist(item)
    web.site.refresh_overview()
    assert '<details class="series-group">' in web.browser.request("GET", "/").body.decode()
    fields = web.form("/", kind="already_done", proposal_id="p0", mail_id=items[0].source_mail_id)
    location = web.submit(fields).headers["Location"]
    assert '<details class="series-group" open>' in web.browser.request("GET", location).body.decode()
    web.run()
    finished = web.browser.request("GET", "/").body.decode()
    # The closed member leaves the group; its result stays visible as "Deine Aktion".
    assert "Deine Aktion" in finished and "Als schon erledigt erfasst" in finished
    assert '<details class="series-group">' in finished
