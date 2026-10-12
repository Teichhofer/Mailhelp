"""Vision OCR (1.4) inside the orchestrator: before relevance, once, restart-safe."""
from __future__ import annotations

from mailhelp.config import Topic, VisionSettings
from mailhelp.imap import FetchedMail
from mailhelp.models import IrrelevantSenders, Relevance, VisionExtractionResult
from mailhelp.openrouter import RateLimitExceeded
from mailhelp.orchestrator import Orchestrator, ProcessingOutcome
from mailhelp.storage import JsonStore
from mailhelp.vision import VisionExtractor
from test_vision import Reader, image_bytes, mail, noise

TOPICS = [Topic(id="schule", name="Schule", enabled=True, description="Schule")]
RAW = mail(("flyer.png", "image", "png", image_bytes(noise())),
           ("plan.png", "image", "png", image_bytes(noise())))


class Analyzer:
    """Records the mail the relevance step sees; the mail is irrelevant afterwards."""

    def __init__(self): self.seen = []

    def relevance(self, mail, topics):
        self.seen.append(mail)
        return "relevance-call", Relevance(decision="irrelevant", topic_ids=[], reason="Test")


class Notify:
    def __init__(self): self.messages = []
    def send(self, chat, text): self.messages.append(text)


class Log:
    def __init__(self): self.events = []
    def event(self, level, module, event, **fields): self.events.append((level, event, fields))


def run(store, reader, *, raw=RAW, sender_store=None, log=None, vision=True):
    analyzer = Analyzer()
    orchestrator = Orchestrator(
        analyzer, store, Notify(), 1, TOPICS, 50_000_000, logger=log, sender_store=sender_store,
        vision=VisionExtractor(reader, VisionSettings()) if vision else None)
    result = orchestrator.process(FetchedMail("INBOX", 1, 7, raw))
    return result, analyzer


def test_image_text_reaches_relevance_and_is_logged_without_content(tmp_path):
    reader = Reader(VisionExtractionResult(legible=True, text="Elternabend am 3. März"),
                    ValueError("Zeitüberschreitung"))
    log = Log()
    with JsonStore(tmp_path) as store:
        result, analyzer = run(store, reader, log=log)
    assert result.outcome is ProcessingOutcome.COMPLETED
    flyer, plan = analyzer.seen[0]["extracted_attachments"]
    assert (flyer["vision"], flyer["text"]) == ("read", "Elternabend am 3. März")
    assert plan["vision"] == "failed"
    assert result.state["mail"]["metadata"]["vision"] == "completed"
    assert result.state["llm_call_ids"] == ["call-1", "relevance-call"]
    events = [(level, fields["outcome"], fields["error_type"], fields["characters"])
              for level, event, fields in log.events if event == "vision_attachment"]
    assert events == [("INFO", "read", None, 22), ("WARNING", "failed", "ValueError", 0)]
    assert "Elternabend" not in repr(log.events)


def test_blocked_senders_never_reach_the_vision_model(tmp_path):
    with JsonStore(tmp_path / "state") as store, JsonStore(tmp_path / "config") as senders:
        senders.save("irrelevant-senders", IrrelevantSenders(addresses=["info@schule.example"])
                     .model_dump(mode="json"))
        result, analyzer = run(store, Reader(), sender_store=senders)
    assert result.state["mail"]["metadata"]["vision"] == "skipped_sender"
    assert result.state["relevance"]["reason"] == "Absender-Vorfilter" and analyzer.seen == []


def test_rate_limit_defers_and_resumes_without_reading_twice(tmp_path):
    first = Reader(VisionExtractionResult(legible=True, text="Seite eins"), RateLimitExceeded(0.0))
    with JsonStore(tmp_path) as store:
        result, analyzer = run(store, first)
        assert result.outcome is ProcessingOutcome.WAITING and analyzer.seen == []
        assert "vision" not in result.state["mail"]["metadata"]
        assert result.state["mail"]["extracted_attachments"][0]["vision"] == "read"
        second = Reader(VisionExtractionResult(legible=True, text="Seite zwei"))
        result, analyzer = run(store, second)
    assert second.calls == [("plan.png", "image/png", 1)]
    assert [item["text"] for item in analyzer.seen[0]["extracted_attachments"]] == [
        "Seite eins", "Seite zwei"]
    assert result.state["llm_call_ids"] == ["call-1", "call-1", "relevance-call"]


def test_a_resumed_mail_without_the_original_message_continues_without_images(tmp_path):
    with JsonStore(tmp_path) as store:
        run(store, Reader(RateLimitExceeded(0.0)))
        result, analyzer = run(store, Reader(), raw=b"")
    assert result.state["mail"]["metadata"]["vision"] == "unavailable"
    assert analyzer.seen[0]["extracted_attachments"][0]["extraction_status"] == "unsupported_format"


def test_without_vision_nothing_is_read_or_marked(tmp_path):
    with JsonStore(tmp_path) as store:
        result, _ = run(store, Reader(), vision=False)
    assert "vision" not in result.state["mail"]["metadata"]
    assert all(item.get("vision") is None for item in result.state["mail"]["extracted_attachments"])


def test_finished_vision_is_not_repeated_when_relevance_is_retried(tmp_path):
    class Limited(Analyzer):
        def relevance(self, mail, topics):
            raise RateLimitExceeded(0.0)

    with JsonStore(tmp_path) as store:
        first = Reader(VisionExtractionResult(legible=True, text="A"),
                       VisionExtractionResult(legible=True, text="B"))
        orchestrator = Orchestrator(Limited(), store, Notify(), 1, TOPICS, 50_000_000,
                                    vision=VisionExtractor(first, VisionSettings()))
        assert orchestrator.process(FetchedMail("INBOX", 1, 7, RAW)).outcome is ProcessingOutcome.WAITING
        second = Reader()
        result, analyzer = run(store, second)
    assert second.calls == [] and result.state["mail"]["metadata"]["vision"] == "completed"
    assert [item["text"] for item in analyzer.seen[0]["extracted_attachments"]] == ["A", "B"]


def test_the_mail_page_names_the_vision_outcome_per_attachment():
    from mailhelp.review.views import MailView
    from mailhelp.web.review_pages import mail_section

    html = mail_section(MailView(
        mail_id="m1", sender="Schule <info@schule.example>", subject="Aushang", received="",
        text="Siehe Anhang.", attachments_omitted=0, text_shortened=False,
        extracted_attachments=(
            {"filename": "flyer.jpg", "extraction_status": "success", "vision": "read"},
            {"filename": "icon.png", "extraction_status": "unsupported_format",
             "vision": "skipped_small"},
            {"filename": "neu.png", "extraction_status": "unsupported_format", "vision": "künftig"},
        )))
    assert '<span class="badge ok">Per Bilderkennung gelesen</span>' in html
    assert '<span class="badge warn">Übersprungen (Symbol oder Logo)</span>' in html
    assert '<span class="badge warn">künftig</span>' in html
    assert "Nicht unterstütztes Format" not in html


def test_preparation_caches_private_previews_without_vision(tmp_path):
    """2.0: raster previews exist independently of OCR and are bound to the mail."""
    from mailhelp.attachments import AttachmentCache
    with JsonStore(tmp_path) as store:
        result, _ = run(store, Reader(), vision=False)
        mail_id = result.state["id"]
        assert [item["preview"]["index"] for item in result.state["mail"]["extracted_attachments"]] == [0, 1]
        assert AttachmentCache(store).read(mail_id, 1)[:2] == b"\xff\xd8"


def test_a_failing_preview_never_stops_the_analysis(tmp_path, monkeypatch):
    """Regression: a preview error (full disk, foreign store) must not fail the preparation."""
    def full(*args): raise OSError("disk full")
    monkeypatch.setattr("mailhelp.attachments.AttachmentCache.prepare", full)
    log = Log()
    with JsonStore(tmp_path) as store:
        result, analyzer = run(store, Reader(), vision=False, log=log)
    assert result.outcome is ProcessingOutcome.COMPLETED and analyzer.seen
    assert ("WARNING", "preview_failed", {"mail_id": result.state["id"], "error_class": "OSError"}) in log.events

    class ForeignStore:
        """A store without a data directory (e.g. a wrapper) simply has no previews."""
        def __init__(self, delegate): self.delegate = delegate
        def load(self, *args): return self.delegate.load(*args)
        def save(self, *args): self.delegate.save(*args)
    monkeypatch.undo()
    with JsonStore(tmp_path / "foreign") as store:
        result, analyzer = run(ForeignStore(store), Reader(), vision=False)
    assert result.outcome is ProcessingOutcome.COMPLETED
    assert all("preview" not in item for item in result.state["mail"]["extracted_attachments"])
