"""4.4.1: an operator pass reads only changed states and never rewrites unchanged ones.

In the field, 224 proposals and their mails were rewritten every four seconds and every
write rebuilt the overview from all 1,664 mails, so web actions waited 2 to 9 seconds.
"""
import os

import pytest

from mailhelp.models import MailState, Proposal, ProposalStatus
from mailhelp.review.views import ReviewViews
from mailhelp.storage import CorruptState, JsonStore
from mailhelp.telegram.relevance import RelevanceDialogProcessor
from tests.fakes.shared_telegram_dialog import relevance_state
from tests.fakes.shared_web_actions import web as web
from tests.scenarios.web_scenario import mail_id, populate, proposal, save_mail


def stamps(directory):
    return {path.name: path.stat().st_mtime_ns for path in directory.glob("*.json")}


def status(item: Proposal) -> ProposalStatus:
    return item.status


def title(item: Proposal) -> str:
    return item.title


# --- regressions -----------------------------------------------------------------


def test_regression_a_later_pass_does_not_rewrite_any_unchanged_proposal(web, monkeypatch):
    """Before 4.4.1 every pass persisted every current proposal and its mail again."""
    web.run()  # The first pass after a start repairs every proposal once.
    persisted = []
    monkeypatch.setattr(web.dialog, "persist", persisted.append)
    before = stamps(web.store.directory)
    web.run()
    web.run()
    assert persisted == []
    changed = {name for name, stamp in stamps(web.store.directory).items() if before.get(name) != stamp}
    assert not {name for name in changed if name.startswith(("proposal-", "mail-"))}, changed


def test_regression_saving_identical_state_writes_nothing_and_keeps_the_revision(tmp_path):
    with JsonStore(tmp_path) as store:
        seen = []
        store.observe("synthetic", seen.append)
        store.save("synthetic", {"a": 1})
        path = tmp_path / "synthetic.json"
        stamp, revision = path.stat().st_mtime_ns, store.revision
        os.utime(path, ns=(stamp - 10_000_000_000, stamp - 10_000_000_000))
        old = path.stat().st_mtime_ns
        store.save("synthetic", {"a": 1})
        assert path.stat().st_mtime_ns == old and store.revision == revision
        assert seen == [{"a": 1}, {"a": 1}]  # Observers still learn the (unchanged) value.
        store.save("synthetic", {"a": 2})
        assert path.stat().st_mtime_ns != old and store.revision == revision + 1
        # A file of the same size but other content is still replaced.
        path.write_text('{\n  "a": 3\n}\n', encoding="utf-8")
        store.save("synthetic", {"a": 2})
        assert store.load("synthetic") == {"a": 2}


def test_regression_a_mailbox_poll_does_not_rebuild_the_overview(tmp_path):
    """Any save, e.g. of an IMAP folder state, used to rebuild the overview from every mail."""
    with JsonStore(tmp_path) as store:
        populate(store)
        views = ReviewViews(store, "Europe/Berlin")
        first = views.overview()
        store.save("imap-synthetic-folder", {"uid": 1})
        store.save("notification-queue", {"entries": []})
        assert views.overview() is first
        save_mail(store, 9, "Neu <neu@x.test>", "Neu", [proposal(9, "neu")])
        second = views.overview()
        assert second is not first and second.fingerprint != first.fingerprint


# --- later passes still act -----------------------------------------------------------


def test_a_later_pass_still_executes_a_newly_confirmed_proposal(web, monkeypatch):
    web.run()
    executed = []
    executor = web.dialog.write_executor
    monkeypatch.setattr(executor, "execute", lambda item: executed.append((item.id, item.status)) or item)
    item = web.dialog.repository.load_current(mail_id(1), "formular")
    web.dialog.repository.save_revision(item.model_copy(update={"status": ProposalStatus.CONFIRMED}))
    executor.resume()
    assert executed == [("formular", ProposalStatus.CONFIRMED)]


def test_a_proposal_damaged_after_the_first_pass_blocks_the_pass_as_before(web):
    web.run()
    path = web.store.directory / f"proposal-{mail_id(1)}-formular.json"
    path.write_text("{", encoding="utf-8")
    for _ in range(2):  # Also once the damage is cached.
        with pytest.raises(CorruptState):
            web.dialog.write_executor.resume()
    assert path.exists()  # Reported, not moved: an operator repairs it.


def test_an_interrupted_first_pass_repairs_everything_again_on_the_next(web, monkeypatch):
    calls, failed = [], []
    original = web.dialog.persist
    def persist(item):
        calls.append(item.id)
        if not failed:
            failed.append(item.id)
            raise OSError("synthetic full disk")
        original(item)
    monkeypatch.setattr(web.dialog, "persist", persist)
    with pytest.raises(OSError):
        web.dialog.write_executor.resume()
    calls.clear()
    web.dialog.write_executor.resume()
    assert len(calls) == len([name for name in web.store.names("proposal-") if "-v" not in name])
    calls.clear()
    web.dialog.write_executor.resume()
    assert calls == []


# --- cached reads ------------------------------------------------------------------------


def test_a_cached_projection_is_read_again_only_after_its_file_changed(tmp_path):
    with JsonStore(tmp_path) as store:
        save_mail(store, 1, "A <a@x.test>", "Eins", [proposal(1, "eins", title="Erste")])
        name = f"proposal-{mail_id(1)}-eins"
        path = tmp_path / f"{name}.json"
        reads = []
        original = store.peek_model
        store.peek_model = lambda *args: reads.append(args[0]) or original(*args)
        assert store.cached(name, Proposal, title) == "Erste"
        assert store.cached(name, Proposal, title, store.scan("proposal-")[name]) == "Erste"
        assert store.cached(name, Proposal, status) == ProposalStatus.PENDING_CONFIRMATION
        assert reads == [name, name]  # One read per projection.
        store.save(name, proposal(1, "eins", title="Zweite").model_dump(mode="json"))
        assert store.cached(name, Proposal, title) == "Zweite"
        # Another program: same size, other modification time.
        text = path.read_text(encoding="utf-8").replace("Zweite", "Dritte")
        path.write_text(text, encoding="utf-8")
        stamp = path.stat().st_mtime_ns
        os.utime(path, ns=(stamp + 5_000_000_000, stamp + 5_000_000_000))
        assert store.cached(name, Proposal, title) == "Dritte"
        store.delete(name)
        assert store.cached(name, Proposal, title) is None
        assert store.cached("telegram-dialog", Proposal, title) is None


def test_damage_is_reported_by_the_cache_without_moving_the_file(tmp_path):
    with JsonStore(tmp_path) as store:
        path = tmp_path / f"proposal-{mail_id(1)}-kaputt.json"
        path.write_text("{", encoding="utf-8")
        for _ in range(2):
            with pytest.raises(CorruptState):
                store.cached(path.stem, Proposal, title)
        assert path.exists()
        path.write_text(proposal(1, "kaputt", title="Repariert").model_dump_json(), encoding="utf-8")
        assert store.cached(path.stem, Proposal, title) == "Repariert"
        # A missing authoritative state with an isolated copy stays damaged.
        isolated = tmp_path / f"proposal-{mail_id(1)}-weg.corrupt"
        isolated.write_text("{", encoding="utf-8")
        with pytest.raises(CorruptState):
            store.cached(f"proposal-{mail_id(1)}-weg", Proposal, title)


def test_scan_lists_only_state_files_and_survives_a_missing_directory(tmp_path):
    with JsonStore(tmp_path / "data") as store:
        store.save("mail-b", {})
        store.save("mail-a", {})
        store.save("proposal-x", {})
        (tmp_path / "data" / "mail-c.tmp").write_text("{}", encoding="utf-8")
        (tmp_path / "data" / "mail-d.json").mkdir()
        listing = store.scan("mail-")
        assert list(listing) == ["mail-a", "mail-b"]
        generation, _, size = listing["mail-a"]
        assert generation == 1 and size == 3
        store.directory = tmp_path / "fehlt"
        assert store.scan() == {}


# --- relevance and overview ---------------------------------------------------------------


def test_relevance_dialogs_come_from_cached_mails_and_damage_is_still_isolated(tmp_path):
    with JsonStore(tmp_path) as store:
        store.save("mail-a" + "0" * 22, relevance_state("a" + "0" * 23).model_dump(mode="json"))
        store.save("mail-run-1", {"entries": []})
        processor = RelevanceDialogProcessor(store, None, 2)
        first = processor.all()
        assert [dialog.mail_id for dialog in first] == ["a" + "0" * 23]
        first[0].version = 9  # Callers receive copies; the cache stays intact.
        assert processor.all()[0].version == 1
        broken = tmp_path / ("mail-b" + "0" * 22 + ".json")
        broken.write_text("{", encoding="utf-8")
        with pytest.raises(CorruptState):
            processor.all()
        assert broken.with_suffix(".corrupt").exists()


def test_relevance_uses_the_loaded_state_if_damage_was_repaired_meanwhile(tmp_path, monkeypatch):
    with JsonStore(tmp_path) as store:
        store.save("mail-a" + "0" * 22, relevance_state("a" + "0" * 23).model_dump(mode="json"))
        store.save("mail-c" + "0" * 22, MailState.model_validate(
            relevance_state("c" + "0" * 23).model_dump() | {"relevance_dialog": None, "awaiting_relevance": False}
        ).model_dump(mode="json"))
        def damaged(*args):
            raise CorruptState("synthetic: repaired before loading")
        monkeypatch.setattr(store, "cached", damaged)
        assert [dialog.mail_id for dialog in RelevanceDialogProcessor(store, None, 2).all()] == ["a" + "0" * 23]


def test_an_isolated_mail_still_counts_as_damage_in_the_overview(tmp_path):
    with JsonStore(tmp_path) as store:
        populate(store)
        views = ReviewViews(store, "UTC")
        before = views.overview().damaged
        path = tmp_path / f"mail-{mail_id(1)}.json"
        os.replace(path, path.with_suffix(".corrupt"))
        assert views.overview().damaged == before + 1
