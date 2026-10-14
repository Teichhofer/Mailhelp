"""Synthetic reproductions of the three production observations in the 2.4 plan."""
from datetime import UTC, datetime

import pytest
from shared_services import AnalyzerStub, Notify

from mailhelp.domain.proposal import DuplicateMatchInfo, DuplicateSource, Proposal, ProposalStatus
from mailhelp.imap import FetchedMail
from mailhelp.models import ActionRoute, EventExtraction, ExtractedEvent, ExtractedTask, TaskExtraction
from mailhelp.orchestrator import Orchestrator
from mailhelp.precheck import DuplicatePreCheckService
from mailhelp.review.views import ReviewViews
from mailhelp.storage import JsonStore
from mailhelp.telegram.persistence import ProposalRepository


class Events(AnalyzerStub):
    def __init__(self, title="Videokonferenz", *, end=None, task=False):
        super().__init__("relevant")
        self.title, self.end, self.task = title, end, task

    def action_route(self, mail):
        return "route", ActionRoute(action_state="task_and_event" if self.task else "event",
                                     task_count=int(self.task), event_count=1, reason="Synthetic invitation")

    def extract_events(self, mail, *, expected_count):
        return "event", EventExtraction(events=[ExtractedEvent(
            title=self.title, description="Online-Sitzung des synthetischen Fachbeirats",
            evidence="Videokonferenz am 20. November 2030 um 14:00 Uhr", responsibility="user",
            certainty="certain", classification="new", date_text="20. November 2030",
            time_text="14:00 Uhr", end_time_text=self.end, time_requirement="timed", location="online")])

    def extract_tasks(self, mail, *, expected_count):
        return "task", TaskExtraction(tasks=[ExtractedTask(
            title="Teilnahme zurückmelden", description="Zur Online-Sitzung anmelden",
            evidence="Bitte Teilnahme zurückmelden",
            responsibility="user", certainty="certain", classification="new")])


class PersistingNotify(Notify):
    def __init__(self, store):
        super().__init__()
        self.repository = ProposalRepository(store)

    def send_proposal(self, proposal):
        self.repository.save_revision(proposal)
        super().send_proposal(proposal)


class Existing(DuplicatePreCheckService):
    def check_proposal(self, proposal, mail_context=None):
        if proposal.kind == "event":
            return proposal.model_copy(update={"status": ProposalStatus.ALREADY_EXISTS,
                "duplicate_match": DuplicateMatchInfo(source=DuplicateSource.GOOGLE_CALENDAR,
                    external_id="synthetic-event", matched_title="Beiratssitzung online",
                    external_link="https://calendar.example.test/event")})
        return proposal


def process(store, analyzer, uid=1, precheck=None):
    notify = PersistingNotify(store)
    engine = Orchestrator(analyzer, store, notify, 1, [], 100000, user_timezone="Europe/Berlin",
                          precheck=precheck)
    raw = (f"From: sender@example.test\nSubject: AW: Synthetischer Fachbeirat\n"
           f"Message-ID: <synthetic-{uid}@example.test>\nReferences: <thread@example.test>\n"
           f"Date: Mon, 18 Nov 2030 10:00:00 +0100\n\n"
           f"Videokonferenz am 20. November 2030 um 14:00 Uhr. Bitte Teilnahme zurückmelden. Nachricht {uid}.").encode()
    result = engine.process(FetchedMail("INBOX", uid, 1, raw,
                         received_at=datetime(2030, 11, 18, 9, tzinfo=UTC)))
    return result, notify


def current(store):
    return [store.load_model(name, Proposal) for name in store.names("proposal-") if "-v" not in name]


