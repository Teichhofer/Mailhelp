"""V1.3 Pipeline, Orchestrator, Attachment Prompt & Regression Tests."""
from datetime import UTC, datetime
from typing import Any

import httpx

from mailhelp.analysis import ActionRoute, Analyzer, Summary
from mailhelp.config import TargetSettings, Topic
from mailhelp.domain.extraction import (
    EventExtraction,
    ExtractedAttachment,
    ExtractedEvent,
    ExtractedTask,
    ParsedCalendarEvent,
    TaskExtraction,
    TelegramAnswerInterpretation,
)
from mailhelp.domain.prepared import PreparedAttachment
from mailhelp.domain.proposal import (
    DuplicateMatchInfo,
    DuplicateSource,
    Proposal,
    ProposalCertainty,
    ProposalClassification,
    ProposalKind,
    ProposalResponsibility,
    ProposalStatus,
)
from mailhelp.domain.temporal import TimeRequirement
from mailhelp.imap import FetchedMail
from mailhelp.integrations import HttpWriter
from mailhelp.models import MailState, ProcessingStage, Relevance
from mailhelp.orchestrator import Orchestrator, ProcessingOutcome
from mailhelp.precheck import DuplicatePreCheckService
from mailhelp.review.cards import card_content
from mailhelp.review.views import MailView, ProposalView, ReviewViews
from mailhelp.storage import JsonStore
from mailhelp.telegram.formatting import format_proposal
from mailhelp.telegram.presenter import ProposalPresenter
from mailhelp.web.review_pages import mail_section, proposal_card


class MockAnalyzer(Analyzer):
    def __init__(self, route=None, tasks=None, events=None, summary_text="Zusammenfassung"):
        self._route = route or ActionRoute(action_state="task_and_event", task_count=1, event_count=1, reason="Test")
        self._tasks = tasks or TaskExtraction(tasks=[
            ExtractedTask(
                title="Bericht fertigstellen",
                description="Monatsbericht fertigstellen",
                due_text="15.10.2026",
                evidence="Bitte Monatsbericht bis morgen einreichen",
                responsibility="user",
                certainty="certain",
                classification="new",
            )
        ])
        self._events = events or EventExtraction(events=[
            ExtractedEvent(
                title="Team-Meeting",
                description="Wöchentliches Update",
                date_text="15.10.2026",
                time_text="10:00",
                end_time_text="11:00",
                time_requirement=TimeRequirement.TIMED,
                evidence="Meeting am 15.10. von 10:00 bis 11:00",
                responsibility="user",
                certainty="certain",
                classification="new",
            )
        ])
        self._summary_text = summary_text
        self.recorded_mails = []

    def relevance(self, mail: dict[str, Any], topics: list[Topic]) -> tuple[str, Relevance]:
        self.recorded_mails.append(("relevance", mail))
        return "call-rel", Relevance(decision="relevant", topic_ids=[topics[0].id], reason="Test relevant")

    def summary(self, mail: dict[str, Any]) -> tuple[str, Summary]:
        self.recorded_mails.append(("summary", mail))
        return "call-sum", Summary(sentences=[self._summary_text], deadlines=[])

    def action_route(self, mail: dict[str, Any]) -> tuple[str, ActionRoute]:
        self.recorded_mails.append(("action_route", mail))
        return "call-route", self._route

    def extract_tasks(self, mail: dict[str, Any], *, expected_count: int) -> tuple[str, TaskExtraction]:
        self.recorded_mails.append(("extract_tasks", mail))
        return "call-task", self._tasks

    def extract_events(self, mail: dict[str, Any], *, expected_count: int) -> tuple[str, EventExtraction]:
        self.recorded_mails.append(("extract_events", mail))
        return "call-event", self._events

    def answer_question_from_mail(self, mail: dict[str, Any], proposal: Proposal, question: str):
        self.recorded_mails.append(("answer_question", mail))
        return "call-answer", TelegramAnswerInterpretation(usable=False, normalized_answer=None, reason="Nicht beantwortbar")


class RecordingNotifier:
    def __init__(self):
        self.messages = []
        self.proposals = []

    def send(self, chat_id: int, text: str) -> None:
        self.messages.append((chat_id, text))

    def send_proposal(self, proposal: Any) -> None:
        self.proposals.append(proposal)

    def send_relevance(self, dialog: Any, sender: str, subject: str) -> None:
        pass

    def awaiting_decision(self) -> bool:
        return False


def test_analyzer_enrich_mail_with_attachments():
    base_mail = {
        "text": "Haupttext der E-Mail.",
        "extracted_attachments": [
            {
                "filename": "protokoll.txt",
                "content_type": "text/plain",
                "size_bytes": 100,
                "text": "Punkt 1: Aufgaben verteilen.",
                "extraction_status": "success",
            },
            {
                "filename": "rechnung.pdf",
                "content_type": "application/pdf",
                "size_bytes": 200,
                "text": "Rechnungsbetrag: 50 EUR fällig am 15.11.",
                "extraction_status": "success",
            },
            {
                "filename": "geheim.pdf",
                "content_type": "application/pdf",
                "size_bytes": 300,
                "text": "",
                "extraction_status": "encrypted",
            },
            {
                "filename": "ohne_typ.txt",
                "content_type": "",
                "size_bytes": 50,
                "text": "Zusatznotiz.",
                "extraction_status": "success",
            },
        ],
    }

    enriched = Analyzer._enrich_mail_with_attachments(base_mail)
    text = enriched["text"]
    assert "Haupttext der E-Mail." in text
    assert "--- Anhang: protokoll.txt (text/plain) ---" in text
    assert "Punkt 1: Aufgaben verteilen." in text
    assert "--- Anhang: rechnung.pdf (application/pdf) ---" in text
    assert "Rechnungsbetrag: 50 EUR fällig am 15.11." in text
    assert "--- Anhang: ohne_typ.txt ---" in text
    assert "Zusatznotiz." in text
    assert "geheim.pdf" not in text

    # Empty or missing extracted_attachments returns same mail
    assert Analyzer._enrich_mail_with_attachments({"text": "Hallo"}) == {"text": "Hallo"}
    assert Analyzer._enrich_mail_with_attachments({"text": "Hallo", "extracted_attachments": []}) == {
        "text": "Hallo",
        "extracted_attachments": [],
    }


def test_orchestrator_precheck_filters_exact_duplicates(tmp_path):
    # Setup Google Calendar writer returning existing event matching proposal
    def cal_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "items": [
                {
                    "id": "cal-999",
                    "summary": "Team-Meeting",
                    "htmlLink": "https://calendar.google.com/event?id=cal-999",
                    "start": {"dateTime": "2026-10-15T10:00:00Z"},
                    "end": {"dateTime": "2026-10-15T11:00:00Z"},
                }
            ]
        })

    cal_writer = HttpWriter(
        service="google_calendar",
        token="tok",
        target="primary",
        calendar_timezone="UTC",
        transport=httpx.MockTransport(cal_handler),
    )
    precheck = DuplicatePreCheckService(writer=cal_writer)

    store = JsonStore(tmp_path)
    notifier = RecordingNotifier()
    analyzer = MockAnalyzer()
    topic = Topic(id="t1", name="Arbeit", enabled=True, description="Berufliche Themen")
    orchestrator = Orchestrator(
        analyzer=analyzer,
        store=store,
        notifier=notifier,
        chat_id=123,
        topics=[topic],
        max_mail_bytes=50000,
        precheck=precheck,
        targets=TargetSettings(todoist_project="inbox", google_calendar="primary"),
        user_timezone="UTC",
    )

    mail = FetchedMail(
        folder="INBOX",
        uidvalidity=1,
        uid=10,
        raw=b"Subject: Team-Meeting\nDate: Wed, 14 Oct 2026 12:00:00 +0000\n\nBesprechung morgen um 10:00",
        received_at=datetime(2026, 10, 14, 12, 0, tzinfo=UTC),
    )

    res = orchestrator.process(mail)
    assert res.outcome == ProcessingOutcome.COMPLETED
    assert res.state["steps"]["duplicate_precheck"] == "completed"

    proposals = res.state["proposals"]
    assert len(proposals) == 2

    # Task proposal is normal and was notified
    task_p = next(p for p in proposals if p["kind"] == "task")
    assert task_p["status"] == "pending_confirmation"

    # Event proposal was detected as exact duplicate in calendar
    event_p = next(p for p in proposals if p["kind"] == "event")
    assert event_p["status"] == "already_exists"
    assert event_p["duplicate_match"]["source"] == "google_calendar"
    assert event_p["duplicate_match"]["external_id"] == "cal-999"

    # Only the non-duplicate task was sent to notifier!
    notified_ids = [p.id for p in notifier.proposals]
    assert task_p["id"] in notified_ids
    assert event_p["id"] not in notified_ids


def test_orchestrator_ics_deterministic_proposal(tmp_path):
    store = JsonStore(tmp_path)
    notifier = RecordingNotifier()
    # Router only expects task; no events expected by LLM
    analyzer = MockAnalyzer(
        route=ActionRoute(action_state="task", task_count=1, event_count=0, reason="Nur Aufgabe"),
        events=EventExtraction(events=[]),
    )
    topic = Topic(id="t1", name="Arbeit", enabled=True, description="Berufliche Themen")
    orchestrator = Orchestrator(
        analyzer=analyzer,
        store=store,
        notifier=notifier,
        chat_id=123,
        topics=[topic],
        max_mail_bytes=50000,
        targets=TargetSettings(todoist_project="inbox", google_calendar="primary"),
        user_timezone="UTC",
    )

    # ICS file attached
    ics_content = b"""BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:conf-2026-xyz\r\nSUMMARY:Strategie-Workshop\r\nDESCRIPTION:Jahresplanung\r\nDTSTART:20261120T090000Z\r\nDTEND:20261120T170000Z\r\nLOCATION:Raum Berlin\r\nEND:VEVENT\r\nEND:VCALENDAR"""

    raw_mail = (
        b'From: boss@example.com\r\n'
        b'To: me@example.com\r\n'
        b'Subject: Einladung Workshop\r\n'
        b'Content-Type: multipart/mixed; boundary="sep"\r\n\r\n'
        b'--sep\r\n'
        b'Content-Type: text/plain\r\n\r\n'
        b'Hier ist der Termin.\r\n\r\n'
        b'--sep\r\n'
        b'Content-Type: text/calendar; name="meeting.ics"\r\n\r\n'
        + ics_content +
        b'\r\n--sep--\r\n'
    )

    mail = FetchedMail("INBOX", 1, 20, raw_mail)
    res = orchestrator.process(mail)
    assert res.outcome == ProcessingOutcome.COMPLETED

    event_proposals = [p for p in res.state["proposals"] if p["kind"] == "event"]
    assert len(event_proposals) == 1
    cal_p = event_proposals[0]
    assert cal_p["title"] == "Strategie-Workshop"
    assert cal_p["location"] == "Raum Berlin"
    assert cal_p["evidence"] == "Aus Kalenderanhang übernommen"
    assert cal_p["status"] == "pending_confirmation"
    assert cal_p["start"] == "2026-11-20T09:00:00Z"
    assert cal_p["end"] == "2026-11-20T17:00:00Z"


def test_orchestrator_failure_outcome_duplicate_precheck(tmp_path):
    store = JsonStore(tmp_path)
    topic = Topic(id="t1", name="Arbeit", enabled=True, description="Berufliche Themen")
    orchestrator = Orchestrator(
        analyzer=MockAnalyzer(),
        store=store,
        notifier=RecordingNotifier(),
        chat_id=123,
        topics=[topic],
        max_mail_bytes=50000,
    )

    state = MailState(
        id="a" * 24,
        imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 1},
        config_fingerprint="0" * 64,
    )
    outcome = orchestrator.failure_outcome("mail-" + state.id, state, ProcessingStage.DUPLICATE_PRECHECK)
    assert outcome == ProcessingOutcome.COMPLETED_WITH_ACTION_ERROR
    assert state.steps.duplicate_precheck == "failed"
    assert state.steps.action_detection == "failed"


# =========================================================================
# REGRESSIONSTESTS (gemäß Mailhelp-Entwicklungsregeln in AGENTS.md)
# =========================================================================

def test_regression_1_existing_calendar_event_suppressed_from_notifications(tmp_path):
    """Regressionstest 1:

    Ein bereits im Kalender existierender Termin darf keine Telegram-Benachrichtigung
    und keinen offenen Eintrag in /offen erzeugen.
    """
    def cal_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "items": [
                {
                    "id": "existing-event-id-123",
                    "summary": "Team-Meeting",
                    "htmlLink": "https://calendar.google.com/event?id=123",
                    "start": {"dateTime": "2026-10-15T10:00:00Z"},
                    "end": {"dateTime": "2026-10-15T11:00:00Z"},
                }
            ]
        })

    cal_writer = HttpWriter(
        service="google_calendar",
        token="test-token",
        target="primary",
        calendar_timezone="UTC",
        transport=httpx.MockTransport(cal_handler),
    )
    precheck = DuplicatePreCheckService(writer=cal_writer)
    store = JsonStore(tmp_path)
    notifier = RecordingNotifier()
    # Mail with only an event that already exists
    analyzer = MockAnalyzer(
        route=ActionRoute(action_state="event", task_count=0, event_count=1, reason="Termin"),
        tasks=TaskExtraction(tasks=[]),
    )
    topic = Topic(id="t1", name="Arbeit", enabled=True, description="Berufliche Themen")
    orchestrator = Orchestrator(
        analyzer=analyzer,
        store=store,
        notifier=notifier,
        chat_id=123,
        topics=[topic],
        max_mail_bytes=50000,
        precheck=precheck,
        targets=TargetSettings(todoist_project="inbox", google_calendar="primary"),
        user_timezone="UTC",
    )

    mail = FetchedMail(
        folder="INBOX",
        uidvalidity=1,
        uid=42,
        raw=b"Subject: Team-Meeting\nDate: Wed, 14 Oct 2026 10:00:00 +0000\n\nMeeting morgen von 10 bis 11",
        received_at=datetime(2026, 10, 14, 10, 0, tzinfo=UTC),
    )

    result = orchestrator.process(mail)
    assert result.outcome == ProcessingOutcome.COMPLETED

    # The proposal exists in state for web auditability, but with status ALREADY_EXISTS
    assert len(result.state["proposals"]) == 1
    proposal_dict = result.state["proposals"][0]
    assert proposal_dict["status"] == "already_exists"

    # ZERO proposals were sent to Telegram!
    assert len(notifier.proposals) == 0

    # In ReviewViews / Overview (the web /offen view), open proposals are empty!
    views = ReviewViews(store, configured_timezone="UTC")
    overview = views.overview()
    assert len(overview.open) == 0


def test_regression_2_rescheduled_event_updates_via_patch(tmp_path):
    """Regressionstest 2:

    Ein geänderter Termin (Reschedule) erkennt den bestehenden Termin,
    setzt target_event_id und time_changes, und aktualisiert bei Bestätigung
    per HTTP PATCH statt ein Duplikat per POST anzulegen.
    """
    patch_executed = False
    post_executed = False

    def cal_handler(request: httpx.Request) -> httpx.Response:
        nonlocal patch_executed, post_executed
        if request.method == "GET" and request.url.path.endswith("/events"):
            # Existing event at 14:00 - 15:00
            return httpx.Response(200, json={
                "items": [
                    {
                        "id": "existing-cal-ev-555",
                        "summary": "Team-Meeting",
                        "htmlLink": "https://calendar.google.com/event?id=555",
                        "start": {"dateTime": "2026-10-15T14:00:00Z"},
                        "end": {"dateTime": "2026-10-15T15:00:00Z"},
                    }
                ]
            })
        elif request.method == "PATCH" and request.url.path.endswith("/events/existing-cal-ev-555"):
            patch_executed = True
            return httpx.Response(200, json={
                "id": "existing-cal-ev-555",
                "htmlLink": "https://calendar.google.com/event?id=555",
            })
        elif request.method == "POST":
            post_executed = True
            return httpx.Response(200, json={"id": "new-event", "htmlLink": "..."})
        return httpx.Response(404, json={})

    cal_writer = HttpWriter(
        service="google_calendar",
        token="test-token",
        target="primary",
        calendar_timezone="UTC",
        transport=httpx.MockTransport(cal_handler),
    )
    precheck = DuplicatePreCheckService(writer=cal_writer)
    store = JsonStore(tmp_path)
    notifier = RecordingNotifier()

    # Mail rescheduling meeting to 10:00 - 11:00
    analyzer = MockAnalyzer(
        route=ActionRoute(action_state="event", task_count=0, event_count=1, reason="Terminverschiebung"),
        tasks=TaskExtraction(tasks=[]),
    )
    topic = Topic(id="t1", name="Arbeit", enabled=True, description="Berufliche Themen")
    orchestrator = Orchestrator(
        analyzer=analyzer,
        store=store,
        notifier=notifier,
        chat_id=123,
        topics=[topic],
        max_mail_bytes=50000,
        precheck=precheck,
        targets=TargetSettings(todoist_project="inbox", google_calendar="primary"),
        user_timezone="UTC",
    )

    mail = FetchedMail(
        folder="INBOX",
        uidvalidity=1,
        uid=43,
        raw=b"Subject: Team-Meeting Verschiebung\nDate: Wed, 14 Oct 2026 10:00:00 +0000\n\nNeuer Termin: 10:00 bis 11:00",
        received_at=datetime(2026, 10, 14, 10, 0, tzinfo=UTC),
    )

    result = orchestrator.process(mail)
    assert result.outcome == ProcessingOutcome.COMPLETED

    assert len(notifier.proposals) == 1
    proposal = notifier.proposals[0]
    assert proposal.status == ProposalStatus.PENDING_CONFIRMATION
    assert proposal.target_event_id == "existing-cal-ev-555"
    assert len(proposal.time_changes) > 0

    # User confirms the reschedule -> HttpWriter executes the update
    prepared = cal_writer.prepare(proposal, "idempotency-key-1")
    assert prepared.requires_write is True
    res = prepared.operation()
    assert patch_executed is True
    assert post_executed is False
    assert res["id"] == "existing-cal-ev-555"


def test_regression_3_pdf_attachment_task_extraction(tmp_path):
    """Regressionstest 3:

    E-Mail mit 'Aufgaben siehe Anhang' und PDF-Anhang extrahiert Aufgaben
    aus dem PDF, Evidence belegt Fundstelle mit Dokumentname.
    """
    store = JsonStore(tmp_path)
    notifier = RecordingNotifier()

    # Simulated LLM extracting task from PDF text passed to it
    extracted_pdf_task = ExtractedTask(
        title="Rechnung 2026-99 bezahlen",
        description="Überweisung an Lieferant ausführen",
        due_text="15.11.2026",
        evidence="[Anhang rechnung.pdf] Bitte begleichen bis 15.11.2026",
        responsibility="user",
        certainty="certain",
        classification="new",
    )
    analyzer = MockAnalyzer(
        route=ActionRoute(action_state="task", task_count=1, event_count=0, reason="Aufgabe in PDF"),
        tasks=TaskExtraction(tasks=[extracted_pdf_task]),
        events=EventExtraction(events=[]),
    )

    topic = Topic(id="t1", name="Arbeit", enabled=True, description="Berufliche Themen")
    orchestrator = Orchestrator(
        analyzer=analyzer,
        store=store,
        notifier=notifier,
        chat_id=123,
        topics=[topic],
        max_mail_bytes=50000,
        targets=TargetSettings(todoist_project="inbox", google_calendar="primary"),
        user_timezone="UTC",
    )

    import base64
    minimal_pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n"
        b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"5 0 obj<</Length 44>>stream\n"
        b"BT /F1 12 Tf 100 700 Td (Hallo Welt) Tj ET\n"
        b"endstream\n"
        b"endobj\n"
        b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000227 00000 n \n0000000294 00000 n \n"
        b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n388\n%%EOF"
    )

    raw_mail = (
        b'From: billing@example.com\r\n'
        b'To: user@example.com\r\n'
        b'Subject: Neue Rechnung\r\n'
        b'Content-Type: multipart/mixed; boundary="bound1"\r\n\r\n'
        b'--bound1\r\n'
        b'Content-Type: text/plain\r\n\r\n'
        b'Aufgaben siehe Anhang.\r\n\r\n'
        b'--bound1\r\n'
        b'Content-Type: application/pdf; name="rechnung.pdf"\r\n'
        b'Content-Transfer-Encoding: base64\r\n\r\n'
        + base64.b64encode(minimal_pdf_bytes) +
        b'\r\n--bound1--\r\n'
    )

    mail = FetchedMail("INBOX", 1, 99, raw_mail)
    result = orchestrator.process(mail)
    assert result.outcome == ProcessingOutcome.COMPLETED

    assert len(notifier.proposals) == 1
    proposal = notifier.proposals[0]
    assert proposal.kind == ProposalKind.TASK
    assert proposal.title == "Rechnung 2026-99 bezahlen"
    assert "rechnung.pdf" in proposal.evidence


CALENDAR_MATCH = DuplicateMatchInfo(
    source=DuplicateSource.GOOGLE_CALENDAR,
    external_id="ev-123",
    external_link="https://calendar.google.com/event?id=ev-123",
    matched_title="Team-Meeting",
    details="Bereits im Google Kalender eingetragen",
)


def rescheduled_card():
    """Card of an event that moves an existing calendar entry from 14:00 to 10:00."""
    return card_content(
        Proposal(
            schema_version=2,
            id="p1",
            version=1,
            kind=ProposalKind.EVENT,
            responsibility=ProposalResponsibility.USER,
            certainty=ProposalCertainty.CERTAIN,
            classification=ProposalClassification.NEW,
            title="Team-Meeting",
            description="Projektstatus",
            evidence="Meeting um 10",
            source_mail_id="m1",
            open_questions=[],
            target="primary",
            status=ProposalStatus.PENDING_CONFIRMATION,
            start=datetime(2026, 10, 15, 10, 0, tzinfo=UTC),
            end=datetime(2026, 10, 15, 11, 0, tzinfo=UTC),
            target_event_id="ev-123",
            time_changes=["Beginn 14:00 → 10:00 Uhr"],
            duplicate_match=CALENDAR_MATCH,
        ),
        "UTC",
    )


def presented(**changes):
    """A web view of the rescheduled card; *changes* override single fields."""
    values = dict(
        mail_id="m1",
        proposal_id="p1",
        version=1,
        status=ProposalStatus.PENDING_CONFIRMATION,
        card=rescheduled_card(),
        sender="Alice",
        subject="Meeting",
        state="Wartet auf Bestätigung",
        editing=False,
        answer_saved=False,
        paused=False,
        current=False,
        queued=False,
        question=None,
        example=None,
        yes_no=False,
        actions=frozenset(),
        confirm_label="Bestehenden Termin aktualisieren",
        external_link=None,
        updated_at=None,
    )
    return ProposalView(**(values | changes))


def test_web_card_shows_the_time_change_against_the_calendar():
    html = proposal_card(presented(duplicate_match=CALENDAR_MATCH, target_event_id="ev-123",
                                   time_changes=["Beginn 14:00 → 10:00 Uhr"]))
    assert "Terminänderung gegenüber dem Kalender" in html
    assert "Beginn 14:00 → 10:00 Uhr" in html


def test_web_card_links_an_existing_calendar_duplicate():
    html = proposal_card(presented(proposal_id="p2", status=ProposalStatus.ALREADY_EXISTS,
                                   state="Bereits vorhanden", confirm_label="Im Kalender anlegen",
                                   duplicate_match=CALENDAR_MATCH))
    assert "Bereits im Google Kalender eingetragen" in html
    assert "https://calendar.google.com/event?id=ev-123" in html


def test_web_card_names_a_ledger_duplicate_without_a_link():
    ledger = DuplicateMatchInfo(source=DuplicateSource.ACTION_LEDGER, external_id=None, external_link=None,
                                matched_title="Team-Meeting", details="Bereits per Mailhelp ausgeführt")
    html = proposal_card(presented(proposal_id="p2", status=ProposalStatus.ALREADY_EXISTS,
                                   state="Bereits vorhanden", confirm_label="Im Kalender anlegen",
                                   duplicate_match=ledger))
    assert '<span class="badge info">Bereits per Mailhelp ausgeführt</span>' in html


def test_web_mail_section_with_attachments_and_calendar():
    mail = MailView(
        mail_id="m1",
        sender="Chef <chef@example.com>",
        subject="Unterlagen",
        received="14.10.2026, 10:00 Uhr",
        text="Hier sind die Unterlagen.",
        attachments_omitted=0,
        text_shortened=False,
        extracted_attachments=(
            PreparedAttachment(filename="plan.pdf", extraction_status="success"),
            PreparedAttachment(filename="passwort.pdf", extraction_status="encrypted"),
        ),
        calendar_events=({"summary": "Meeting", "start": "2026-10-15T10:00:00Z"},),
    )

    html = mail_section(mail)
    assert "plan.pdf" in html
    assert "Text extrahiert" in html
    assert "passwort.pdf" in html
    assert "Verschlüsselt / Passwortgeschützt" in html
    assert "ICS-Kalenderanhang/-anhänge erkannt" in html


def test_telegram_presenter_and_formatting_reschedule_and_cancel():
    proposal_reschedule = Proposal(
        schema_version=2,
        id="p1",
        version=1,
        kind=ProposalKind.EVENT,
        responsibility=ProposalResponsibility.USER,
        certainty=ProposalCertainty.CERTAIN,
        classification=ProposalClassification.NEW,
        title="Team-Meeting",
        description="Wöchentlich",
        evidence="Meeting um 10",
        source_mail_id="a" * 24,
        open_questions=[],
        target="primary",
        status=ProposalStatus.PENDING_CONFIRMATION,
        start=datetime(2026, 10, 15, 10, 0, tzinfo=UTC),
        end=datetime(2026, 10, 15, 11, 0, tzinfo=UTC),
        target_event_id="ev-999",
        time_changes=["Beginn 14:00 → 10:00 Uhr"],
    )

    # Format proposal with time changes
    text = format_proposal(proposal_reschedule, "UTC")
    assert "Terminänderung gegenüber Kalender" in text
    assert "Beginn 14:00 → 10:00 Uhr" in text

    # Format proposal without time changes (covers line 97 of telegram/formatting.py)
    proposal_no_time_changes = proposal_reschedule.model_copy(update={"time_changes": []})
    text_no_changes = format_proposal(proposal_no_time_changes, "UTC")
    assert "🔄 Terminänderung gegenüber Kalender" in text_no_changes

    # Presenter buttons
    presenter = ProposalPresenter("UTC", encode=lambda d: f"enc-{d.action.value}")
    pres = presenter.present(proposal_reschedule)
    buttons = pres.reply_markup["inline_keyboard"][0]
    confirm_btn = buttons[0]
    assert confirm_btn["text"] == "Termin aktualisieren"

    # Cancellation
    proposal_cancel = proposal_reschedule.model_copy(update={
        "classification": ProposalClassification.CANCELLATION,
        "is_cancellation": True,
        "time_changes": [],
    })
    cancel_text = format_proposal(proposal_cancel, "UTC")
    assert "Status: Bestehender Termin soll abgesagt werden" in cancel_text

    pres_cancel = presenter.present(proposal_cancel)
    cancel_btn = pres_cancel.reply_markup["inline_keyboard"][0][0]
    assert cancel_btn["text"] == "Termin absagen"


def test_analysis_attachment_enrichment_edges():
    # The stored form of an attachment (mime.prepare stores the extraction as JSON).
    att = ExtractedAttachment(
        filename="daten.txt",
        content_type="text/plain",
        size_bytes=50,
        text="Wichtiger Inhalt",
        extraction_status="success",
        character_count=16,
    ).model_dump(mode="json")
    enriched = Analyzer._enrich_mail_with_attachments({"text": "Mail-Text", "extracted_attachments": [att]})
    assert enriched["text"] == "Mail-Text\n\n--- Anhang: daten.txt (text/plain) ---\nWichtiger Inhalt"
    # Without a content type the header names only the file.
    bare = Analyzer._enrich_mail_with_attachments({"text": "", "extracted_attachments": [{"text": " x "}]})
    assert bare["text"] == "\n\n--- Anhang: Anhang ---\nx"

    # Failed extraction / empty snippets -> returns original mail untouched (covers line 309 of analysis.py)
    att_failed = ExtractedAttachment(
        filename="broken.pdf",
        content_type="application/pdf",
        size_bytes=50,
        text="",
        extraction_status="error",
        character_count=0,
    )
    mail_failed = {"text": "Nur Mail", "extracted_attachments": [att_failed.model_dump(mode="json")]}
    not_enriched = Analyzer._enrich_mail_with_attachments(mail_failed)
    assert not_enriched == mail_failed


def test_http_writer_calendar_cancellation_prepare():
    import json
    def cal_handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        data = json.loads(request.content)
        assert data["status"] == "cancelled"
        return httpx.Response(200, json={"id": "ev-123", "htmlLink": "https://calendar.google.com/event?id=ev-123"})

    cal_writer = HttpWriter(
        service="google_calendar",
        token="tok",
        target="primary",
        calendar_timezone="UTC",
        transport=httpx.MockTransport(cal_handler),
    )
    proposal_cancel = Proposal(
        schema_version=2,
        id="p1",
        version=1,
        kind=ProposalKind.EVENT,
        responsibility=ProposalResponsibility.USER,
        certainty=ProposalCertainty.CERTAIN,
        classification=ProposalClassification.CANCELLATION,
        title="Abzusagendes Meeting",
        description="Termin",
        evidence="Absage",
        source_mail_id="a" * 24,
        open_questions=[],
        target="primary",
        status=ProposalStatus.PENDING_CONFIRMATION,
        start=datetime(2026, 10, 15, 10, 0, tzinfo=UTC),
        end=datetime(2026, 10, 15, 11, 0, tzinfo=UTC),
        target_event_id="ev-123",
        is_cancellation=True,
    )
    prepared = cal_writer.prepare(proposal_cancel, "key-cancel")
    res = prepared.operation()
    assert res["id"] == "ev-123"
    assert res["operation"] == "duplicate_updated"


def test_proposal_builder_calendar_collision():
    from mailhelp.action_normalization import MailDateContext
    from mailhelp.config import TargetSettings
    from mailhelp.proposal_builder import ProposalBuilder
    context = MailDateContext(
        date_context_status="valid",
        date_header_parsed="2026-10-14T10:00:00+00:00",
        imap_received_at="2026-10-14T10:00:00+00:00",
        user_timezone="UTC",
    )
    builder = ProposalBuilder(
        source_mail_id="a" * 24,
        targets=TargetSettings(todoist_project="inbox", google_calendar="primary"),
        context=context,
        source_sender="Alice",
        source_subject="Test",
    )
    cal1 = ParsedCalendarEvent(
        uid="dup-uid",
        summary="Workshop",
        description="Desc",
        start=datetime(2026, 10, 20, 10, 0, tzinfo=UTC),
        end=datetime(2026, 10, 20, 11, 0, tzinfo=UTC),
        all_day=False,
    )
    cal2 = ParsedCalendarEvent(
        uid="dup-uid",
        summary="Workshop",
        description="Desc",
        start=datetime(2026, 10, 20, 14, 0, tzinfo=UTC),
        end=datetime(2026, 10, 20, 15, 0, tzinfo=UTC),
        all_day=False,
    )
    proposals = builder.build(tasks=[], events=[], calendar_events=[cal1, cal2])
    assert len(proposals) == 2
    assert proposals[0].id != proposals[1].id


def test_review_views_cancellation_label(tmp_path):
    store = JsonStore(tmp_path)
    views = ReviewViews(store, configured_timezone="UTC")
    proposal_cancel = Proposal(
        schema_version=2,
        id="p1",
        version=1,
        kind=ProposalKind.EVENT,
        responsibility=ProposalResponsibility.USER,
        certainty=ProposalCertainty.CERTAIN,
        classification=ProposalClassification.CANCELLATION,
        title="Meeting absagen",
        description="Desc",
        evidence="Evidence",
        source_mail_id="a" * 24,
        open_questions=[],
        target="primary",
        status=ProposalStatus.PENDING_CONFIRMATION,
        start=datetime(2026, 10, 15, 10, 0, tzinfo=UTC),
        end=datetime(2026, 10, 15, 11, 0, tzinfo=UTC),
        target_event_id="ev-123",
        is_cancellation=True,
    )
    store.save(f"proposal-{proposal_cancel.source_mail_id}-{proposal_cancel.id}", proposal_cancel.model_dump(mode="json"))
    views = ReviewViews(store, configured_timezone="UTC")
    pv = views.proposal(proposal_cancel.source_mail_id, proposal_cancel.id)
    assert pv is not None
    assert pv.confirm_label == "Termin absagen"


def test_orchestrator_without_precheck_skips_precheck(tmp_path):
    store = JsonStore(tmp_path)
    notifier = RecordingNotifier()
    analyzer = MockAnalyzer(
        route=ActionRoute(action_state="task", task_count=1, event_count=0, reason="Task"),
        events=EventExtraction(events=[]),
    )
    topic = Topic(id="t1", name="Arbeit", enabled=True, description="Berufliche Themen")
    orchestrator = Orchestrator(
        analyzer=analyzer,
        store=store,
        notifier=notifier,
        chat_id=123,
        topics=[topic],
        max_mail_bytes=50000,
        precheck=None,
        targets=TargetSettings(todoist_project="inbox", google_calendar="primary"),
        user_timezone="UTC",
    )
    mail = FetchedMail(
        folder="INBOX",
        uidvalidity=1,
        uid=88,
        raw=b"Subject: Task Mail\nDate: Wed, 14 Oct 2026 12:00:00 +0000\n\nTask text",
        received_at=datetime(2026, 10, 14, 12, 0, tzinfo=UTC),
    )
    res = orchestrator.process(mail)
    assert res.outcome == ProcessingOutcome.COMPLETED
    assert res.state["steps"]["duplicate_precheck"] == "completed"
