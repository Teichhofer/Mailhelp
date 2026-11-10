"""Regression (5.1.7): resuming a mail checks its configuration like processing does.

The resume loop compared a mail's fingerprint with the global one, although since 3.2
every mail carries the fingerprint of its own mailbox. Mails of a mailbox with its own
settings therefore waited forever ("configuration_changed" on every poll), and a
completed mail whose action detection had failed was never retried.
"""
from mailhelp.mailbox.mailbox_run import _checkpoint_name
from mailhelp.models import MailState
from mailhelp.processing.mail_pipeline import ProcessingOutcome
from tests.fakes.shared_application import Imap, Orch, Store, Telegram, app

ACCOUNT = "0" * 24
GLOBAL, MAILBOX, OLD = "a" * 64, "c" * 64, "b" * 64


class MailboxOrch(Orch):
    """Accepts like the real orchestrator: the mailbox's own fingerprint when an account is named."""

    def accepts_configuration(self, fingerprint, account_id=None):
        return fingerprint == (MAILBOX if account_id is not None else GLOBAL)


def state(uid, fingerprint, **steps):
    return MailState(id=f"{uid:024x}", config_fingerprint=fingerprint, steps=steps,
                     imap={"account_id": ACCOUNT, "folder": "INBOX", "uidvalidity": 7, "uid": uid})


def run(tmp_path, *states):
    store = Store({**{f"mail-{item.id}": item.model_dump(mode="json") for item in states},
                   _checkpoint_name(ACCOUNT, "INBOX"): {"uidvalidity": 7, "uid": 9, "start_uid": 1}})
    service = app(tmp_path, Imap([(7, [])]), Telegram([]), MailboxOrch(config_fingerprint=GLOBAL), store=store)
    results = service.mailbox.poll(max_mails=5)
    warnings = [event for event in service.logger.events if event[0][2] == "configuration_changed"]
    return service, results, warnings


def test_an_unfinished_mail_with_its_mailbox_fingerprint_is_resumed(tmp_path):
    service, results, warnings = run(tmp_path, state(3, MAILBOX))
    assert service.orchestrator.seen == [3] and warnings == []
    assert [result.outcome for result in results] == [ProcessingOutcome.COMPLETED]


def test_a_completed_mail_with_a_failed_action_detection_is_retried_under_an_older_configuration(tmp_path):
    failed = state(4, OLD, preparation="completed", relevance="completed", action_detection="failed",
                   completion="completed")
    service, _, warnings = run(tmp_path, failed)
    assert service.orchestrator.seen == [4] and warnings == []


def test_an_unfinished_mail_of_an_older_configuration_still_waits(tmp_path):
    service, results, warnings = run(tmp_path, state(5, OLD))
    assert service.orchestrator.seen == [] and len(warnings) == 1
    assert [result.outcome for result in results] == [ProcessingOutcome.WAITING]
