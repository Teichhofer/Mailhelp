"""State names are stored data: their patterns never change between releases."""
from __future__ import annotations

from store_fakes import DelegatingStore, InterruptingStore

from mailhelp import state_names
from mailhelp.storage import JsonStore, StateStore

MAIL = "a" * 24


def test_name_patterns_stay_byte_identical():
    assert state_names.mail(MAIL) == f"mail-{MAIL}"
    assert state_names.mail_run("b" * 24) == "mail-run-" + "b" * 24
    assert state_names.draft(MAIL) == f"draft-{MAIL}"
    assert state_names.proposal(MAIL, "p1") == f"proposal-{MAIL}-p1"
    assert state_names.proposal(MAIL, "p1", 3) == f"proposal-{MAIL}-p1-v3"
    assert state_names.proposal(MAIL, "p1", "3") == f"proposal-{MAIL}-p1-v3"
    assert state_names.proposals_of(MAIL) == f"proposal-{MAIL}-"
    assert state_names.clarification(MAIL, "p1", 2) == f"clarification-{MAIL}-p1-v2"


def test_mail_states_exclude_the_run_queue_that_shares_the_prefix(tmp_path):
    with JsonStore(tmp_path) as store:
        for name in (state_names.mail(MAIL), state_names.mail_run(MAIL), state_names.draft(MAIL)):
            store.save(name, {})
        assert state_names.mail_state_names(store) == [f"mail-{MAIL}"]
    assert state_names.is_mail_state("mail-x") and not state_names.is_mail_state("mail-run-x")


def test_the_store_and_its_test_doubles_implement_the_whole_protocol(tmp_path):
    with JsonStore(tmp_path) as store:
        assert isinstance(store, StateStore)
        for double in (DelegatingStore(store), InterruptingStore(store, 2)):
            assert isinstance(double, StateStore)
            with double.locked():
                double.save("probe", {"ok": True})
            assert double.load("probe") == {"ok": True} and double.directory == tmp_path
