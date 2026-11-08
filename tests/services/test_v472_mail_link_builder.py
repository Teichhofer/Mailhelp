"""4.7, step 18.3: the link to the original mail in task and event descriptions."""
import pytest
from pydantic import ValidationError

from mailhelp.mailbox.imap import FetchedMail
from mailhelp.models import MailState, Proposal
from mailhelp.persistence.ledger import ActionLedgerService
from mailhelp.storage import JsonStore
from tests.fakes.proposal_builder_fakes import builder, event, task
from tests.fakes.shared_profiles import ACCOUNT_ONE
from tests.fakes.shared_self_mail import orchestrator, own_settings

LINK = "message://%3Cabc.123@mail.example.test%3E"


def built(link, **changes):
    made = builder(**changes)
    made.mail_link = link
    return made.build([task(description="Bitte Unterlagen prüfen")], [event()])


def test_a_task_gets_a_markdown_link_and_an_event_the_bare_link():
    task_proposal, event_proposal = built(LINK)
    assert task_proposal.description.endswith(f"\n📧 [Original-E-Mail öffnen]({LINK})")
    assert event_proposal.description.endswith(f"\n📧 Original-E-Mail öffnen: {LINK}")
    assert task_proposal.mail_link == event_proposal.mail_link == LINK


def test_the_link_changes_neither_the_proposal_ids_nor_the_ledger_identity():
    with_link, without = built(LINK), built(None)
    assert [item.id for item in with_link] == [item.id for item in without]
    assert "📧" not in without[0].description and without[0].mail_link is None
    # The same task from another mail (another link) is still recognised as the same action.
    other = built("message://%3Cother@mail.example.test%3E")
    assert ActionLedgerService.action_key(with_link[0]) == ActionLedgerService.action_key(without[0]) == (
        ActionLedgerService.action_key(other[0]))


def test_a_long_description_is_shortened_so_that_the_link_stays():
    made = builder()
    made.mail_link = LINK
    (proposal,) = made.build([task(description="x" * 4000)], [])  # the longest extracted description
    assert len(proposal.description) == 4000 and proposal.description.endswith(f"({LINK})")


@pytest.mark.parametrize("link", ["javascript:alert(1)", "message://%3Ca b@c%3E", "https://evil.example.test/x",
                                  'message://%3C"x"@y%3E', "message://<x@y>"])
def test_only_links_built_by_mailhelp_are_stored(link):
    (proposal, _) = built(None)
    with pytest.raises(ValidationError):
        Proposal.model_validate({**proposal.model_dump(mode="json"), "mail_link": link})


def process(tmp_path, *, message_id, host=None, legacy=False):
    raw = (f"From: Verein <info@verein.example.test>\r\nSubject: Einladung\r\n"
           f"Date: Sat, 07 Nov 2026 10:00:00 +0000\r\n{message_id}\r\nAm 5.12. um 9:30 Uhr.").encode()
    cfg = own_settings(tmp_path)
    if host is not None:
        data = cfg.model_dump(mode="json")
        data["imap"]["mailboxes"][0]["host"] = host
        cfg = type(cfg).model_validate(data)
    with JsonStore(tmp_path / "data") as store:
        run = orchestrator(store, cfg)
        if legacy:
            original = run.pipeline._prepare

            def prepare(work, fetched):
                original(work, fetched)
                work.state.proposal_policy.pop("mail_link_kind")  # as stored before 4.7

            run.pipeline._prepare = prepare
        state = MailState.model_validate(run.process(FetchedMail("INBOX", 1, 1, raw, account_id=ACCOUNT_ONE)).state)
    return state.proposals[0]


def test_the_mailbox_server_chooses_the_link_kind(tmp_path):
    gmail = process(tmp_path / "g", message_id="Message-ID: <CAF+1@mail.gmail.com>\r\n", host="imap.gmail.com")
    assert gmail.mail_link == "https://mail.google.com/mail/u/0/#search/rfc822msgid%3ACAF%2B1%40mail.gmail.com"
    other = process(tmp_path / "o", message_id="Message-ID: <a1@verein.example.test>\r\n")
    assert other.mail_link == "message://%3Ca1@verein.example.test%3E"


def test_without_a_message_id_or_from_before_4_7_there_is_no_link(tmp_path):
    missing = process(tmp_path / "m", message_id="")
    assert missing.mail_link is None and "📧" not in missing.description
    legacy = process(tmp_path / "l", message_id="Message-ID: <a1@verein.example.test>\r\n", legacy=True)
    assert legacy.mail_link is None
