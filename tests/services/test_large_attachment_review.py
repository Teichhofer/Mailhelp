"""Large attachments must produce durable local review proposals, never block later letters."""
from email.message import EmailMessage

import pytest
from shared_services import Notify, Writer

from mailhelp.attachment_extractor import extract_attachment_text
from mailhelp.config import TargetSettings
from mailhelp.imap import FetchedMail
from mailhelp.integrations import execute_confirmed
from mailhelp.mail_pipeline import ProcessingRun
from mailhelp.mime import MimeLimits
from mailhelp.models import Proposal
from mailhelp.orchestrator import Orchestrator, ProcessingOutcome
from mailhelp.review.views import ReviewViews
from mailhelp.storage import JsonStore
from mailhelp.web.review_pages import proposal_card


@pytest.mark.parametrize("size,status", [(5_000_000, "success"), (5_000_001, "skipped_oversized")])
def test_five_mb_extraction_boundary(size, status):
    extracted = extract_attachment_text("letter.txt", "text/plain", b"a" * size)
    assert extracted.extraction_status == status


def test_large_attachment_always_has_one_review_proposal_after_restart(tmp_path):
    message = EmailMessage()
    message["From"] = "school@example.test"
    message["Subject"] = "Berufsvorstellung"
    message.set_content("Bitte den Anhang lesen.")
    message.add_attachment(b"x" * 5_000_001, maintype="application", subtype="pdf", filename="Einladung.pdf")
    fetched = FetchedMail("INBOX", 1, 1, message.as_bytes())
    notifier = Notify()
    with JsonStore(tmp_path) as store:
        # No LLM service: a missing/failing provider must not hide this review entry.
        processor = Orchestrator(object(), store, notifier, 1, [], 100_000)
        result = processor.process(fetched)
        assert result.outcome == ProcessingOutcome.COMPLETED
        proposal, = result.state["proposals"]
        assert "manuell prüfen" in proposal["title"].lower()
        assert "Einladung.pdf" in proposal["description"]
        assert proposal["status"] == "pending_confirmation"
        assert proposal["external_id"] is None and not result.state["write_attempts"]
        writer = Writer()
        with pytest.raises(ValueError):
            execute_confirmed(Proposal.model_validate(proposal), writer, lambda item: None)
        assert writer.created == 0
        assert not result.state["llm_call_ids"]
        assert result.state["mail"]["extracted_attachments"][0]["extraction_status"] == "skipped_oversized"
        assert len(notifier.messages) == 1
        view, = ReviewViews(store, "UTC").overview().open
        assert "Nachricht manuell prüfen" in proposal_card(view)
        assert view.proposal_id == proposal["id"]
        assert processor.process(fetched).state["proposals"] == [proposal]
    with JsonStore(tmp_path) as store:
        restarted = Orchestrator(object(), store, notifier, 1, [], 100_000)
        assert restarted.process(fetched).state["proposals"] == [proposal]
        assert len(notifier.messages) == 1


@pytest.mark.parametrize("kind", ["pdf", "png", "ics", "txt"])
def test_custom_limit_applies_before_any_ocr_llm_or_calendar_extraction(tmp_path, kind):
    message = EmailMessage()
    message.set_content("Inhalt ohne Handlungsbedarf.")
    message.add_attachment(b"x" * 1025, maintype="application", subtype="octet-stream", filename=f"file.{kind}")
    with JsonStore(tmp_path) as store:
        processor = Orchestrator(object(), store, Notify(), 1, [], 100_000, vision=object(),
                                 targets=TargetSettings(task_provider="microsoft_todo", google_calendar="primary",
                                                        microsoft_todo_list="review-list"),
                                 mime_limits=MimeLimits(100_000, max_attachment_bytes=1024))
        result = processor.process(FetchedMail("INBOX", 1, 1, message.as_bytes()))
        assert result.outcome == ProcessingOutcome.COMPLETED
        assert result.state["proposals"][0]["target"] == "review-list"
        assert not result.state["mail"]["calendar_events"]
        assert not result.state["llm_call_ids"]


def test_omitted_iserv_attachment_is_listed_and_uncertain_notification_is_not_repeated(tmp_path):
    class InterruptedNotify(Notify):
        def send_proposal(self, proposal):
            super().send_proposal(proposal)
            raise RuntimeError("Synthetic interruption after delivery")

    message = EmailMessage()
    message.set_content("Einladung mit großem Anhang.")
    fetched = FetchedMail("Elternbriefe", 1, 1, message.as_bytes(),
                          oversized_attachments=(("Einladung.pdf", "application/pdf", 5_000_001),))
    notifier = InterruptedNotify()
    with JsonStore(tmp_path) as store:
        processor = Orchestrator(object(), store, notifier, 1, [], 100_000)
        failed = processor.process(fetched)
        assert failed.outcome == ProcessingOutcome.FAILED
        proposal, = failed.state["proposals"]
        assert "Einladung.pdf" in proposal["description"]
        assert failed.state["proposal_notifications"][0]["status"] == "sending"
    with JsonStore(tmp_path) as store:
        processor = Orchestrator(object(), store, notifier, 1, [], 100_000)
        resumed = processor.process(fetched)
        assert resumed.outcome == ProcessingOutcome.COMPLETED
        assert resumed.state["proposals"] == [proposal]
        assert notifier.messages.count(proposal["id"]) == 1


def test_review_uses_the_saved_target_profile_after_preparation_restart(tmp_path):
    message = EmailMessage()
    message.set_content("Brief")
    fetched = FetchedMail("Elternbriefe", 1, 1, message.as_bytes(),
                          oversized_attachments=(("Termin.pdf", "application/pdf", 5_000_001),))
    with JsonStore(tmp_path) as store:
        processor = Orchestrator(object(), store, Notify(), 1, [], 100_000)
        run = processor._begin(fetched)
        assert isinstance(run, ProcessingRun)
        processor.pipeline._prepare(run, fetched)
        run.state.proposal_policy.update(
            targets=TargetSettings(task_provider="microsoft_todo", google_calendar="primary",
                                   microsoft_todo_list="profile-7-list").model_dump(), target_profile=7)
        processor.save(run.name, run.state)
        result = processor.process(fetched)
        assert result.outcome == ProcessingOutcome.COMPLETED
        proposal, = result.state["proposals"]
        assert proposal["target_profile"] == 7 and proposal["target"] == "profile-7-list"
        assert proposal["target_provider"] == "microsoft_todo"
