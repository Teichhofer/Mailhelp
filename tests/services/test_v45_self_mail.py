"""4.5, step 16.1: mail from the user's own addresses is marked as a self-note."""
import pytest
from pydantic import ValidationError

from mailhelp.config import Settings
from mailhelp.mailbox.imap import FetchedMail
from mailhelp.models import MailState
from mailhelp.processing.identity import NOTE_LIMIT, addresses_in, is_self_mail, sender_addresses, user_note
from mailhelp.processing.orchestrator import Orchestrator
from mailhelp.storage import JsonStore
from tests.fakes.shared_profiles import ACCOUNT_ONE, ACCOUNT_TWO, TOPICS, settings
from tests.fakes.shared_self_mail import orchestrator, own_settings
from tests.fakes.shared_services import AnalyzerStub, Notify

NOTE = "Ich bin angemeldet und nehme teil.\r\n\r\nVon meinem iPhone gesendet"


def raw(sender: str, text: str = NOTE) -> bytes:
    return (f"From: {sender}\r\nSubject: Landesversammlung\r\n"
            f"Date: Sat, 07 Nov 2026 10:00:00 +0000\r\n\r\n{text}").encode()


@pytest.mark.parametrize(("sender", "account"), [
    ("Ich <ich@private.example.test>", ACCOUNT_ONE),          # IMAP user name
    ("ALIAS@private.example.test", ACCOUNT_ONE),             # configured alias, any case
    ("Notiz <notiz@privat.example.test>", ACCOUNT_ONE),      # address in personal_info
    ("Büro <buero@work.example.test>", ACCOUNT_TWO),          # mailbox-specific personal_info
])
def test_mail_from_an_own_address_is_a_self_note_with_the_users_words(tmp_path, sender, account):
    cfg = own_settings(tmp_path)
    with JsonStore(tmp_path / "data") as store:
        state = MailState.model_validate(orchestrator(store, cfg).process(
            FetchedMail("INBOX", 1, 1, raw(sender), account_id=account)).state)
        assert state.self_mail is True
        assert state.user_note.startswith("Ich bin angemeldet und nehme teil.")
        assert MailState.model_validate(store.load(f"mail-{state.id}")).self_mail is True


@pytest.mark.parametrize(("sender", "account"), [
    ("Verein <info@verein.example.test>", ACCOUNT_ONE),
    ("ich@private.example.test", ACCOUNT_TWO),                # another mailbox's address
    ('"ich@private.example.test" <fremd@example.test>', ACCOUNT_ONE),  # display name never counts
    ("ich@private.example.test, fremd@example.test", ACCOUNT_ONE),     # several senders
])
def test_other_senders_are_read_as_before(tmp_path, sender, account):
    cfg = own_settings(tmp_path)
    with JsonStore(tmp_path / "data") as store:
        state = MailState.model_validate(orchestrator(store, cfg).process(
            FetchedMail("INBOX", 1, 1, raw(sender), account_id=account)).state)
        assert state.self_mail is False and state.user_note is None


def test_without_mailbox_settings_or_with_a_removed_mailbox_nothing_is_own(tmp_path):
    cfg = own_settings(tmp_path, personal_info="")
    with JsonStore(tmp_path / "data") as store:
        plain = Orchestrator(AnalyzerStub("relevant"), store, Notify(), 1, TOPICS, cfg.limits)
        assert plain.own_addresses(ACCOUNT_ONE) == frozenset()
        run = orchestrator(store, cfg)
        run.mailbox_numbers = {ACCOUNT_ONE: 7, ACCOUNT_TWO: 2}
        assert run.own_addresses(ACCOUNT_ONE) == frozenset()
        assert run.own_addresses(ACCOUNT_TWO) == {"buero@work.example.test"}


def test_an_empty_self_note_has_no_note(tmp_path):
    cfg = own_settings(tmp_path)
    with JsonStore(tmp_path / "data") as store:
        state = MailState.model_validate(orchestrator(store, cfg).process(
            FetchedMail("INBOX", 1, 1, raw("ich@private.example.test", "   "), account_id=ACCOUNT_ONE)).state)
        assert state.self_mail is True and state.user_note is None


def test_address_helpers_are_strict_and_bounded():
    assert addresses_in(["A@B.example", None, "", "kein Text", "x@y.test und Z@Y.TEST"]) == {
        "a@b.example", "x@y.test", "z@y.test"}
    assert sender_addresses("Name <keine-adresse>") == frozenset()
    assert not is_self_mail("", frozenset({"a@b.example"}))
    assert user_note(None) is None
    assert user_note("x" * (NOTE_LIMIT + 10)) == "x" * NOTE_LIMIT


def test_own_addresses_must_be_addresses(tmp_path):
    cfg = settings(tmp_path).model_dump(mode="json")
    cfg["imap"]["mailboxes"][0]["own_addresses"] = ["kein-alias"]
    with pytest.raises(ValidationError):
        Settings.model_validate(cfg)
    cfg["imap"]["mailboxes"][0]["own_addresses"] = [f"a{index}@x.test" for index in range(21)]
    with pytest.raises(ValidationError):
        Settings.model_validate(cfg)
