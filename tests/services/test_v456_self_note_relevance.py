"""4.5.6: own notes and forwardings are relevant without a topic decision.

Regression: in the real 4.5 evaluation the forwarded "Elternabend" with "Bitte eintragen"
was filed as irrelevant, so no proposal would have been created at all.
"""
from mailhelp.config import Topic
from mailhelp.mailbox.imap import FetchedMail
from mailhelp.models import MailState, Relevance
from mailhelp.processing.perspective import SELF_NOTE_REASON, Perspective
from mailhelp.storage import JsonStore
from tests.fakes.shared_profiles import ACCOUNT_ONE
from tests.fakes.shared_self_mail import orchestrator, own_settings
from tests.fakes.shared_services import AnalyzerStub

FORWARD = ("Bitte eintragen\r\n\r\n-------- Weitergeleitete Nachricht --------\r\n"
           "Betreff: Einladung Elternabend\r\nVon: Grundschule <sekretariat@grundschule.example.test>\r\n\r\n"
           "Der Elternabend findet am 24.11.2026 um 19:30 Uhr in Raum 12 statt.")


class Irrelevant(AnalyzerStub):
    """A topic decision that files every mail away, as observed for the forwarding."""

    def __init__(self):
        super().__init__("irrelevant")
        self.relevance_calls = 0

    def relevance(self, m, t):
        self.relevance_calls += 1
        return super().relevance(m, t)


def process(tmp_path, sender, topics=None):
    raw = (f"From: {sender}\r\nSubject: WG: Einladung Elternabend\r\n"
           f"Date: Sat, 07 Nov 2026 11:00:00 +0000\r\n\r\n{FORWARD}").encode()
    with JsonStore(tmp_path / "data") as store:
        run = orchestrator(store, own_settings(tmp_path))
        run.analyzer = analyzer = Irrelevant()
        if topics is not None:
            run.topics_for = lambda fingerprint, account=None: topics
        result = run.process(FetchedMail("INBOX", 1, 1, raw, account_id=ACCOUNT_ONE))
        name = next(name for name in store.names("analysis-"))
        archived = store.load(name)
    return MailState.model_validate(result.state), analyzer, archived


def test_an_own_forwarding_is_relevant_without_a_relevance_call(tmp_path):
    state, analyzer, archived = process(tmp_path, "Ich <ich@private.example.test>")
    assert state.self_mail and state.is_forwarding
    assert state.relevance == Relevance(decision="relevant", topic_ids=[], reason=SELF_NOTE_REASON)
    assert analyzer.relevance_calls == 0 and archived["source"] == "self_mail"
    # Relevance no longer stops the note: routing and extraction ran and built a proposal.
    assert state.steps.summary == "completed" and [item.kind.value for item in state.proposals] == ["task"]


def test_the_same_forwarding_from_someone_else_still_needs_the_topic_decision(tmp_path):
    state, analyzer, _ = process(tmp_path, "Verein <info@verein.example.test>")
    assert not state.self_mail and state.is_forwarding
    assert state.relevance.decision == "irrelevant" and analyzer.relevance_calls == 1
    assert state.proposals == []


def test_a_mailbox_without_enabled_topics_also_skips_own_notes(tmp_path):
    """Disabling every topic of a mailbox switches its processing off, own notes included."""
    disabled = [Topic(id="aus", name="Aus", enabled=False, description="Aus")]
    state, analyzer, _ = process(tmp_path, "ich@private.example.test", topics=disabled)
    assert state.relevance.reason == "Kein relevantes Thema für dieses Postfach"
    assert analyzer.relevance_calls == 0 and state.proposals == []


def test_only_an_own_sender_makes_a_mail_relevant_by_itself():
    assert Perspective(self_mail=True).own_relevance().decision == "relevant"
    assert Perspective(is_forwarding=True).own_relevance() is None
    assert Perspective().own_relevance() is None
