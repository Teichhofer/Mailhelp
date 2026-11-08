"""4.7, step 18.6: the link to the original mail arrives in Todoist and in Google Calendar.

Synthetic mail, simulated services; the Message-ID contains characters that must be encoded.
"""
import json
from datetime import UTC, datetime

import httpx
import pytest

from mailhelp.config import TargetSettings, Topic
from mailhelp.external.confirmed import execute_confirmed
from mailhelp.mailbox.imap import FetchedMail
from mailhelp.models import (
    ActionRoute,
    EventExtraction,
    ExtractedEvent,
    ExtractedTask,
    MailState,
    ProposalStatus,
    TaskExtraction,
)
from mailhelp.processing.orchestrator import Orchestrator
from mailhelp.proposals.integrations import HttpWriter
from mailhelp.storage import JsonStore
from tests.fakes.shared_services import AnalyzerStub, Notify

pytestmark = pytest.mark.e2e

# Allowed in an RFC 5322 msg-id (atext), but not literally in a link.
MESSAGE_ID = "<CAF+x/1=2&y#z{q}@mail.example.test>"
APPLE = "message://%3CCAF%2Bx%2F1%3D2%26y%23z%7Bq%7D@mail.example.test%3E"


class Model(AnalyzerStub):
    def __init__(self):
        super().__init__("relevant")

    def action_route(self, mail):
        return "ar", ActionRoute(action_state="task_and_event", task_count=1, event_count=1, reason="synthetisch")

    def extract_tasks(self, mail, *, expected_count):
        return "t", TaskExtraction(tasks=[ExtractedTask(
            title="Angebot schicken", description="An Firma Muster", evidence="Bitte schicken Sie das Angebot",
            responsibility="user", certainty="certain", classification="new")])

    def extract_events(self, mail, *, expected_count):
        return "e", EventExtraction(events=[ExtractedEvent(
            title="Verbandsausschuss", evidence="am 22.12.2026 ganztägig", date_text="22.12.2026",
            time_requirement="all_day", responsibility="user", certainty="certain", classification="new")])


class Service:
    """Todoist or Google: nothing exists yet; a POST creates one item and is recorded."""

    def __init__(self, created):
        self.created, self.posts = created, []

    def __call__(self, request):
        if request.method == "POST":
            self.posts.append(json.loads(request.content))
            return httpx.Response(200, json=self.created)
        return httpx.Response(200, json={"results": [], "next_cursor": None, "items": []})


def run(tmp_path, message_id_header):
    todoist, google = Service({"id": "t1", "url": "https://todoist.example.test/t1"}), Service(
        {"id": "e1", "htmlLink": "https://calendar.example.test/e1"})
    writers = {"todoist": HttpWriter(service="todoist", token="tok", target="inbox",
                                     transport=httpx.MockTransport(todoist)),
               "google_calendar": HttpWriter(service="google_calendar", token="tok", target="primary",
                                             calendar_timezone="Europe/Berlin", transport=httpx.MockTransport(google))}
    raw = (f"From: Firma Muster <info@muster.example.test>\r\nSubject: Angebot\r\n{message_id_header}"
           "Date: Mon, 23 Nov 2026 09:00:00 +0100\r\n\r\nBitte schicken Sie das Angebot.").encode()
    with JsonStore(tmp_path / "data") as store:
        orchestrator = Orchestrator(Model(), store, Notify(), 1,
                                    [Topic(id="arbeit", name="Arbeit", description="Beruf", enabled=True)], 50_000,
                                    targets=TargetSettings(todoist_project="inbox", google_calendar="primary"),
                                    user_timezone="Europe/Berlin")
        result = orchestrator.process(FetchedMail("INBOX", 1, 1, raw, received_at=datetime(2026, 11, 23, 8, tzinfo=UTC)))
    proposals = MailState.model_validate(result.state).proposals
    for proposal in proposals:
        confirmed = proposal.model_copy(update={"status": ProposalStatus.CONFIRMED, "confirmed_web_actor": None})
        writer = writers["todoist" if proposal.kind == "task" else "google_calendar"]
        written, _ = execute_confirmed(confirmed, writer, lambda _: None, authorize=lambda: True)
        assert written.status == ProposalStatus.CREATED
    return proposals, todoist.posts, google.posts


def test_todoist_and_google_receive_a_clickable_link_to_the_original_mail(tmp_path):
    proposals, tasks, events = run(tmp_path, f"Message-ID: {MESSAGE_ID}\r\n")
    assert all(item.mail_link == APPLE for item in proposals)
    ((task,), (event,)) = tasks, events
    assert f"📧 [Original-E-Mail öffnen]({APPLE})" in task["description"]   # Markdown in Todoist
    assert f"📧 Original-E-Mail öffnen: {APPLE}" in event["description"]      # link in the calendar
    # Characters of the header cannot break out of the link.
    assert not set(APPLE.removeprefix("message://")) & set("&#{}/+= ")


def test_a_mail_without_message_id_is_written_without_a_link(tmp_path):
    proposals, tasks, events = run(tmp_path, "")
    assert all(item.mail_link is None for item in proposals)
    assert "📧" not in tasks[0]["description"] and "📧" not in events[0]["description"]
