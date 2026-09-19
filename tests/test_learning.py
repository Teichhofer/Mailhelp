from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage

import pytest
import yaml

from mailhelp.config import Topic
from mailhelp.imap import FetchedMail
from mailhelp.learning import LearningMode, _safe_terminal, _topic_id, save_topics
from mailhelp.models import AbstractCategories, LearnedCategory, MailClassification
from mailhelp.analysis import Analyzer as RealAnalyzer


def raw_mail(subject: str) -> bytes:
    message = EmailMessage()
    message["Subject"] = subject
    message.set_content("Synthetischer Inhalt")
    return message.as_bytes()


class Imap:
    def __init__(self, batches):
        self.batches = iter(batches)
        self.calls = []

    def fetch_since(self, *args):
        self.calls.append(args)
        return next(self.batches)


class Analyzer:
    def __init__(self, categories):
        self.categories = categories
        self.mails = []
        self.abstract_inputs = []

    def classify_for_learning(self, mail):
        self.mails.append(mail)
        return "call", MailClassification(categories=[LearnedCategory(
            name="Einzel", description="Einzelbeschreibung")])

    def abstract_learned_categories(self, classifications):
        self.abstract_inputs.append(classifications)
        return "call", AbstractCategories(categories=self.categories)


def topic(identifier="bestand"):
    return Topic(id=identifier, name="Bestand", enabled=True, description="Schon da")


def test_learning_fetches_batches_prompts_and_saves_only_accepted(tmp_path):
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    mails = [FetchedMail("INBOX", 1, uid, raw_mail(str(uid)), received_at=stamp)
             for uid in (3, 2)]
    imap = Imap([[mails[0]], [mails[1]]])
    categories = [
        LearnedCategory(name="Ämter & Fristen", description="\x1bBehördliches", examples=["Antrag"]),
        LearnedCategory(name="Werbung", description="Angebote"),
    ]
    analyzer = Analyzer(categories)
    answers = iter(["vielleicht", "ja", "n"])
    output = []
    path = tmp_path / "topics.yaml"
    path.write_text("topics: []\n", encoding="utf-8")
    mode = LearningMode(imap, analyzer, ["INBOX"], 10000, [topic()], path,
                        input_fn=lambda _prompt: next(answers), output_fn=output.append)

    assert mode.run(2) == 1
    assert len(imap.calls) == 2
    assert imap.calls[1][-1] == ((3, 3),)
    assert len(analyzer.mails) == 2 and len(analyzer.abstract_inputs) == 1
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))["topics"]
    assert [item["id"] for item in saved] == ["bestand", "amter-fristen"]
    assert any("Bitte mit j" in line for line in output)
    assert all("\x1b" not in line for line in output)


def test_learning_empty_mailbox_and_all_rejected_do_not_write(tmp_path):
    path = tmp_path / "topics.yaml"
    path.write_text("original", encoding="utf-8")
    output = []
    empty = LearningMode(Imap([[]]), Analyzer([]), ["INBOX"], 1000, [topic()], path,
                         output_fn=output.append)
    assert empty.run(1) == 0
    assert path.read_text() == "original"

    analyzer = Analyzer([LearnedCategory(name="Nein", description="Nein")])
    rejected = LearningMode(Imap([[FetchedMail("INBOX", 1, 1, raw_mail("x"))]]),
                            analyzer, ["INBOX"], 1000, [topic()], path,
                            input_fn=lambda _prompt: "no", output_fn=output.append)
    assert rejected.run(1) == 0
    assert path.read_text() == "original"


def test_topic_ids_collision_fallback_and_atomic_cleanup(tmp_path, monkeypatch):
    used = {"thema", "thema-2", "a" * 60}
    assert _topic_id("***", used) == "thema-3"
    assert _topic_id("a" * 100, used).endswith("-2")
    assert _safe_terminal("ok\n\x00") == "ok\n�"
    path = tmp_path / "topics.yaml"
    monkeypatch.setattr("mailhelp.learning.os.replace", lambda *_args: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError, match="disk"):
        save_topics(path, [topic()], [LearnedCategory(name="Neu", description="Neu")])
    assert not list(tmp_path.iterdir())


def test_analyzer_learning_stages_pass_validated_payloads():
    analyzer = object.__new__(RealAnalyzer)
    calls = []
    classification = MailClassification(categories=[
        LearnedCategory(name="A", description="B")])
    analyzer._run = lambda *args: calls.append(args) or ("one", classification)
    analyzer._classified_run = lambda *args: calls.append(args) or (
        "two", AbstractCategories(categories=[]))

    assert analyzer.classify_for_learning({"text": "mail"})[0] == "one"
    assert analyzer.abstract_learned_categories([classification])[0] == "two"
    assert calls[0][0] == "learning_classification"
    assert calls[1][0] == "learning_abstraction"
    assert calls[1][1] == {"classifications": [classification.model_dump()]}
