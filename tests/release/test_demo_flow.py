"""7.6: every proposal of the shipped demo can be decided at once – no question slows the visitor down.

The dataset comes from a real pipeline run (``devtools.demo.dataset``); this check fails as soon as a
later change to prompts, models or processing brings an open question back into the demo.
"""
from __future__ import annotations

import json

from mailhelp.domain.mail import MailState
from mailhelp.domain.proposal import ProposalStatus
from mailhelp.runtime.demo_dataset import packaged, verify


def demo_states() -> list[MailState]:
    directory = verify(packaged()) and packaged()
    return [MailState.model_validate(json.loads(path.read_text(encoding="utf-8")))
            for path in sorted((directory / "state").glob("mail-*.json"))]


def test_all_demo_proposals_are_ready_for_confirmation():
    proposals = [proposal for state in demo_states() for proposal in state.proposals]
    assert len(proposals) >= 6, "Zu wenige Vorschläge im Demo-Bestand"
    for proposal in proposals:
        assert proposal.status == ProposalStatus.PENDING_CONFIRMATION, (proposal.title, proposal.status)
        assert proposal.open_questions == [], (proposal.title, proposal.open_questions)


def test_no_demo_mail_waits_for_a_relevance_decision():
    states = demo_states()
    assert all(state.relevance is not None and state.relevance.decision != "unclear" for state in states)
    assert not any(state.awaiting_relevance for state in states)


def test_the_demo_prepares_no_answers_because_nothing_is_asked():
    assert json.loads((packaged() / "answers.json").read_text(encoding="utf-8")) == []
