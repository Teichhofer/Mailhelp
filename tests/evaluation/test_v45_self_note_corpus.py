"""4.5, step 16.5: the self-note cases reach the model exactly as in the pipeline."""
import json
from copy import deepcopy
from pathlib import Path

from mailhelp.llm.evaluation import evaluate
from tests.fakes.prompt_gate_fakes import repository_prompts
from tests.fakes.shared_quality_corpus import ExpectedAnswers

CORPUS = Path(__file__).parents[1] / "fixtures" / "mail_corpus_v3" / "corpus.json"
SELF_NOTES = {"32_self_note_photo_invitation", "33_forwarded_invitation_please_add", "34_self_note_task"}


class Recording(ExpectedAnswers):
    def __init__(self, corpus):
        super().__init__(corpus)
        self.payloads = []

    def complete(self, model, parameters, system, payload, **metadata):
        self.payloads.append((metadata.get("stage"), deepcopy(payload)))
        return super().complete(model, parameters, system, payload, **metadata)


def run():
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    provider = Recording(corpus)
    report = evaluate(corpus, repository_prompts(), provider, 10_000)
    return corpus, provider, report


def mails(provider, subject, stage):
    return [payload["mail"] for name, payload in provider.payloads
            if name == stage and payload["mail"]["headers"]["subject"] == subject]


def test_self_notes_pass_the_gate_and_carry_the_users_perspective():
    corpus, provider, report = run()
    assert report["passed"] and {case["id"] for case in report["cases"]} >= SELF_NOTES
    (photo,) = mails(provider, "Landesversammlung", "action_router")
    assert photo["perspective"] == {"self_mail": True, "user_note": "Ich bin angemeldet und nehme teil.\n\n"
                                    "Von meinem iPhone gesendet", "is_forwarding": False, "forwarded_headers": None}
    # The text read from the photo reaches routing and extraction like vision OCR output.
    assert "am Samstag, 5. Dezember 2026, 9:30 Uhr" in photo["text"]
    assert mails(provider, "Landesversammlung", "event_extraction") == [photo]
    (forward,) = mails(provider, "WG: Einladung Elternabend Klasse 3b", "event_extraction")
    assert forward["perspective"]["user_note"] == "Bitte eintragen"
    assert forward["perspective"]["forwarded_headers"]["sender"] == "Grundschule <sekretariat@grundschule.example.test>"
    (task,) = mails(provider, "Notiz Projektmeeting", "task_extraction")
    assert task["perspective"]["self_mail"] is True
    # Relevance and summary receive the plain mail; other senders never get a perspective.
    assert all("perspective" not in mail for stage in ("relevance", "summary")
               for mail in mails(provider, "Landesversammlung", stage))
    other = [payload["mail"] for name, payload in provider.payloads if name == "action_router"
             and payload["mail"]["headers"]["from"] != "Alex Muster <alex.muster@example.test>"]
    assert other and not any("perspective" in mail and mail["perspective"]["self_mail"] for mail in other)


def test_without_own_addresses_the_notes_are_read_as_foreign_mail():
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    corpus.pop("own_addresses")
    provider = Recording(corpus)
    evaluate(corpus, repository_prompts(), provider, 10_000)
    (photo,) = mails(provider, "Landesversammlung", "action_router")
    assert "perspective" not in photo
    (forward,) = mails(provider, "WG: Einladung Elternabend Klasse 3b", "action_router")
    assert forward["perspective"]["self_mail"] is False and forward["perspective"]["user_note"] is None


def test_only_named_image_attachments_receive_recognized_text():
    from mailhelp.llm.evaluation import _recognized_images
    mail = {"extracted_attachments": [
        {"filename": "foto.jpg", "text": "", "extraction_status": "unsupported_format", "character_count": 0},
        {"filename": "plan.pdf", "text": "Plan", "extraction_status": "success", "character_count": 4}]}
    _recognized_images(mail, {"foto.jpg": "Termin am 5.12."})
    assert mail["extracted_attachments"] == [
        {"filename": "foto.jpg", "text": "Termin am 5.12.", "extraction_status": "success", "character_count": 15,
         "vision": "read"},
        {"filename": "plan.pdf", "text": "Plan", "extraction_status": "success", "character_count": 4}]
    empty = {}
    _recognized_images(empty, {"foto.jpg": "x"})
    assert empty == {}
