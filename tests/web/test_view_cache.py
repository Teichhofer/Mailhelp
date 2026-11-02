"""Cached overview and per-mail history keep pages fast without showing stale state."""
from __future__ import annotations

import os

from web_scenario import mail_id, populate, proposal, save_mail

from mailhelp.review.archive import record_event
from mailhelp.review.queries import ArchiveQueries
from mailhelp.review.views import OVERVIEW_MAX_AGE_SECONDS, ReviewViews
from mailhelp.storage import JsonStore


def test_the_overview_is_rebuilt_only_after_a_change(tmp_path):
    with JsonStore(tmp_path) as store:
        populate(store)
        views = ReviewViews(store, "Europe/Berlin")
        now = [100.0]
        views.clock = lambda: now[0]
        first = views.overview()
        assert views.overview() is first
        # A state change, changed settings (touch) and changed mailbox labels rebuild it.
        save_mail(store, 9, "Neu <neu@x.test>", "Neu", [proposal(9, "neu")])
        second = views.overview()
        assert second is not first and "neu" in {view.proposal_id for view in second.open}
        store.touch()
        third = views.overview()
        assert third is not second and third.fingerprint != second.fingerprint
        views.mailboxes = {"0" * 24: (2, "Arbeit")}
        assert views.overview() is not third
        cached = views.overview()
        # A file written by another program changes the directory time.
        (tmp_path / f"proposal-{mail_id(1)}-kaputt.json").write_text("{", encoding="utf-8")
        stat = tmp_path.stat()
        os.utime(tmp_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        changed = views.overview()
        assert changed is not cached and changed.damaged == cached.damaged + 1
        # An in-place change outside the process is picked up after the maximum age.
        now[0] += OVERVIEW_MAX_AGE_SECONDS - 1
        assert views.overview() is changed
        now[0] += 1
        assert views.overview() is not changed


def test_an_unreadable_directory_time_does_not_break_the_overview(tmp_path):
    with JsonStore(tmp_path / "data") as store:
        populate(store)
        views = ReviewViews(store, "Europe/Berlin")
        store.directory = tmp_path / "fehlt"
        assert views.overview().damaged == 0


def test_history_of_one_mail_equals_its_part_of_the_full_history(tmp_path):
    with JsonStore(tmp_path) as store:
        populate(store)
        item = proposal(1, "elternabend", kind="event", start="2026-10-21T19:00:00+02:00",
                        end="2026-10-21T20:30:00+02:00")
        record_event(store, item, "confirm", "web", "key-1")
        queries = ArchiveQueries(store)
        full = queries.history()
        for number in (1, 2, 3):
            mail = mail_id(number)
            assert queries.history_of(mail) == [row for row in full if row["mail_id"] == mail]
        (event,) = queries.history_of(mail_id(1))
        assert (event["kind"], event["proposal_id"], event["proposal_kind"], event["source"]) == (
            "confirm", "elternabend", "event", "web")
        assert [row["kind"] for row in queries.history_of(mail_id(2))] == ["legacy"]
        assert queries.history_of(mail_id(99)) == []
        store.save(f"history-{mail_id(1)}", {"schema_version": 1, "removed": True})
        assert queries.history_of(mail_id(1)) == []
        (tmp_path / f"history-{mail_id(2)}.json").write_text("{", encoding="utf-8")
        assert queries.history_of(mail_id(2)) == []
        (tmp_path / f"mail-{mail_id(3)}.json").write_text("{", encoding="utf-8")
        assert queries.history_of(mail_id(3)) == []
