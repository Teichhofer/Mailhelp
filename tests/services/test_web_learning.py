"""Browser learning: read-only external work, recoverable local adoption and authorization."""

import json
from threading import Event, Thread

import pytest

from mailhelp.config import read_yaml
from mailhelp.models import IrrelevantSenders
from mailhelp.runtime.learning_jobs import LearningConflict, LearningJobs
from mailhelp.runtime.learning_worker import LearningCompleter, LearningPaused
from tests.fakes.learning_harness import learning


def choice(**patch):
    return (
        dict(
            index=0,
            kind="relevant",
            name="Camping",
            description="Synthetic booking category",
            **{"global": False, "block_senders": False},
        )
        | patch
    )


@pytest.mark.slow
def test_shared_kernel_job_review_and_explicit_joint_adoption(learning):
    h = learning
    before = h.jobs.hashes()
    state = h.review()
    assert state.status == "review" and state.cursor == 2 and state.failures == 0
    assert h.jobs.hashes() == before
    assert len(state.cards) == 1 and state.cards[0].evidence == ["<untrusted>"] * 2
    assert state.cards[0].senders == ["news@example.test"]
    assert state.folders == {"Archive": True, "Junk": False}
    h.change("edit", choice())
    assert h.jobs.hashes() == before
    state = h.change("apply")
    assert state.status == "done"
    found = read_yaml(h.directory / "topics.yaml")["topics"][-1]
    assert found["name"] == "Camping" and found["mailboxes"] == [1]
    assert "Archive" in read_yaml(h.directory / "config.yaml")["imap"]["folders"]
    assert "Junk" not in read_yaml(h.directory / "config.yaml")["imap"]["folders"]
    assert h.client.calls.count("learning_classification") == 2
    assert h.client.calls.count("learning_abstraction") == 2
    assert not h.worker.tick()


@pytest.mark.slow
@pytest.mark.parametrize("globally", [True, False])
def test_irrelevant_categories_sender_scope_and_unselected_cards(learning, globally):
    h = learning
    h.review()
    h.change("edit", choice(kind="skip"))
    h.change("edit", choice(kind="irrelevant", block_senders=True, **{"global": globally}))
    h.change("folder", {"name": "Archive", "selected": False})
    h.change("folder", {"name": "Junk", "selected": True})
    h.change("apply")
    blocked = IrrelevantSenders.model_validate_json((h.directory / "irrelevant-senders.json").read_text())
    assert ("news@example.test" in blocked.addresses) == globally
    if not globally:
        assert blocked.mailboxes["1"].addresses == ["news@example.test"]
    assert "Junk" in read_yaml(h.directory / "config.yaml")["imap"]["folders"]


def test_no_implicit_category_or_sender_acceptance(learning):
    h = learning
    before = read_yaml(h.directory / "topics.yaml")
    h.review()
    h.change("edit", choice(kind="skip"))
    h.change("apply")
    assert read_yaml(h.directory / "topics.yaml") == before
    assert IrrelevantSenders.model_validate_json((h.directory / "irrelevant-senders.json").read_text()).addresses == []


def test_pause_restart_resume_cancel_and_receipt_replay(learning):
    h = learning
    start = h.change("start", h.selection, key="startkey01")
    assert h.jobs.change(h.actor, 0, "startkey01", "start", h.selection) == start
    with pytest.raises(LearningConflict, match="Idempotenz"):
        h.jobs.change(h.actor, 0, "startkey01", "start", h.selection | {"count": 3})
    h.worker.tick()
    h.worker.tick()
    assert h.jobs.state().cursor == 1
    h.jobs.recover()
    assert h.jobs.state().status == "paused"
    assert not h.worker.tick()
    h.change("resume")
    h.worker.tick()
    assert h.reader.reads == [2, 1]
    h.change("pause")
    h.jobs.recover()
    h.change("cancel")
    assert h.jobs.state().status == "cancelled"
    h.change("start", h.selection)
    assert h.jobs.state().cursor == 0


@pytest.mark.parametrize(
    "action,payload",
    [
        ("pause", {}),
        ("resume", {}),
        ("cancel", {}),
        ("apply", {}),
        ("unknown", {}),
        ("start", dict(mailbox=99)),
        ("start", dict(folders=["INBOX", "INBOX"])),
        ("start", dict(folders=["Unknown"])),
        ("start", dict(budget_usd=0.000001)),
    ],
)
def test_invalid_job_transitions_do_not_write(learning, action, payload):
    h = learning
    before = h.jobs.hashes()
    with pytest.raises(ValueError):
        h.change(action, h.selection | payload if action == "start" else payload)
    assert h.jobs.hashes() == before and h.jobs.state().status == "empty"


def test_stale_and_expired_actions_are_refused(learning):
    h = learning
    with pytest.raises(LearningConflict, match="Idempotenz"):
        h.change("start", h.selection, key="?")
    with pytest.raises(LearningConflict, match="Lernstand"):
        h.change("start", h.selection, version=44)
    h.change("start", h.selection)
    with pytest.raises(LearningConflict, match="offenen"):
        h.change("start", h.selection)
    h.change("pause")
    (h.directory / "topics.yaml").write_text(
        (h.directory / "topics.yaml").read_text(encoding="utf8") + "\n", encoding="utf8"
    )
    with pytest.raises(LearningConflict, match="Konfiguration"):
        h.change("resume")
    h.auth.revoke_all()
    with pytest.raises(LearningConflict, match="Sitzung"):
        h.change("cancel")


def test_session_rechecked_after_estimation(learning):
    h = learning
    h.jobs.estimate = lambda _: (h.auth.revoke_all() and 0)
    with pytest.raises(LearningConflict, match="Sitzung"):
        h.change("start", h.selection)
    assert h.jobs.state().status == "empty"


@pytest.mark.parametrize("patch", [{"index": -1}, {"index": 99}, {"index": True}, {"kind": "other"}, {"name": ""}])
def test_invalid_review_edit_is_refused(learning, patch):
    h = learning
    h.review()
    before = h.jobs.state()
    with pytest.raises(ValueError):
        h.change("edit", choice(**patch))
    assert h.jobs.state() == before


@pytest.mark.parametrize("payload", [{"name": "Unknown", "selected": True}, {"name": "Archive", "selected": "true"}])
def test_invalid_folder_review_is_refused(learning, payload):
    h = learning
    h.review()
    with pytest.raises(LearningConflict):
        h.change("folder", payload)


def test_config_changed_during_review_requires_new_job(learning):
    h = learning
    h.review()
    (h.directory / "topics.yaml").write_text("topics: []", encoding="utf8")
    with pytest.raises(LearningConflict, match="Konfiguration"):
        h.change("apply")


@pytest.mark.parametrize("modify", ["unexpected", "index", "duplicate", "kind", "folder"])
def test_joint_commit_validates_untrusted_selections(learning, modify):
    h = learning
    state = h.review()
    payload = {"cards": [choice()], "folders": []}
    if modify == "unexpected":
        payload["cards"][0]["extra"] = "no"
    if modify == "index":
        payload["cards"][0]["index"] = "0"
    if modify == "duplicate":
        payload["cards"] *= 2
    if modify == "kind":
        payload["cards"][0]["kind"] = "wrong"
    if modify == "folder":
        payload["folders"] = ["Nonexistent"]
    with pytest.raises(LearningConflict):
        h.jobs.prepare_commit(state, payload)


@pytest.mark.slow
def test_atomic_commit_recovers_after_interrupted_write(learning, monkeypatch):
    from mailhelp.runtime import learning_jobs

    h = learning
    h.review()
    h.change("edit", choice())
    original = learning_jobs.atomic_replace
    writes = []

    def interrupt(path, content):
        original(path, content)
        writes.append(path.name)
        if len(writes) == 2:
            raise OSError("synthetic interruption")

    monkeypatch.setattr(learning_jobs, "atomic_replace", interrupt)
    with pytest.raises(OSError):
        h.change("apply", key="commitkey01")
    assert h.jobs.state().status == "committing"
    monkeypatch.setattr(learning_jobs, "atomic_replace", original)
    restored = LearningJobs(h.configuration, h.jobs.active, h.worker.estimate)
    restored.recover()
    assert restored.state().status == "done"
    assert sum(t["name"] == "Camping" for t in read_yaml(h.directory / "topics.yaml")["topics"]) == 1
    before = h.jobs.hashes()
    restored.recover()
    assert h.jobs.hashes() == before


@pytest.mark.slow
def test_recovery_never_overwrites_unrelated_external_edit(learning):
    h = learning
    state = h.review()
    h.jobs.prepare_commit(state, {"cards": [], "folders": []})
    h.jobs.save(state)
    (h.directory / "topics.yaml").write_text("unrelated", encoding="utf8")
    with pytest.raises(LearningConflict, match="außerhalb"):
        h.jobs.recover()
    assert (h.directory / "topics.yaml").read_text() == "unrelated"


@pytest.mark.parametrize("reason", ["budget", "revoked", "changed", "stopped", "paused", "cancelled"])
def test_each_actual_call_reserves_before_network_and_stops_safely(learning, reason):
    h = learning
    h.change("start", h.selection)
    if reason == "budget":
        state = h.jobs.state()
        state.reserved_tokens = 10**20
        h.jobs.save(state)
    if reason == "revoked":
        h.auth.revoke_all()
    if reason == "changed":
        (h.directory / "topics.yaml").write_text("changed", encoding="utf8")
    if reason == "stopped":
        h.worker.stopped.set()
    if reason in {"paused", "cancelled"}:
        h.change("pause" if reason == "paused" else "cancel")
    with pytest.raises(LearningPaused):
        LearningCompleter(h.worker, h.client).complete("synthetic", {}, "system", {})
    assert h.client.calls == []
    assert h.jobs.state().status == ("cancelled" if reason == "cancelled" else "paused")
    assert LearningCompleter(h.worker, h.client).policy is h.client.policy


def test_pause_and_cancel_during_call_use_mail_boundary(learning):
    h = learning
    h.change("start", h.selection)
    h.worker.tick()
    h.client.before = lambda: h.change("pause") if h.jobs.state().status == "running" else None
    with pytest.raises(LearningPaused):
        h.worker.tick()
    assert h.jobs.state().cursor == 0 and h.jobs.state().reserved_tokens > 0
    h.change("resume")
    h.client.before = lambda: h.change("cancel") if h.jobs.state().status == "running" else None
    with pytest.raises(LearningPaused):
        h.worker.tick()
    assert h.jobs.state().status == "cancelled"


def test_background_job_survives_failures_without_secret_diagnostics(learning):
    h = learning
    h.change("start", h.selection)
    h.reader.before = lambda: (_ for _ in ()).throw(ConnectionError("synthetic-secret"))
    h.worker.start()
    h.worker.stop()
    assert h.jobs.state().status == "paused"
    assert "synthetic-secret" not in h.jobs.state().model_dump_json()


def test_network_work_holds_no_store_lock_and_cancel_prevents_late_results(learning):
    h = learning
    h.change("start", h.selection)
    h.worker.tick()
    entered, release = Event(), Event()

    def barrier():
        entered.set()
        assert release.wait(10)

    h.reader.before = barrier
    outcomes = []

    def tick():
        try:
            h.worker.tick()
        except LearningPaused:
            outcomes.append("cancelled")

    worker = Thread(target=tick)
    worker.start()
    assert entered.wait(10)
    h.change("cancel")
    release.set()
    worker.join(10)
    assert not worker.is_alive() and h.jobs.state().cards == [] and outcomes == ["cancelled"]


def test_browser_authorization_csrf_estimate_review_and_stale_forms(learning):
    from urllib.parse import urlencode

    from tests.fakes.shared_web_auth import Browser

    h = learning
    assert Browser(h.web, host="localhost:8765").request("GET", "/lernen").status == 303
    assert h.browser.request("GET", "/lernen").status == 200
    assert h.browser.request("POST", "/lernen", {"action": "start"}).status == 403
    query = urlencode(dict(mailbox=1, count=2, folders="INBOX", price=0.001, budget=1000))
    page = h.browser.request("GET", "/lernen?" + query).body.decode()
    assert "Konservative Schätzung" in page and "kostenpflichtig starten" in page
    assert "Angaben für" in h.browser.request("GET", "/lernen?count=no").body.decode()

    def post(action, **extra):
        return h.browser.request(
            "POST",
            "/lernen",
            {
                "csrf": h.auth.csrf_token(h.initial.session.id),
                "action": action,
                "version": h.jobs.state().version,
                "key": "browserkey" + str(h.sequence),
                **extra,
            },
        )

    assert post("start", selection=json.dumps(h.selection)).status == 303
    assert "Pausieren" in h.browser.request("GET", "/lernen").body.decode()
    assert h.browser.request("GET", "/api/lernen").status == 200
    while h.worker.tick():
        pass
    page = h.browser.request("GET", "/lernen").body.decode()
    assert "&lt;untrusted&gt;" in page and "<untrusted>" not in page
    h.sequence += 1
    assert post("edit", **(choice() | {"index": "0", "global": "on", "block_senders": "on"})).status == 303
    h.sequence += 1
    assert post("folder", name="Archive", selected="on").status == 303
    page = h.browser.request("GET", "/lernen").body.decode()
    assert " checked" in page
    h.sequence += 1
    assert post("apply").status == 303
    assert "Konfiguration neu laden" in h.browser.request("GET", "/lernen").body.decode()
    assert post("start", selection="broken").status == 409
