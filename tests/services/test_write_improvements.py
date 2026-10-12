"""Regression tests for authorization and exact, complete external reconciliation."""
import types

import httpx
import pytest

from mailhelp.analysis import ContradictoryRevision, validate_revision_successor
from mailhelp.integrations import HttpWriter
from mailhelp.models import CalendarDuplicateDecision, ProposalRevisionDelta, apply_proposal_revision
from mailhelp.storage import JsonStore
from mailhelp.telegram import Decision, DecisionAction
from test_core import proposal
from test_telegram_dialog import callback, controller, message


def event(**changes):
    changes.setdefault("target", "calendar")
    return proposal(kind="event", start="2026-05-10T10:00:00+00:00",
                    end="2026-05-10T11:00:00+00:00", **changes)


@pytest.mark.parametrize("description", [
    "mailhelp:mail:p1:v10", "[mailhelp:mail:p1:v10]", "[mailhelp:mail:p1:v1-extra]",
    "mailhelp:mail:p1:v1", "[prefix-mailhelp:mail:p1:v1]",
])
def test_todoist_reconciliation_requires_complete_marker(description):
    writer = HttpWriter("todoist", "synthetic", "project", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"results": [
            {"id": "wrong-version", "description": description},
        ], "next_cursor": None})))
    try:
        assert writer.reconcile("mailhelp:mail:p1:v1") is None
    finally:
        writer.close()


def test_todoist_exact_marker_reconciles_correct_version_on_later_page():
    requests = []
    def handler(request):
        requests.append(request)
        data = ({"results": [{"id": "v10", "description": "[mailhelp:mail:p1:v10]"}],
                 "next_cursor": "page2"} if "cursor" not in request.url.params else
                {"results": [{"id": "v1", "description": "Text\n\n[mailhelp:mail:p1:v1]"}],
                 "next_cursor": None})
        return httpx.Response(200, json=data)
    writer = HttpWriter("todoist", "synthetic", "project", transport=httpx.MockTransport(handler))
    try:
        assert writer.reconcile("mailhelp:mail:p1:v1")["id"] == "v1"
        assert requests[1].url.params["cursor"] == "page2"
    finally:
        writer.close()


@pytest.mark.parametrize("matching", [True, False])
def test_calendar_search_follows_pages_before_any_write(matching):
    requests = []
    compared = []
    def handler(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"id": "new"})
        if "pageToken" not in request.url.params:
            items = [{"id": f"first-{i}", "summary": "Other", "start": {}, "end": {}}
                     for i in range(50)]
            return httpx.Response(200, json={"items": items, "nextPageToken": "page2"})
        return httpx.Response(200, json={"items": [
            {"id": "last", "summary": "Target", "start": {}, "end": {}},
        ]})
    def matcher(item, existing):
        compared.append(existing["id"])
        return "call", CalendarDuplicateDecision(
            same_event=matching and existing["id"] == "last", reason="synthetic comparison")
    writer = HttpWriter("google_calendar", "synthetic", "calendar", calendar_timezone="UTC",
                        calendar_matcher=matcher, transport=httpx.MockTransport(handler))
    try:
        result = writer.create(event(status="confirmed"), "key")
        assert result["id"] == ("last" if matching else "new")
        assert len(compared) == 51
        assert requests[1].url.params["pageToken"] == "page2"
        assert [request.method for request in requests] == (["GET", "GET"] if matching else ["GET", "GET", "POST"])
        if matching:
            assert result["operation"] == "duplicate_skipped"
    finally:
        writer.close()


@pytest.mark.parametrize("token", ["", 4, [], "loop"])
def test_calendar_invalid_or_repeated_page_token_never_creates(token):
    requests = []
    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        return httpx.Response(200, json={"items": [], "nextPageToken": token})
    writer = HttpWriter("google_calendar", "synthetic", "calendar", calendar_timezone="UTC",
                        calendar_matcher=lambda *_: None, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ValueError, match="ungültige Antwort"):
            writer.create(event(status="confirmed"), "key")
        assert len(requests) == (2 if token == "loop" else 1)
    finally:
        writer.close()


def test_calendar_empty_intermediate_page_is_followed():
    requests = []
    def handler(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"id": "new"})
        return httpx.Response(200, json={"items": [], **(
            {"nextPageToken": "next"} if "pageToken" not in request.url.params else {})})
    writer = HttpWriter("google_calendar", "synthetic", "calendar", calendar_timezone="UTC",
                        calendar_matcher=lambda *_: None, transport=httpx.MockTransport(handler))
    try:
        assert writer.create(event(status="confirmed"), "key")["id"] == "new"
        assert [request.method for request in requests] == ["GET", "GET", "POST"]
    finally:
        writer.close()


@pytest.mark.parametrize("failure", ["malformed", "denied"])
def test_calendar_later_page_failure_never_causes_creation(failure):
    requests = []
    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        if "pageToken" not in request.url.params:
            return httpx.Response(200, json={"items": [], "nextPageToken": "next"})
        return (httpx.Response(200, json={"items": "invalid"}) if failure == "malformed"
                else httpx.Response(403, json={}))
    writer = HttpWriter("google_calendar", "synthetic", "calendar", calendar_timezone="UTC",
                        calendar_matcher=lambda *_: None, transport=httpx.MockTransport(handler))
    try:
        from mailhelp.integrations import CalendarAccessError
        with pytest.raises(ValueError if failure == "malformed" else CalendarAccessError):
            writer.create(event(status="confirmed"), "key")
        assert len(requests) == 2
    finally:
        writer.close()


@pytest.mark.parametrize("kind", ["task", "event"])
def test_non_binding_agreement_still_requires_current_authorized_confirmation(tmp_path, kind):
    requests = []
    service = "todoist" if kind == "task" else "google_calendar"
    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"results": [], "next_cursor": None, "items": []})
        return httpx.Response(200, json={"id": "created"})
    writer = HttpWriter(service, "synthetic", "target", calendar_timezone="UTC",
                        transport=httpx.MockTransport(handler))
    question = "Soll der nicht bindende Hinweis dennoch als neuer Eintrag angelegt werden?"
    item = (event if kind == "event" else proposal)(
        target="target", classification="non_binding", status="needs_clarification", open_questions=[question])
    try:
        with JsonStore(tmp_path) as store:
            dialog, telegram, _ = controller(store, writers={service: writer})
            dialog.send_proposal(item)
            edit = telegram.sent[-1][2]["inline_keyboard"][0][0]["callback_data"]
            telegram.updates = [callback(1, edit), message(2, "Ja")]
            dialog.poll_once()
            saved = store.load("proposal-" + item.source_mail_id + "-p1")
            assert saved["status"] == "pending_confirmation" and saved["version"] == 2
            assert saved["classification"] == "non_binding"
            assert requests == []
            for update in [callback(3, f"proposal:{item.source_mail_id}:p1:1:confirm"),
                           callback(4, f"proposal:{item.source_mail_id}:p1:2:confirm", user=9),
                           callback(5, f"proposal:{item.source_mail_id}:p1:2:confirm", chat=9)]:
                telegram.updates = [update]
                dialog.poll_once()
            assert requests == []
        with JsonStore(tmp_path) as store:
            restarted, telegram, _ = controller(store, writers={service: writer})
            telegram.updates = [callback(6, f"proposal:{item.source_mail_id}:p1:2:confirm")]
            restarted.poll_once()
            assert store.load("proposal-" + item.source_mail_id + "-p1")["status"] == "created"
            telegram.updates = [callback(7, f"proposal:{item.source_mail_id}:p1:2:confirm")]
            restarted.poll_once()
            assert len([request for request in requests if request.method == "POST"]) == 1
    finally:
        writer.close()


def test_duplicate_authorization_is_cleared_by_revision_and_rejected_from_llm():
    previous = proposal(status="needs_clarification", open_questions=["Titel?"],
                        explicit_duplicate_create_confirmed_version=1)
    revised = apply_proposal_revision(previous, ProposalRevisionDelta(
        answered_question="Titel?", changes={"title": "New"}))
    assert revised.explicit_duplicate_create_confirmed_version is None
    injected = revised.model_copy(update={"explicit_duplicate_create_confirmed_version": 2})
    with pytest.raises(ContradictoryRevision, match="Doppelanlage"):
        validate_revision_successor(previous, injected.model_dump())
    assert validate_revision_successor(previous, revised.model_dump()) == revised
    with pytest.raises(ValueError):
        ProposalRevisionDelta(answered_question="Titel?", changes={
            "explicit_duplicate_create_confirmed_version": 2})


@pytest.mark.parametrize("authorized_version", [None, 1, 2])
def test_calendar_duplicate_override_only_applies_to_confirmed_version(authorized_version):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"id": "new"} if request.method == "POST" else {
            "items": [{"id": "old", "start": {}, "end": {}}]})
    writer = HttpWriter("google_calendar", "synthetic", "calendar", calendar_timezone="UTC",
                        transport=httpx.MockTransport(handler), calendar_matcher=lambda *_: (
                            "call", CalendarDuplicateDecision(same_event=True, reason="same")))
    try:
        result = writer.create(event(status="confirmed", version=2,
            explicit_duplicate_create_confirmed_version=authorized_version), "key")
        assert result["id"] == ("new" if authorized_version == 2 else "old")
        assert [request.method for request in requests] == (["POST"] if authorized_version == 2 else ["GET"])
    finally:
        writer.close()


@pytest.mark.parametrize("interruption", ["before_write", "uncertain", "late_success"])
def test_explicit_calendar_duplicate_survives_restart_without_blind_retries(tmp_path, monkeypatch, interruption):
    requests = []
    recoverable = False
    def handler(request):
        requests.append(request)
        if request.method == "GET":
            assert "privateExtendedProperty" in request.url.params
            return httpx.Response(200, json={"items": [{"id": "new"}] if recoverable else []})
        assert request.method == "POST"
        if interruption != "before_write":
            raise httpx.ReadTimeout("synthetic uncertain write", request=request)
        return httpx.Response(200, json={"id": "new"})
    def matcher(*_):
        raise AssertionError("Explicit duplicate confirmation must bypass semantic matching")
    writer = HttpWriter("google_calendar", "synthetic", "calendar", calendar_timezone="UTC",
                        transport=httpx.MockTransport(handler), calendar_matcher=matcher)
    source = "b" * 24
    confirm = Decision(mail_id=source, proposal_id="p1", version=1, action=DecisionAction.CONFIRM)
    name = f"proposal-{source}-p1"
    try:
        with JsonStore(tmp_path) as store:
            dialog, telegram, _ = controller(store, writers={"google_calendar": writer})
            dialog.persist(event(status="created", external_id="old"))
            dialog.send_proposal(event(source_mail_id=source))
            dialog.decision_service.decide(confirm, 1, 2)
            assert requests == []
            token = telegram.sent[-1][2]["inline_keyboard"][0][0]["callback_data"]
            duplicate = Decision.parse(token, store)
            assert duplicate.action == DecisionAction.CONFIRM_DUPLICATE
            for user, chat in [(9, 2), (1, 9)]:
                with pytest.raises(PermissionError):
                    dialog.decision_service.decide(duplicate, user, chat)
            with pytest.raises(ValueError, match="veraltet"):
                dialog.decision_service.decide(duplicate.model_copy(update={"version": 2}), 1, 2)
            assert store.load(name)["explicit_duplicate_create_confirmed_version"] is None
            if interruption == "before_write":
                def crash(_):
                    raise RuntimeError("synthetic crash after persisted authorization")
                monkeypatch.setattr(dialog.write_executor, "execute", crash)
                with pytest.raises(RuntimeError, match="synthetic crash"):
                    dialog.decision_service.decide(duplicate, 1, 2)
                assert store.load(name)["status"] == "confirmed"
            else:
                dialog.decision_service.decide(duplicate, 1, 2)
                assert store.load(name)["status"] == "uncertain"
            assert store.load(name)["explicit_duplicate_create_confirmed_version"] == 1
        recoverable = interruption == "late_success"
        for _ in range(2):
            with JsonStore(tmp_path) as store:
                restarted, telegram, _ = controller(store, writers={"google_calendar": writer})
                restarted.poll_once()
                saved = store.load(name)
                assert saved["status"] == ("uncertain" if interruption == "uncertain" else "created")
                assert saved["explicit_duplicate_create_confirmed_version"] == 1
                with pytest.raises(ValueError, match="veraltet"):
                    restarted.decision_service.decide(Decision.parse(token, store), 1, 2)
        assert len([request for request in requests if request.method == "POST"]) == 1
    finally:
        writer.close()


def test_posix_storage_lock_and_directory_sync_on_all_platforms(tmp_path, monkeypatch):
    """Exercise the POSIX syscall contract on Windows without changing global os.name."""
    import os
    import mailhelp.storage as storage
    store = JsonStore(tmp_path)
    calls = []
    descriptor = os.open(tmp_path / "lock", os.O_CREAT | os.O_RDWR, 0o600)
    class PosixOS:
        name = "posix"
        def __getattr__(self, name):
            return getattr(os, name)
        def open(self, path, flags):
            assert path == tmp_path and flags == os.O_RDONLY
            calls.append("open-directory")
            return descriptor
        def fsync(self, value):
            calls.append(("fsync", value))
        def close(self, value):
            calls.append(("close", value))
    monkeypatch.setattr(storage, "os", PosixOS())
    monkeypatch.setitem(__import__("sys").modules, "fcntl", types.SimpleNamespace(
        LOCK_EX=2, LOCK_NB=4, flock=lambda *args: calls.append(("flock", *args))))
    try:
        store._acquire_lock(descriptor)
        store.save("posix", {"ok": True})
        assert calls[0] == ("flock", descriptor, 6)
        assert calls[-3:] == ["open-directory", ("fsync", descriptor), ("close", descriptor)]
        assert store.load("posix") == {"ok": True}
    finally:
        os.close(descriptor)
