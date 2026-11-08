"""4.5, step 16.5: the self-note cases reach the model exactly as in the pipeline."""
import json
from copy import deepcopy
from pathlib import Path

from mailhelp.llm.evaluation import evaluate, semantic_result
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
    # 4.5.6: own notes need no relevance call; the summary receives the plain mail.
    for subject in ("Landesversammlung", "WG: Einladung Elternabend Klasse 3b", "Notiz Projektmeeting"):
        assert mails(provider, subject, "relevance") == []
    (summary,) = mails(provider, "Landesversammlung", "summary")
    assert "perspective" not in summary
    observed = {case["id"]: case["review_outputs"]["relevance"] for case in report["cases"]}
    assert all(observed[case] == {"decision": "relevant", "topic_ids": [],
                                  "reason": "Eigene Notiz: immer relevant"} for case in SELF_NOTES)
    # Other senders never get a perspective.
    other = [payload["mail"] for name, payload in provider.payloads if name == "action_router"
             and payload["mail"]["headers"]["from"] != "Alex Muster <alex.muster@example.test>"]
    assert other and not any("perspective" in mail and mail["perspective"]["self_mail"] for mail in other)


def test_without_own_addresses_the_notes_are_read_as_foreign_mail():
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    corpus.pop("own_addresses")
    for case in corpus["cases"]:
        if case["id"] in SELF_NOTES:  # A topic decision of foreign mail always names a topic.
            case["expected"]["relevance"] = {"decision": "relevant", "topic_ids": ["arbeit"], "reason": "fremd"}
    provider = Recording(corpus)
    evaluate(corpus, repository_prompts(), provider, 10_000)
    (photo,) = mails(provider, "Landesversammlung", "action_router")
    assert "perspective" not in photo
    # Read as foreign mail, the note goes through the topic decision again.
    assert len(mails(provider, "Landesversammlung", "relevance")) == 1
    (forward,) = mails(provider, "WG: Einladung Elternabend Klasse 3b", "action_router")
    assert forward["perspective"]["self_mail"] is False and forward["perspective"]["user_note"] is None


def test_a_leading_weekday_does_not_change_the_compared_date():
    """Regression 4.5.6: the real model wrote "Samstag, 5. Dezember 2026" and was counted as wrong."""
    from mailhelp.llm.evaluation import _day
    from mailhelp.proposals.action_normalization import MailDateContext

    def when(date_text):
        event = {"title": "Termin", "evidence": "x", "date_text": date_text, "time_text": "9:30 Uhr",
                 "time_requirement": "timed", "responsibility": "user", "certainty": "certain",
                 "classification": "new", "location": "Saal"}
        result = semantic_result("event_extraction", {"events": [event]}, MailDateContext(
            date_context_status="missing", date_header_parsed=None, imap_received_at=None, user_timezone=None))
        return result["events"][0]["when"]["date"]

    assert when("Samstag, 5. Dezember 2026") == when("5. Dezember 2026") == "5. dezember 2026"
    assert when("Di. 24.11.2026") == when("Dienstag, 24.11.2026") == "24.11.2026"
    # Only a weekday in front of a day number is dropped.
    assert _day("Samstag nach dem Fest") == "samstag nach dem fest" and _day(None) is None
    assert _day("Sonntagsbrunch 3.5.") == "sonntagsbrunch 3.5."


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
