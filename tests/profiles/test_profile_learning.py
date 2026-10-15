"""Learning proposals retain their origin unless a global scope is explicitly selected."""
import yaml
from shared_profiles import ACCOUNT_ONE, ACCOUNT_TWO

from mailhelp.imap import FetchedMail
from mailhelp.learning import LearningMode, LearningSource
from mailhelp.models import AbstractCategories, IrrelevantSenders, LearnedCategory, MailClassification, Relevance
from mailhelp.storage import JsonStore


class Reader:
    def __init__(self, account, subject):
        self.account_id, self.subject = account, subject
    def fetch_since(self, *args):
        if args[-1]:
            return []
        return [FetchedMail("INBOX", 1, 1, f"From: {self.subject}@example.test\nSubject: {self.subject}\n\nBody".encode(), self.account_id)]


class Classifier:
    def relevance(self, mail, topics):
        return "r", Relevance(decision="irrelevant", topic_ids=[], reason="new")
    def classify_for_learning(self, mail):
        return "classify", MailClassification(categories=[LearnedCategory(name=mail["headers"]["subject"], description="Synthetic")])
    def abstract_learned_categories(self, classifications):
        return "abstract", AbstractCategories(categories=[item for classification in classifications for item in classification.categories])


def test_learning_scopes_categories_and_rejected_senders_to_the_origin(tmp_path):
    one, two = Reader(ACCOUNT_ONE, "private"), Reader(ACCOUNT_TWO, "work")
    answers = iter(["j", "", "n", "invalid", ""])
    output = []
    with JsonStore(tmp_path) as store:
        mode = LearningMode(one, Classifier(), ["INBOX"], 1000, [], tmp_path / "topics.yaml", [],
            tmp_path / "irrelevant_topics.yaml", store, input_fn=lambda _: next(answers), output_fn=output.append,
            scoped_learning=True, sources=[LearningSource(one, ["INBOX"], "imap.mailboxes.0.folders", 1),
                                          LearningSource(two, ["INBOX"], "imap.mailboxes.1.folders", 2)])
        assert mode.run(2) == 1
        assert yaml.safe_load((tmp_path / "topics.yaml").read_text())["topics"][0]["mailboxes"] == [1]
        assert yaml.safe_load((tmp_path / "irrelevant_topics.yaml").read_text())["topics"][0]["mailboxes"] == [2]
        blocked = store.load_model("irrelevant-senders", IrrelevantSenders)
        assert blocked.addresses == [] and blocked.mailboxes["2"].addresses == ["work@example.test"]
        assert any("Ursprungspostfach" in line for line in output)


def test_learning_explicit_global_scope_keeps_topics_global(tmp_path):
    reader, answers = Reader(ACCOUNT_TWO, "work"), iter(["n", "alle"])
    with JsonStore(tmp_path) as store:
        mode = LearningMode(reader, Classifier(), ["INBOX"], 1000, [], tmp_path / "topics.yaml", [],
            tmp_path / "irrelevant_topics.yaml", store, scoped_learning=True,
            sources=[LearningSource(reader, ["INBOX"], "imap.mailboxes.1.folders", 2)],
            input_fn=lambda _: next(answers), output_fn=lambda _: None)
        assert mode.run(1) == 0
        assert "mailboxes" not in yaml.safe_load((tmp_path / "irrelevant_topics.yaml").read_text())["topics"][0]
        assert store.load_model("irrelevant-senders", IrrelevantSenders).addresses == ["work@example.test"]
