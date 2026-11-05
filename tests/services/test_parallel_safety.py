"""P1–P7: actual web/Telegram adapters, forced order and persistent state assertions."""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from mailhelp.models import Proposal
from mailhelp.review.inbox import FINISHED
from mailhelp.telegram.callbacks import Decision, DecisionAction
from mailhelp.telegram.receiver import TelegramInbox
from tests.fakes.safety_harness import Gate, PersistentWriter
from tests.fakes.shared_telegram_dialog import callback
from tests.fakes.shared_web_auth import Browser, code_from
from tests.scenarios.web_scenario import mail_id, proposal, save_mail

MAIL = mail_id(1)
EDIT_PATH = f"/vorschlag/{MAIL}/formular/bearbeiten"


def pair_browser(web):
    browser, messages = Browser(web.app), []
    web.auth.notify = messages.append
    csrf = browser.csrf()
    browser.request("POST", "/anmelden/code", {"csrf": csrf})
    browser.request("POST", "/anmelden", {"csrf": csrf, "code": code_from(messages)})
    return browser


def inspect(web, provider):
    """Check all independent records, including the user's durable result."""
    entries = web.commands._entries()
    assert entries and all(entry.status in FINISHED and entry.result.message for entry in entries)
    assert all(entry.finished_at is not None for entry in entries)
    ledger = [entry for entry in web.store.load("action-ledger", {"entries": []})["entries"]
              if entry["mail_id"] == MAIL and entry["proposal_id"] == "formular"]
    calls = [c for c in provider.state()["calls"] if c[0] == "create"]
    assert len(calls) <= 1 and len(ledger) == len(calls)
    item = web.dialog.repository.load_current(MAIL, "formular")
    projection = web.dialog.repository.load_mail(MAIL)
    assert next(p for p in projection.proposals if p.id == item.id) == item
    assert all(web.store.load(name)["status"] == "completed"
               for name in web.store.names("reconciliation-merge-"))
    if calls:
        assert item.status == "created" and item.version == 1 and item.external_id
        assert len(projection.write_attempts) == 1
    return item, entries


@pytest.fixture
def provider(web, tmp_path):
    writer = PersistentWriter(tmp_path / "provider.json")
    web.dialog.write_executor.writers["todoist"] = writer
    web.dialog.inbox = TelegramInbox(web.store)
    return writer


@pytest.mark.parametrize("first", ["web", "telegram"])
def test_p1_two_channels_confirm_same_version(web, provider, first):
    fields = web.form("/", kind="confirm", proposal_id="formular")
    token = Decision(mail_id=MAIL, proposal_id="formular", version=1, action=DecisionAction.CONFIRM).encode(web.store)
    gate = Gate()
    provider.checkpoint = lambda point: gate.hold() if point == "A2" else None
    def telegram(): web.dialog.inbox.add([callback(1, token)], set())
    def browser(): return web.submit(fields)
    browser()
    if first == "telegram":
        telegram()
    with gate.during(web.run):
        if first == "web":
            telegram()
        else:
            assert len(web.commands.queued()) == 1
    provider.checkpoint = lambda point: None
    web.run()
    item, _ = inspect(web, provider)
    assert item.status == "created"
    if first == "web":
        assert any("veraltet" in text.lower() or "anderen" in text.lower()
                   for _, text, _ in web.telegram.sent)


@pytest.mark.parametrize("reverse", [False, True])
def test_p2_two_sessions_distinct_keys_cannot_bypass_business_idempotency(web, provider, reverse):
    other = pair_browser(web)
    first = web.form("/", kind="confirm", proposal_id="formular")
    second = {**first, "csrf": other.csrf("/"), "key": "b" * 32}
    requests = [(web.browser, first), (other, second)]
    if reverse:
        requests.reverse()
    for browser, fields in requests:
        assert browser.request("POST", "/aktion", fields).status == 303
    gate = Gate()
    provider.checkpoint = lambda point: gate.hold() if point == "A2" else None
    with gate.during(web.run):
        assert len(web.commands._entries()) == 2
        assert sum(e.status.value == "running" for e in web.commands._entries()) == 1
    item, entries = inspect(web, provider)
    assert item.status == "created"
    assert sorted(e.result.status.value for e in entries) == ["stale", "written"]


@pytest.mark.parametrize("first", ["change", "confirm"])
@pytest.mark.parametrize("kind", ["edit", "reject", "merge"])
def test_p3_p4_p5_decision_orders(web, provider, first, kind):
    other = pair_browser(web)
    confirmation = web.form("/", kind="confirm", proposal_id="formular")
    confirmation["csrf"] = other.csrf("/")
    if kind == "edit":
        fields = web.form(EDIT_PATH, action=EDIT_PATH)
        fields["title"] = "Manuell bearbeitet"
        path = EDIT_PATH
    elif kind == "reject":
        fields, path = web.form("/", kind="reject", proposal_id="formular"), "/aktion"
    else:
        # Distinct source with compatible type/target, explicitly chosen by the person.
        source = proposal(20, "source", title="Zusätzliche Unterlagen",
                          matching_candidates=[{"mail_id": MAIL, "proposal_id": "formular"}],
                          status="needs_clarification", open_questions=["Zuordnung prüfen."])
        save_mail(web.store, 20, "source@example.test", "Zusatz", [source])
        fields = web.form("/abgleich", action="/abgleich", kind="merge_proposals",
                          proposal_id="source", target_proposal_id="formular")
        path = "/abgleich"
    actions = [(web.browser, path, fields), (other, "/aktion", confirmation)]
    if first == "confirm":
        actions.reverse()
    # Both requests are accepted while the referenced version is still open.
    for browser, endpoint, form in actions:
        assert browser.request("POST", endpoint, form).status == 303
    gate, execute = Gate(), web.dialog.review.execute
    calls = []
    def held(command, **kwargs):
        result = execute(command, **kwargs)
        if not calls:
            calls.append(result)
            gate.hold()
        return result
    web.dialog.review.execute = held
    with gate.during(web.run):
        running = web.commands._entries()[0]
        assert running.status.value == "running"
        if first == "change":
            assert not [c for c in provider.state()["calls"] if c[0] == "create"]
    item, entries = inspect(web, provider)
    if first == "confirm":
        assert item.status == "created" and entries[1].result.status.value in {"stale", "invalid"}
    else:
        assert item.status == ("rejected" if kind == "reject" else "pending_confirmation")
        assert item.version == (1 if kind == "reject" else 2)
        assert entries[1].result.status.value == "stale"
        if kind == "edit":
            assert item.title == "Manuell bearbeitet"
        if kind == "merge":
            alias = web.dialog.repository.load_current(mail_id(20), "source")
            assert alias.status == "merged" and alias.canonical_ref.proposal_id == item.id


@pytest.mark.parametrize("expiry", [False, True])
def test_p6_waiting_command_loses_revoked_or_expired_session(web, provider, expiry):
    fields = web.form("/", kind="confirm", proposal_id="formular")
    web.submit(fields)
    gate, execute = Gate(), web.dialog.review.execute
    def held(command, **kwargs):
        gate.hold()
        return execute(command, **kwargs)
    web.dialog.review.execute = held
    with gate.during(web.run):
        if expiry:
            now = web.auth.clock()
            web.auth.clock = lambda: now + timedelta(days=31)
        else:
            web.auth.revoke_all()
    item, entries = inspect(web, provider)
    assert item.status == "pending_confirmation"
    assert entries[0].result.status.value == "unauthorized"


def test_p7_same_request_while_running_and_after_completion_returns_same_result(web, provider):
    fields = web.form("/", kind="confirm", proposal_id="formular")
    response = web.submit(fields, accept="application/json")
    identifier = json.loads(response.body)["id"]
    gate = Gate()
    provider.checkpoint = lambda point: gate.hold() if point == "A2" else None
    with gate.during(web.run):
        repeat = web.submit(fields, accept="application/json")
        assert repeat.status == 202 and json.loads(repeat.body)["id"] == identifier
        assert json.loads(repeat.body)["status"] == "running"
    again = web.submit(fields, accept="application/json")
    assert again.status == 202 and json.loads(again.body) == {
        "id": identifier, "status": "done", "status_url": f"/aktion/{identifier}"}
    item, entries = inspect(web, provider)
    assert item.status == "created" and len(entries) == 1


@pytest.mark.parametrize("first", ["merge", "confirm"])
def test_p5_confirmation_of_merge_source_obeys_both_orders(web, provider, first):
    target = proposal(20, "target", title="Kanonische Unterlagen")
    save_mail(web.store, 20, "source@example.test", "Zusatz", [target])
    other = pair_browser(web)
    confirmation = web.form("/", kind="confirm", proposal_id="formular")
    confirmation["csrf"] = other.csrf("/")
    # An explicit, authenticated association of both displayed versions.
    merge = {"csrf": web.browser.csrf("/"), "key": "source-merge-race",
             "kind": "merge_proposals", "mail_id": MAIL, "proposal_id": "formular", "version": "1",
             "target_mail_id": target.source_mail_id, "target_proposal_id": target.id, "target_version": "1"}
    actions = [(web.browser, "/abgleich", merge), (other, "/aktion", confirmation)]
    if first == "confirm":
        actions.reverse()
    for browser, endpoint, fields in actions:
        assert browser.request("POST", endpoint, fields).status == 303
    gate, execute = Gate(), web.dialog.review.execute
    started = []
    def held(command, **kwargs):
        result = execute(command, **kwargs)
        if not started:
            started.append(command)
            gate.hold()
        return result
    web.dialog.review.execute = held
    with gate.during(web.run):
        assert web.commands._entries()[0].status.value == "running"
    item, entries = inspect(web, provider)
    canonical = web.dialog.repository.load_current(target.source_mail_id, target.id)
    if first == "merge":
        assert item.status == "merged" and item.version == canonical.version == 2
        assert item.canonical_ref.proposal_id == canonical.id and len(canonical.sources) == 2
        assert entries[1].result.status.value == "stale"
    else:
        assert item.status == "created" and canonical == target
        assert entries[1].result.status.value == "invalid"


@pytest.mark.parametrize("scenario", ["P1", "P2", "P3", "P4", "P5", "P6", "P7"])
@pytest.mark.parametrize("csrf", ["valid", "missing", "wrong", "foreign"])
def test_p_scenarios_require_session_bound_csrf_at_web_entry(web, provider, scenario, csrf):
    other = pair_browser(web)
    kind = "reject" if scenario == "P4" else "confirm"
    path = "/aktion"
    fields = web.form("/", kind=kind, proposal_id="formular")
    if scenario == "P3":
        path = EDIT_PATH
        fields = {**web.form(path, action=path), "title": "Geändert"}
    if scenario == "P5":
        source = proposal(20, "source", matching_candidates=[{"mail_id": MAIL, "proposal_id": "formular"}],
                          status="needs_clarification", open_questions=["Zuordnung prüfen."])
        save_mail(web.store, 20, "source@example.test", "Zusatz", [source])
        path = "/abgleich"
        fields = web.form(path, action=path, kind="merge_proposals", proposal_id="source",
                          target_proposal_id="formular")
    if csrf == "missing":
        fields.pop("csrf")
    elif csrf == "wrong":
        fields["csrf"] = "wrong"
    elif csrf == "foreign":
        fields["csrf"] = other.csrf("/")
    before = web.store.load(f"proposal-{MAIL}-formular")
    response = web.browser.request("POST", path, fields)
    assert response.status == (303 if csrf == "valid" else 403)
    if csrf != "valid":
        assert web.commands._entries() == []
        assert web.store.load(f"proposal-{MAIL}-formular") == before
        assert provider.state()["calls"] == []
