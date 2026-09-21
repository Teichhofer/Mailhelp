from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage
from threading import Barrier, Lock

import pytest
import yaml

from mailhelp.config import Topic
from mailhelp.imap import FetchedMail, FolderNotReadable, MailCandidate
from mailhelp.learning import LearningMode, _safe_terminal, _topic_id, save_topics
from mailhelp.models import AbstractCategories, LearnedCategory, MailClassification, Relevance
from mailhelp.analysis import Analyzer as RealAnalyzer, LlmProviderResponseInvalid


def raw_mail(subject: str, sender: str | None = None) -> bytes:
    message = EmailMessage()
    message["Subject"] = subject
    if sender is not None:
        message["From"] = sender
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
    def __init__(self, categories, relevance_decisions=None):
        self.categories = categories
        self.mails = []
        self.abstract_inputs = []
        self.relevance_decisions = iter(relevance_decisions or [])
        self.relevance_topics = []

    def relevance(self, mail, topics):
        self.relevance_topics.append((mail, topics))
        result = next(self.relevance_decisions, "irrelevant")
        decision = result if result in {"irrelevant", "unclear"} else "relevant"
        topic_ids = [result] if decision == "relevant" else []
        return "relevance", Relevance(decision=decision, topic_ids=topic_ids, reason="test")

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
    mails = [FetchedMail("INBOX", 1, uid, raw_mail(str(uid), "Shop <offers@example.test>"), received_at=stamp)
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
    irrelevant_path = tmp_path / "irrelevant_topics.yaml"
    path.write_text("topics: []\n", encoding="utf-8")
    mode = LearningMode(imap, analyzer, ["INBOX"], 10000, [topic()], path,
                        [], irrelevant_path,
                        input_fn=lambda _prompt: next(answers), output_fn=output.append)

    assert mode.run(2) == 1
    assert len(imap.calls) == 2
    assert imap.calls[1][-1] == ((3, 3),)
    assert len(analyzer.mails) == 2 and len(analyzer.abstract_inputs) == 1
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))["topics"]
    assert [item["id"] for item in saved] == ["bestand", "amter-fristen"]
    irrelevant = yaml.safe_load(irrelevant_path.read_text(encoding="utf-8"))["topics"]
    assert [item["id"] for item in irrelevant] == ["werbung"]
    assert any("Bitte mit j" in line for line in output)
    assert all("\x1b" not in line for line in output)


def test_learning_fetches_globally_newest_messages(tmp_path):
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fetched = []

    class GlobalImap:
        def discover_since(self, folder, **kwargs):
            assert kwargs == {"max_count": 1, "historical_start": None}
            hour = {"INBOX": 1, "Archive": 3}[folder]
            return [MailCandidate(folder, 9, hour, "0" * 24,
                                  stamp.replace(hour=hour))]
        def fetch_uid(self, folder, uid, validity):
            fetched.append((folder, uid, validity))
            return FetchedMail(folder, validity, uid, raw_mail(folder), received_at=stamp)

    mode = LearningMode(
        GlobalImap(), Analyzer([]), ["INBOX", "Archive"], 1000, [],
        tmp_path / "topics.yaml", [], tmp_path / "irrelevant_topics.yaml",
        output_fn=lambda _line: None, global_newest_first=True,
    )
    assert mode.run(1) == 0
    assert fetched == [("Archive", 3, 9)]


def test_learning_skips_unreadable_folders_during_discovery_and_fetch(tmp_path):
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    output = []

    class ChangingImap:
        def discover_since(self, folder, **_kwargs):
            if folder == "Drafts\x1b":
                raise FolderNotReadable(folder)
            uid = 2 if folder == "Vanished" else 1
            return [MailCandidate(folder, 9, uid, "0" * 24, stamp)]

        def fetch_uid(self, folder, uid, validity):
            if folder == "Vanished":
                raise FolderNotReadable(folder)
            return FetchedMail(folder, validity, uid, raw_mail(folder), received_at=stamp)

    mode = LearningMode(
        ChangingImap(), Analyzer([]), ["INBOX", "Drafts\x1b", "Vanished"], 1000, [],
        tmp_path / "topics.yaml", [], tmp_path / "irrelevant_topics.yaml",
        output_fn=output.append, global_newest_first=True,
    )

    assert mode.run(3) == 0
    assert any('"Drafts�" ist nicht lesbar' in line for line in output)
    assert any('"Vanished" ist nicht mehr lesbar' in line for line in output)


@pytest.mark.parametrize("historical", [False, True])
def test_folder_ordered_learning_skips_unreadable_folder(tmp_path, historical):
    boundary = datetime(2026, 1, 1, tzinfo=timezone.utc)
    output = []

    class PartlyReadable(Imap):
        def determine_start_uid(self, folder, _start):
            if folder == "Drafts":
                raise FolderNotReadable(folder)
            return 0

        def fetch_since(self, folder, *args):
            if folder == "Drafts":
                raise FolderNotReadable(folder)
            return super().fetch_since(folder, *args)

    imap = PartlyReadable([[]])
    mode = LearningMode(
        imap, Analyzer([]), ["Drafts", "INBOX"], 1000, [],
        tmp_path / "topics.yaml", [], tmp_path / "irrelevant_topics.yaml",
        output_fn=output.append, historical_start=boundary if historical else None,
    )

    assert mode.run(1) == 0
    assert any('"Drafts" ist nicht lesbar' in line for line in output)
    assert imap.calls == [("INBOX", 0, None, 1, ())]


def test_folder_ordered_learning_applies_historical_boundary(tmp_path):
    boundary = datetime(2026, 1, 1, tzinfo=timezone.utc)
    calls = []

    class HistoricalImap(Imap):
        def determine_start_uid(self, folder, start):
            calls.append((folder, start))
            return 41

    imap = HistoricalImap([[]])
    mode = LearningMode(
        imap, Analyzer([]), ["INBOX"], 1000, [], tmp_path / "topics.yaml", [],
        tmp_path / "irrelevant_topics.yaml", output_fn=lambda _line: None,
        historical_start=boundary,
    )
    assert mode.run(1) == 0
    assert calls == [("INBOX", boundary)]
    assert imap.calls == [("INBOX", 41, None, 1, ())]


def test_learning_bounds_each_folder_and_orders_ties_deterministically(tmp_path):
    stamp = datetime(2026, 1, 2, tzinfo=timezone.utc)
    boundary = stamp.replace(hour=1)
    calls = []
    fetched = []

    class WindowedImap:
        def discover_since(self, folder, **kwargs):
            calls.append((folder, kwargs))
            values = {
                "INBOX": [(8, stamp.replace(hour=4)), (9, stamp.replace(hour=5))],
                "Archive": [(4, stamp.replace(hour=5))],
                "Empty": [],
            }[folder]
            return [MailCandidate(folder, 7, uid, "0" * 24, received)
                    for uid, received in values]

        def fetch_uid(self, folder, uid, validity):
            fetched.append((folder, uid, validity))
            return FetchedMail(folder, validity, uid, raw_mail(str(uid)),
                               received_at=stamp)

    mode = LearningMode(
        WindowedImap(), Analyzer([]), ["INBOX", "Archive", "Empty"], 1000, [],
        tmp_path / "topics.yaml", [], tmp_path / "irrelevant_topics.yaml",
        output_fn=lambda _line: None, global_newest_first=True,
        historical_start=boundary,
    )
    assert mode.run(5) == 0
    assert calls == [(folder, {"max_count": 5, "historical_start": boundary})
                     for folder in ("INBOX", "Archive", "Empty")]
    # Equal times use higher UID first, then configured folder order.  Fewer
    # than N available messages are fetched exactly once and without writes.
    assert fetched == [("INBOX", 9, 7), ("Archive", 4, 7), ("INBOX", 8, 7)]


def test_learning_sender_prefilter_skips_before_relevance(tmp_path):
    from mailhelp.models import IrrelevantSenders
    from mailhelp.storage import JsonStore

    analyzer = Analyzer([])
    mail = FetchedMail("INBOX", 1, 1, raw_mail("sale", "Sender <ad@blocked.test>"))
    with JsonStore(tmp_path / "state") as store:
        store.save("irrelevant-senders", IrrelevantSenders(
            domains=["blocked.test"]
        ).model_dump())
        mode = LearningMode(
            Imap([[mail]]), analyzer, ["INBOX"], 1000, [topic()], tmp_path / "topics.yaml",
            [], tmp_path / "irrelevant_topics.yaml", store, output_fn=lambda _line: None,
        )
        assert mode.run(1) == 0
    assert analyzer.relevance_topics == []


@pytest.mark.parametrize(
    ("content", "quarantine_suffix"),
    [("{", ".corrupt"), ('{"schema_version": 1, "addresses": [3]}', ".invalid")],
)
def test_learning_recovers_from_corrupt_optional_sender_filter(
        tmp_path, content, quarantine_suffix):
    from mailhelp.storage import JsonStore

    analyzer = Analyzer([LearnedCategory(name="Einzel", description="Neue Kategorie")])
    output = []
    state = tmp_path / "state"
    state.mkdir()
    (state / "irrelevant-senders.json").write_text(content, encoding="utf-8")
    mail = FetchedMail("INBOX", 1, 1, raw_mail("sale", "Shop <offer@example.test>"))

    with JsonStore(state) as store:
        mode = LearningMode(
            Imap([[mail]]), analyzer, ["INBOX"], 1000, [], tmp_path / "topics.yaml",
            [], tmp_path / "irrelevant_topics.yaml", store,
            input_fn=lambda _prompt: "nein", output_fn=output.append,
        )
        assert mode.run(1) == 0
        assert store.load("irrelevant-senders")["addresses"] == ["offer@example.test"]

    assert (state / f"irrelevant-senders{quarantine_suffix}").exists()
    assert any("Absenderfilter wurde isoliert" in line for line in output)


def test_learning_records_sender_of_rejected_individual_topic(tmp_path):
    from mailhelp.storage import JsonStore

    analyzer = Analyzer([LearnedCategory(name="Einzel", description="Einzelbeschreibung")])
    mail = FetchedMail("INBOX", 1, 1, raw_mail("sale", "Shop <offer@example.test>"))
    with JsonStore(tmp_path / "state") as store:
        mode = LearningMode(
            Imap([[mail]]), analyzer, ["INBOX"], 1000, [], tmp_path / "topics.yaml",
            [], tmp_path / "irrelevant_topics.yaml", store,
            input_fn=lambda _prompt: "nein", output_fn=lambda _line: None,
        )
        assert mode.run(1) == 0
        assert store.load("irrelevant-senders")["addresses"] == ["offer@example.test"]

        unchanged = LearningMode(
            Imap([[FetchedMail("INBOX", 1, 2, raw_mail("sale"))]]), analyzer,
            ["INBOX"], 1000, [], tmp_path / "topics.yaml", [],
            tmp_path / "irrelevant_topics.yaml", store,
            input_fn=lambda _prompt: "nein", output_fn=lambda _line: None,
        )
        assert unchanged.run(1) == 0
        assert store.load("irrelevant-senders")["addresses"] == ["offer@example.test"]


def test_learning_maps_abstract_rejection_and_contains_mapping_failures(tmp_path):
    from mailhelp.storage import JsonStore

    mails = [FetchedMail("INBOX", 1, uid, raw_mail(str(uid), f"s{uid}@example.test"))
             for uid in (1, 2, 3)]

    class MappingAnalyzer(Analyzer):
        def classify_for_learning(self, mail):
            if mail["headers"]["subject"] == "1":
                raise RuntimeError("bad mail")
            return super().classify_for_learning(mail)

        def relevance(self, mail, topics):
            if mail["headers"]["subject"] == "3":
                raise RuntimeError("mapping unavailable")
            return "mapping", Relevance(
                decision="relevant", topic_ids=[topics[0].id], reason="mapped"
            )

    analyzer = MappingAnalyzer([LearnedCategory(name="Abstrakt", description="Werbung")])
    with JsonStore(tmp_path / "state") as store:
        mode = LearningMode(
            Imap([mails]), analyzer, ["INBOX"], 1000, [], tmp_path / "topics.yaml",
            [], tmp_path / "irrelevant_topics.yaml", store,
            input_fn=lambda _prompt: "nein", output_fn=lambda _line: None,
        )
        assert mode.run(3) == 0
        assert store.load("irrelevant-senders")["addresses"] == ["s2@example.test"]

def test_learning_empty_mailbox_and_all_rejected_do_not_write(tmp_path):
    path = tmp_path / "topics.yaml"
    irrelevant_path = tmp_path / "irrelevant_topics.yaml"
    path.write_text("original", encoding="utf-8")
    output = []
    empty = LearningMode(Imap([[]]), Analyzer([]), ["INBOX"], 1000, [topic()], path,
                         [], irrelevant_path,
                         output_fn=output.append)
    assert empty.run(1) == 0
    assert path.read_text() == "original"

    analyzer = Analyzer([LearnedCategory(name="Nein", description="Nein")])
    rejected = LearningMode(Imap([[FetchedMail("INBOX", 1, 1, raw_mail("x"))]]),
                            analyzer, ["INBOX"], 1000, [topic()], path,
                            [], irrelevant_path,
                            input_fn=lambda _prompt: "no", output_fn=output.append)
    assert rejected.run(1) == 0
    assert path.read_text() == "original"
    assert yaml.safe_load(irrelevant_path.read_text(encoding="utf-8"))["topics"][0]["id"] == "nein"


def test_learning_skips_mails_matching_relevant_or_irrelevant_topics(tmp_path):
    mails = [FetchedMail("INBOX", 1, uid, raw_mail(str(uid))) for uid in (1, 2, 3)]
    analyzer = Analyzer(
        [LearnedCategory(name="Neu", description="Neu")],
        # Mail 1 matches the relevant list, mail 2 the irrelevant list, and
        # mail 3 misses the combined list and is freely classified.
        ["known-relevant", "known-irrelevant", "irrelevant"],
    )
    relevant = topic("known-relevant")
    irrelevant = topic("known-irrelevant")
    mode = LearningMode(
        Imap([mails]), analyzer, ["INBOX"], 1000, [relevant], tmp_path / "topics.yaml",
        [irrelevant], tmp_path / "irrelevant_topics.yaml",
        input_fn=lambda _prompt: "ja", output_fn=lambda _line: None,
    )

    assert mode.run(3) == 1
    assert len(analyzer.relevance_topics) == 3
    assert [[topic.id for topic in topics] for _mail, topics in analyzer.relevance_topics] == [
        ["known-relevant", "known-irrelevant"],
        ["known-relevant", "known-irrelevant"],
        ["known-relevant", "known-irrelevant"],
    ]
    assert len(analyzer.mails) == 1


def test_learning_does_not_call_relevance_for_disabled_or_empty_sets(tmp_path):
    mail = FetchedMail("INBOX", 1, 1, raw_mail("neu"))
    analyzer = Analyzer([])
    disabled = Topic(id="aus", name="Aus", enabled=False, description="Aus")
    mode = LearningMode(
        Imap([[mail]]), analyzer, ["INBOX"], 1000, [], tmp_path / "topics.yaml",
        [disabled], tmp_path / "irrelevant_topics.yaml", output_fn=lambda _line: None,
    )
    assert mode.run(1) == 0
    assert analyzer.relevance_topics == []


def test_learning_parallelizes_first_stage_and_preserves_result_order(tmp_path):
    mails = [FetchedMail("INBOX", 1, uid, raw_mail(str(uid))) for uid in (1, 2)]
    barrier = Barrier(2)
    lock = Lock()

    class ParallelAnalyzer(Analyzer):
        def classify_for_learning(self, mail):
            barrier.wait(timeout=2)
            with lock:
                self.mails.append(mail)
            return "call", MailClassification(categories=[LearnedCategory(
                name=mail["headers"]["subject"], description="Beschreibung")])

    analyzer = ParallelAnalyzer([])
    mode = LearningMode(
        Imap([mails]), analyzer, ["INBOX"], 1000, [], tmp_path / "topics.yaml",
        [], tmp_path / "irrelevant_topics.yaml", parallel_llm_calls=2,
        output_fn=lambda _line: None,
    )

    assert mode.run(2) == 0
    assert [item.categories[0].name for item in analyzer.abstract_inputs[0]] == ["1", "2"]


def test_learning_skips_failed_mail_and_keeps_successful_results(tmp_path):
    mails = [FetchedMail("INBOX", 1, uid, raw_mail(str(uid))) for uid in (1, 2)]

    class PartlyFailingAnalyzer(Analyzer):
        def classify_for_learning(self, mail):
            if mail["headers"]["subject"] == "1":
                raise RuntimeError("must not be displayed")
            return super().classify_for_learning(mail)

    analyzer = PartlyFailingAnalyzer([
        LearnedCategory(name="Erfolg", description="Beschreibung")
    ])
    output = []
    mode = LearningMode(
        Imap([mails]), analyzer, ["INBOX"], 1000, [], tmp_path / "topics.yaml",
        [], tmp_path / "irrelevant_topics.yaml", input_fn=lambda _prompt: "ja",
        output_fn=output.append,
    )

    assert mode.run(2) == 1
    assert len(analyzer.abstract_inputs[0]) == 1
    assert any("1 Mail(s)" in line for line in output)
    assert all("must not be displayed" not in line for line in output)


def test_learning_uses_individual_categories_when_abstraction_fails(tmp_path):
    mail = FetchedMail("INBOX", 1, 1, raw_mail("neu"))

    class AbstractionFailure(Analyzer):
        def abstract_learned_categories(self, classifications):
            raise LlmProviderResponseInvalid("learning_abstraction", "output_token_limit")

    analyzer = AbstractionFailure([])
    output = []
    mode = LearningMode(
        Imap([[mail]]), analyzer, ["INBOX"], 1000, [], tmp_path / "topics.yaml",
        [], tmp_path / "irrelevant_topics.yaml", input_fn=lambda _prompt: "ja",
        output_fn=output.append,
    )

    assert mode.run(1) == 1
    saved = yaml.safe_load((tmp_path / "topics.yaml").read_text(encoding="utf-8"))
    assert saved["topics"][0]["id"] == "einzel"
    assert any("Einzelklassifikationen" in line for line in output)
    assert all("output_token_limit" not in line for line in output)


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
