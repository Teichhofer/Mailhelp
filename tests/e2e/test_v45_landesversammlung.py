"""4.5, step 16.7: regression for the "Landesversammlung" self-note (synthesized).

In November 2026 the user sent three photos of a printed invitation from their iPhone
to their own mailbox with "Ich bin angemeldet und nehme teil." The router answered
"none": it read the photos as an older invitation to someone else. All names,
addresses and texts here are synthetic; only the structure follows the real mail.
"""
from datetime import datetime
from email.message import EmailMessage

import pytest

from mailhelp.mailbox.imap import FetchedMail
from mailhelp.models import ActionRoute, EventExtraction, ExtractedEvent, MailState
from mailhelp.processing.vision import VisionUpdate
from mailhelp.storage import JsonStore
from tests.fakes.shared_profiles import ACCOUNT_ONE
from tests.fakes.shared_self_mail import orchestrator, own_settings
from tests.fakes.shared_services import AnalyzerStub

pytestmark = pytest.mark.e2e

PAGES = [
    "EINLADUNG zur Landesversammlung des Landesverbands",
    "am Samstag, 5. Dezember 2026, 9:30 Uhr im Gasthof Krone, Hauptstraße 1, Hohenstadt",
    "Tagesordnung: Berichte, Wahlen, Anträge. Wir bitten um Anmeldung bis 20. November 2026.",
]


def raw_mail(sender: str) -> bytes:
    message = EmailMessage()
    message["From"], message["To"] = sender, "ich@private.example.test"
    message["Date"], message["Subject"] = "Sat, 07 Nov 2026 10:00:00 +0100", "Landesversammlung"
    message.set_content("Ich bin angemeldet und nehme teil.\n\nVon meinem iPhone gesendet\n")
    for number in range(3):
        message.add_attachment(b"\xff\xd8\xff\xe0synthetic" + bytes([number]) + b"\xff\xd9",
                               maintype="image", subtype="jpeg", filename=f"IMG_47{number}.JPG")
    return message.as_bytes()


class Vision:
    """Recognized text of each photo, in the shape processing.vision stores."""

    def extract(self, raw, attachments):
        for index, attachment in enumerate(attachments):
            yield VisionUpdate(index, {**attachment, "text": PAGES[index], "extraction_status": "success",
                                       "character_count": len(PAGES[index]), "vision": "read"}, f"vision-{index}")


class Model(AnalyzerStub):
    """Answers as the sharpened prompts require; without the perspective as observed in 2026."""

    def __init__(self):
        super().__init__("relevant")
        self.inputs = []

    def action_route(self, mail):
        self.inputs.append(mail)
        perspective = mail.get("perspective") or {}
        if perspective.get("self_mail") and "teil" in (perspective.get("user_note") or ""):
            return "ar", ActionRoute(action_state="event", task_count=0, event_count=1,
                                     reason="Die nutzende Person hält ihre eigene Teilnahme fest.")
        return "ar", ActionRoute(action_state="none", task_count=0, event_count=0,
                                 reason="Bestätigt lediglich die eigene Anmeldung des Absenders.")

    def extract_events(self, mail, *, expected_count):
        assert mail["perspective"]["self_mail"] and "5. Dezember 2026, 9:30 Uhr" in str(mail)
        return "e", EventExtraction(events=[ExtractedEvent(
            title="Landesversammlung", evidence=PAGES[1], date_text="Samstag, 5. Dezember 2026",
            time_text="9:30 Uhr", time_requirement="timed", location="Gasthof Krone, Hauptstraße 1, Hohenstadt",
            responsibility="user", certainty="certain", classification="new")])


def process(tmp_path, sender):
    with JsonStore(tmp_path / "data") as store:
        run = orchestrator(store, own_settings(tmp_path))
        run.analyzer, run.vision = model, _ = Model(), Vision()
        run.user_timezone = "Europe/Berlin"
        arrived = datetime.fromisoformat("2026-11-07T10:01:00+01:00")
        result = run.process(FetchedMail("INBOX", 1, 1, raw_mail(sender), account_id=ACCOUNT_ONE,
                                         received_at=arrived))
    return MailState.model_validate(result.state), model


def test_the_self_note_with_invitation_photos_becomes_a_confirmable_appointment(tmp_path):
    state, model = process(tmp_path, "Ich <ich@private.example.test>")
    assert state.self_mail and state.user_note.startswith("Ich bin angemeldet und nehme teil.")
    (routed,) = model.inputs
    # The router receives the recognized photos (the analyzer appends them to the text).
    assert [item["text"] for item in routed["extracted_attachments"]] == PAGES
    (proposal,) = state.proposals
    assert (proposal.kind.value, proposal.responsibility, proposal.classification) == ("event", "user", "new")
    assert proposal.known_temporal_facts.start.isoformat() == "2026-12-05T09:30:00+01:00"
    assert proposal.location == "Gasthof Krone, Hauptstraße 1, Hohenstadt"
    # Unchanged rule: without a recognizable meeting mode no standard duration applies,
    # so the end time is the only open fact. The appointment itself is no longer lost.
    assert proposal.meeting_mode == "unknown" and proposal.open_questions == ["Wann endet der Termin?"]


def test_the_same_mail_from_an_unknown_address_still_yields_no_appointment(tmp_path):
    """Without the own address the model reads the mail from a third person's view."""
    state, model = process(tmp_path, "Fremd <fremd@example.test>")
    assert not state.self_mail and state.proposals == []
    assert "perspective" not in model.inputs[0]
