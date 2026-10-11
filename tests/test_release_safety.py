"""Release regressions: bounded locking and genuinely write-free test mode."""
import errno
import os

import pytest

from mailhelp.integrations import execute_confirmed
from mailhelp.models import Proposal, Relevance
from mailhelp.storage import AlreadyRunning, JsonStore


@pytest.mark.parametrize("jev", [False, True])
def test_regression_shortlink_bait_cannot_become_an_action_even_if_model_says_so(jev):
    from pathlib import Path
    from unittest.mock import Mock
    import yaml
    from mailhelp.analysis import Analyzer
    from mailhelp.config import PromptConfig, Topic
    from mailhelp.decisions import JevRelevanceAnalyzer

    config = PromptConfig.model_validate(yaml.safe_load(
        (Path(__file__).parents[1] / "prompts.yaml").read_text(encoding="utf-8")))
    client = Mock()
    client.complete.return_value = ("unsafe", {"decision": "relevant", "topic_ids": ["private"], "reason": "Personal"})
    decisions = Mock()
    decisions.relevance.return_value = ("unsafe", Relevance(decision="relevant", topic_ids=["private"], reason="Personal"))
    service = (JevRelevanceAnalyzer(client, config, decisions=decisions) if jev
               else Analyzer(client, config))
    mail = {"text": "Guten Tag, wie geht es dir? Das solltest du dir anschauen. https://rb.gy/synthetic Teste es auf jeden Fall!"}
    result = service.relevance(mail, [Topic(id="private", name="Privat", enabled=True, description="Private Korrespondenz")])[1]
    assert result.decision == "unclear" and "Kurzlink" in result.reason
    route = service.action_route(mail)[1]
    assert route.action_state == "none" and route.task_count == route.event_count == 0
    client.complete.assert_not_called()
    decisions.relevance.assert_not_called()


def test_regression_transient_lock_after_process_exit_is_retried(tmp_path, monkeypatch):
    store = JsonStore(tmp_path)
    acquire = store._acquire_lock
    attempts = []

    def transient(descriptor):
        attempts.append(descriptor)
        if len(attempts) < 3:
            raise PermissionError(errno.EACCES, "kernel cleanup still pending")
        acquire(descriptor)

    monkeypatch.setattr(store, "_acquire_lock", transient)
    with store:
        store.save("restarted", {"ok": True})
    assert len(attempts) == 3
    assert store.load("restarted") == {"ok": True}


def test_lock_retry_never_steals_live_lock_and_closes_descriptor(tmp_path, monkeypatch):
    store = JsonStore(tmp_path)
    descriptors = []

    def busy(descriptor):
        descriptors.append(descriptor)
        raise PermissionError(errno.EACCES, "another process")

    monkeypatch.setattr(store, "_acquire_lock", busy)
    with pytest.raises(AlreadyRunning):
        store.__enter__()
    assert len(descriptors) == 4
    assert store.lock is None
    with pytest.raises(OSError):
        os.fstat(descriptors[-1])


@pytest.mark.parametrize("kind", ["task", "event"])
def test_regression_test_mode_never_contacts_either_external_writer(tmp_path, kind):
    class ForbiddenWriter:
        def reconcile(self, key):
            pytest.fail("Test mode contacted an external service")

        def create(self, proposal, key):
            pytest.fail("Test mode attempted a write")

    item = Proposal.model_validate(dict(
        id="release", version=1, kind=kind, source_mail_id="a" * 24,
        responsibility="user", certainty="certain", classification="new",
        title="Synthetic", evidence="Synthetic", target="synthetic",
        status="confirmed",
        **({"start": "2026-10-12T10:00:00+02:00",
            "end": "2026-10-12T11:00:00+02:00"} if kind == "event" else {})))
    with JsonStore(tmp_path) as store:
        persist = lambda value: store.save("proposal", value.model_dump(mode="json"))
        result, metadata = execute_confirmed(item, ForbiddenWriter(), persist, True)
        assert result.status == "simulated" and metadata == {"simulation": True}
    with JsonStore(tmp_path) as restored:
        saved = restored.load_model("proposal", Proposal)
        assert execute_confirmed(saved, ForbiddenWriter(), persist, True) == (saved, metadata)


@pytest.mark.parametrize("text,blocked", [
    ("Das solltest du dir anschauen https://rb.gy/synthetic", True),
    ("DAS SOLLTEST DU DIR ANSCHAUEN HTTPS://RB.GY/synthetic", True),
    ("Das solltest du dir anschauen https://www.rb.gy/synthetic", True),
    ("Projektunterlagen fuer die Sitzung https://rb.gy/synthetic", False),
    ("Das solltest du dir anschauen https://rb.gy.example.test/synthetic", False),
    ("Das solltest du dir anschauen https://example.test/rb.gy/synthetic", False),
    ("Das solltest du dir anschauen https://example.test/", False),
    ("", False),
])
def test_shortlink_policy_checks_host_and_lure_together(text, blocked):
    from pathlib import Path
    import yaml
    from mailhelp.analysis import Analyzer
    from mailhelp.config import PromptConfig
    config = PromptConfig.model_validate(yaml.safe_load(
        (Path(__file__).parents[1] / "prompts.yaml").read_text(encoding="utf-8")))
    assert bool(Analyzer(None, config).suspicious_link_bait({"text": text})) is blocked


@pytest.mark.parametrize("status", ["confirmed", "writing", "uncertain"])
def test_restored_snapshot_reconciles_existing_action_across_repeated_restarts(tmp_path, status):
    import shutil
    from test_services import proposal

    external = {}
    writes = []
    class Writer:
        def reconcile(self, key):
            return external.get(key)
        def create(self, item, key):
            writes.append(key)
            external[key] = {"id": "synthetic-existing-action"}
            return external[key]

    original, backup, restored = (tmp_path / name for name in ("original", "backup", "restored"))
    item = proposal(status="confirmed")
    with JsonStore(original) as store:
        store.save("proposal", item.model_dump(mode="json"))
    shutil.copytree(original, backup)  # Consistent backup while service is stopped.
    with JsonStore(original) as store:
        execute_confirmed(item, Writer(), lambda p: store.save("proposal", p.model_dump(mode="json")))
    shutil.copytree(backup, restored)
    for _ in range(25):
        with JsonStore(restored) as store:
            snapshot = store.load_model("proposal", Proposal).model_copy(update={"status": status})
            resolved, result = execute_confirmed(snapshot, Writer(),
                lambda p: store.save("proposal", p.model_dump(mode="json")))
            assert resolved.status == "created" and result["id"] == "synthetic-existing-action"
    assert len(writes) == 1
