"""7.7.2: VIP senders, ignore rules and header filters decide before any model call (Planung 7.7, 3.1, 5)."""
from __future__ import annotations

from datetime import UTC, datetime

from mailhelp.config import Topic
from mailhelp.domain.mail import MailState
from mailhelp.domain.relevance import HeaderPrefilter, IrrelevantSenders, PrefilterHits, SenderRule
from mailhelp.mailbox.imap import FetchedMail
from mailhelp.mailbox.sender_filter import LISTS
from mailhelp.persistence.storage import JsonStore
from mailhelp.processing.orchestrator import Orchestrator, ProcessingOutcome
from mailhelp.review.explanation import explain
from tests.fakes.shared_services import AnalyzerStub, Notify

NOW = datetime(2026, 11, 17, 12, tzinfo=UTC)
TOPICS = [Topic(id="schule", name="Schule", enabled=True, description="Schule"),
          Topic(id="aus", name="Aus", enabled=False, description="Aus")]


class Counting(AnalyzerStub):
    def __init__(self, decision="relevant"):
        super().__init__(decision)
        self.relevance_calls = 0

    def relevance(self, mail, topics):
        self.relevance_calls += 1
        return super().relevance(mail, topics)


def rule(kind, value, action="ignore", **fields):
    return SenderRule(id=SenderRule.identity(kind, value, None), kind=kind, value=value, action=action,
                      created_at=NOW, **fields)


def raw(sender, subject="Hallo", extra=b"", uid=1):
    return (f"From: {sender}\nSubject: {subject}\nMessage-ID: <m{uid}@example.test>\n".encode()
            + extra + b"\nBitte bis Freitag das Formular abgeben.")


def process(store, analyzer, message, uid=1):
    orchestrator = Orchestrator(analyzer, store, Notify(), 1, TOPICS, 1000)
    return orchestrator.process(FetchedMail("INBOX", 1, uid, message))


def rules(store, *items, **fields):
    store.save("irrelevant-senders", IrrelevantSenders(rules=list(items), **fields).model_dump(mode="json"))


def hits(store):
    return store.load_model("prefilter-hits", PrefilterHits, PrefilterHits())


def test_a_vip_sender_skips_only_the_relevance_call_and_keeps_the_confirmation(tmp_path):
    vip = rule("domain", "schule.test", action="vip", topic_ids=["schule", "aus", "weg"])
    with JsonStore(tmp_path) as store:
        rules(store, vip, rule("subject", "formular"), domains=["schule.test"])
        analyzer = Counting("irrelevant")
        result = process(store, analyzer, raw("Lehrerin <lehrerin@mail.schule.test>", "Formular"))
        state = MailState.model_validate(result.state)
        assert analyzer.relevance_calls == 0 and state.prefilter_rule == vip.id
        assert state.relevance.decision == "relevant" and state.relevance.topic_ids == ["schule"]
        assert state.relevance.reason == "VIP-Absender: schule.test"
        # A forged VIP gains nothing beyond that: the proposal still waits for an explicit confirmation.
        assert state.steps.summary == "completed" and [p.status.value for p in state.proposals] == [
            "pending_confirmation"]
        assert hits(store).rules[vip.id].count == 1
        relevance = next(step for step in explain(state).steps if step.key == "relevance")
        assert relevance.text == "Als relevant eingestuft. VIP-Absender: schule.test – ohne KI-Aufruf."
        assert relevance.model_reason is None


def test_an_ignore_rule_files_the_mail_without_any_model_call(tmp_path):
    pattern = rule("pattern", "no-reply@*")
    with JsonStore(tmp_path) as store:
        rules(store, pattern)
        analyzer = Counting()
        result = process(store, analyzer, raw("Bank <No-Reply@bank.test>"))
        state = MailState.model_validate(result.state)
        assert result.outcome is ProcessingOutcome.COMPLETED and analyzer.relevance_calls == 0
        assert state.relevance.decision == "irrelevant" and state.relevance.reason == "Vorfilter: no-reply@*"
        assert state.llm_call_ids == [] and state.proposals == [] and state.steps.summary == "skipped"
        # The same mail again is a duplicate; the rule is never counted twice for it.
        process(store, analyzer, raw("Bank <No-Reply@bank.test>"))
        assert hits(store).rules[pattern.id].count == 1 and hits(store).rules[pattern.id].last is not None


def test_header_filters_decide_only_when_switched_on(tmp_path):
    newsletter = b"List-Unsubscribe: <https://shop.test/ab>\n"
    with JsonStore(tmp_path) as store:
        analyzer = Counting()
        process(store, analyzer, raw("Shop <news@shop.test>", extra=newsletter), uid=1)
        assert analyzer.relevance_calls == 1
        rules(store, headers=HeaderPrefilter(lists="on"))
        state = MailState.model_validate(process(store, analyzer, raw("Shop <news@shop.test>", extra=newsletter,
                                                                      uid=2), uid=2).state)
        assert analyzer.relevance_calls == 1 and state.prefilter_rule == LISTS
        assert state.relevance.reason == "Vorfilter: Newsletter oder Verteiler" and hits(store).rules[LISTS].count == 1


def test_without_a_matching_rule_the_model_decides_as_before(tmp_path):
    with JsonStore(tmp_path) as store:
        rules(store, rule("address", "andere@schule.test", action="vip"))
        analyzer = Counting()
        state = MailState.model_validate(process(store, analyzer, raw("a@b.test")).state)
    assert analyzer.relevance_calls == 1 and state.prefilter_rule is None and state.relevance.reason == "why"
    assert next(step for step in explain(state).steps if step.key == "relevance").model_reason == "why"


def test_the_decision_test_follows_subject_and_vip_rules(tmp_path):
    """Acceptance 7.7 (5.5): the decision test reaches the same prefilter result as the pipeline."""
    from mailhelp.domain.relevance import Relevance
    from mailhelp.llm.decision_test import ComparisonRecorder, DecisionTestMode
    from tests.fakes.shared_decision_test import Reader, settings

    class Classifier:
        def relevance(self, mail, topics):
            return "model", Relevance(decision="relevant", topic_ids=[], reason="Modell")

    def stages(blocked):
        report = {"mails": [], "selection_errors": []}
        mode = DecisionTestMode(Reader(), Classifier(), Classifier(), settings(), TOPICS, report,
                                tmp_path / "out.json",
                                ComparisonRecorder(tmp_path / "comparison.jsonl", ()), relevance_only=True,
                                blocked_senders=blocked)
        assert mode.run(1) == 0
        return {path["stages"]["relevance"]["call_id"] for path in report["mails"][0]["paths"].values()}

    assert stages(IrrelevantSenders(rules=[rule("subject", "synthetic comparison")])) == {"prefilter"}
    vip = IrrelevantSenders(rules=[rule("address", "sender@example.test", action="vip")],
                            addresses=["sender@example.test"])
    assert stages(vip) == {"model"}


def test_a_header_trial_only_counts_and_an_exception_is_never_counted(tmp_path):
    newsletter = b'List-Id: "Schule" <Eltern.Schule.test>\nList-Unsubscribe: <https://x>\n'
    with JsonStore(tmp_path) as store:
        rules(store, headers=HeaderPrefilter(lists="trial", trial_since={"lists": NOW}))
        analyzer = Counting()
        state = MailState.model_validate(process(store, analyzer, raw("a@schule.test", extra=newsletter)).state)
        assert analyzer.relevance_calls == 1 and state.prefilter_rule is None and state.relevance.reason == "why"
        assert hits(store).trial[LISTS].count == 1 and hits(store).rules == {}
        rules(store, headers=HeaderPrefilter(lists="trial", trial_since={"lists": NOW},
                                             list_exceptions=["<eltern.schule.test>"]))
        process(store, analyzer, raw("a@schule.test", extra=newsletter, uid=2), uid=2)
        assert analyzer.relevance_calls == 2 and hits(store).trial[LISTS].count == 1
