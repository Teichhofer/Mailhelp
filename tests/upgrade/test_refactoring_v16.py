"""Compatibility and standalone service contracts for release 1.6."""
from datetime import UTC, datetime
from threading import Event

from shared_application import Log, Orch, Store, settings

from mailhelp import integrations
from mailhelp.external.confirmed import execute_confirmed
from mailhelp.external.http_writer import HttpWriter
from mailhelp.external.ical import CalendarFileWriter, calendar_file
from mailhelp.external.oauth import GoogleOAuthTokenProvider
from mailhelp.imap import FetchedMail, MailCandidate
from mailhelp.mailbox_run import MailboxRunService
from mailhelp.models import MailRunState
from mailhelp.orchestrator import ProcessingOutcome, ProcessingResult
from mailhelp.web import review_pages, status_pages


def test_existing_integration_and_renderer_imports_remain_identical():
    assert integrations.GoogleOAuthTokenProvider is GoogleOAuthTokenProvider
    assert integrations.HttpWriter is HttpWriter
    assert integrations.execute_confirmed is execute_confirmed
    assert integrations.CalendarFileWriter is CalendarFileWriter
    assert integrations.calendar_file is calendar_file
    assert review_pages.ServiceInfo is status_pages.ServiceInfo
    assert review_pages.status_page is status_pages.status_page


def test_mailbox_service_materializes_batch_before_bodies_and_resumes_without_application(tmp_path):
    store = Store()
    stopped = Event()
    stamp = datetime(2026, 10, 1, tzinfo=UTC)

    class Reader:
        account_id = "a" * 24
        last_uidvalidity = 7

        def __init__(self):
            self.bodies = []
            self.discoveries = 0

        def discover_since(self, folder, start, expected, ranges):
            self.discoveries += 1
            return [MailCandidate(folder, 7, uid, self.account_id, stamp)
                    for uid in (2, 1)]

        def fetch_uid(self, folder, uid, validity):
            run = store.load_model(f"mail-run-{self.account_id}", MailRunState)
            assert [entry.uid for entry in run.entries] == [2, 1]
            assert next(entry for entry in run.entries if entry.uid == uid).status == "processing"
            self.bodies.append(uid)
            return FetchedMail(folder, validity, uid, b"Subject: synthetic\n\nbody")

    reader = Reader()
    processed = []

    def process(mail):
        processed.append(mail.uid)
        stopped.set()
        return ProcessingResult(ProcessingOutcome.COMPLETED, {})

    configured = settings(tmp_path)
    first = MailboxRunService(configured, store, Log(), reader, Orch(), stopped, process)
    assert len(first.poll(2)) == 1
    assert reader.bodies == processed == [2]
    stopped.clear()
    restarted = MailboxRunService(configured, store, Log(), reader, Orch(), stopped, process)
    assert len(restarted.poll(2)) == 1
    assert reader.bodies == processed == [2, 1]
    assert reader.discoveries == 1  # resume uses the saved batch, no rediscovery
    checkpoint = store.load(f"imap-{reader.account_id}-{b'INBOX'.hex()}")
    assert checkpoint["completed_uid_ranges"] == [(1, 2)]


def renderer_contract_pages(store, renderer):
    """Fixed synthetic states, including malicious mail values and runtime contacts."""
    from dataclasses import replace

    from web_scenario import NOW, mail_id, populate

    from mailhelp.review.inbox import CommandStatus
    from mailhelp.review.views import ReviewViews
    populate(store)
    views = ReviewViews(store, "Europe/Berlin", test_mode=True)
    overview = replace(views.overview(), fingerprint="fixed-contract")
    info = renderer.ServiceInfo(
        version="1.5.0", test_mode=True, started_at=NOW, now=NOW,
        address="http://127.0.0.1:8765", devices=2, llm_calls_per_minute=20,
        commands={CommandStatus.QUEUED: 1}, services=("imap", "telegram"),
        runtime={"stage": "relevance", "elapsed": 123, "mail_id": mail_id(4),
                 "next_poll": NOW.isoformat(),
                 "contacts": {"imap": NOW.isoformat(), "<script>": NOW.isoformat()}},
    )
    mail = views.mail(mail_id(1))
    return {
        "overview": renderer.overview_page(overview),
        "proposal": renderer.detail_page(views.proposal(mail_id(4), "boese"), mail=views.mail(mail_id(4))),
        "mail": renderer.mail_page(mail),
        "status_runtime": renderer.status_page(overview.run, overview, "Europe/Berlin", views.system(NOW), info),
        "status_no_runtime": renderer.status_page(overview.run, overview, "Europe/Berlin", views.system(NOW), replace(info, runtime=None)),
    }


def test_renderer_output_is_byte_identical_to_release_15(tmp_path):
    import hashlib
    import json
    from pathlib import Path

    from mailhelp.storage import JsonStore
    expected = json.loads(Path(__file__).with_name("renderer_v15_hashes.json").read_text(encoding="utf-8"))
    with JsonStore(tmp_path) as store:
        pages = renderer_contract_pages(store, review_pages)
    # 2.0 only wraps existing content: the open items (master list of the split view)
    # and the mail of a proposal (collapsed source section). Without the wrappers
    # every byte is still the same as in release 1.5.
    overview, proposal = pages["overview"], pages["proposal"]
    assert overview.count('<div class="open-items">') == 1
    pages["overview"] = overview.replace('<div class="open-items">', "", 1).replace(
        "</div>\n<h2>Zuletzt erledigt</h2>", "\n<h2>Zuletzt erledigt</h2>", 1)
    wrapper = '<details class="disclosure"><summary>Quellbeleg aus E-Mail / Anhang</summary>'
    assert proposal.count(wrapper) == 1 and proposal.count("</section></details>") == 1
    pages["proposal"] = proposal.replace(wrapper, "", 1).replace("</section></details>", "</section>", 1)
    # 2.2 adds one navigation entry for activity reports.
    berichte = '<a href="/berichte">Berichte</a>'
    assert all(html.count(berichte) == 1 for html in pages.values())
    pages = {name: html.replace(berichte, "", 1) for name, html in pages.items()}
    abgleich = '<a href="/abgleich">Vorschlagsabgleich</a>'
    assert all(html.count(abgleich) == 1 for html in pages.values())
    pages = {name: html.replace(abgleich, "", 1) for name, html in pages.items()}
    assert {name: hashlib.sha256(html.encode("utf-8")).hexdigest()
            for name, html in pages.items()} == expected


def test_successor_builder_rejects_changed_identity_without_persisting(tmp_path):
    import pytest
    from web_scenario import Revisions, proposal

    from mailhelp.analysis import ContradictoryRevision
    from mailhelp.telegram.revision_successor import build_revision_successor
    original = proposal(1, "edit")
    revised, deterministic = build_revision_successor(original, "Welche Änderung?", "Titel: Neuer Titel", "UTC", Revisions())
    assert (revised.id, revised.version, revised.title) == (original.id, 2, "Neuer Titel")
    assert not deterministic
    assert original.version == 1 and original.title == "Aufgabe"

    class WrongIdentity:
        def revise_proposal(self, item, question, answer):
            return "call", revised.model_copy(update={"id": "different"})

    with pytest.raises(ContradictoryRevision, match="Identität|identität"):
        build_revision_successor(original, "Welche Änderung?", "Neuer Titel", "UTC", WrongIdentity())
    assert list(tmp_path.iterdir()) == []
