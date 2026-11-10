"""5.2 V1: a written, not yet verified entry is booked, protected and shown, never written again."""
from datetime import UTC, datetime, timedelta

from mailhelp.config import RetentionSettings
from mailhelp.domain.mail import MailState
from mailhelp.runtime.retention import RetentionService
from tests.fakes.log_fakes import RecordingLogger
from tests.scenarios.web_scenario import mail_id, proposal, save_mail


def test_the_ledger_books_a_verifying_entry_so_a_duplicate_is_recognized(web):
    written = proposal(30, "a", title="Unterlagen senden", status="verifying", external_id="todo-7")
    save_mail(web.store, 30, "Schule <schule@example.test>", "Unterlagen", [written])
    web.dialog.persist(written)
    assert [entry.external_id for entry in web.dialog.ledger.prior_actions(
        written.model_copy(update={"id": "b", "status": "pending_confirmation", "external_id": None}))] == ["todo-7"]


def test_retention_keeps_the_content_of_a_mail_with_a_verifying_entry(web):
    written = proposal(31, "a", status="verifying", external_id="todo-8")
    save_mail(web.store, 31, "Schule <schule@example.test>", "Unterlagen", [written], text="Inhalt",
              steps=dict(preparation="completed", completion="completed"))
    now = datetime.now(UTC) + timedelta(days=400)
    RetentionService(web.store, RetentionSettings(full_mail_days=1), RecordingLogger(), lambda: now).run()
    assert web.store.load_model(f"mail-{mail_id(31)}", MailState).mail is not None


def test_the_card_names_the_verification_state(web):
    written = proposal(32, "a", title="Unterlagen senden", status="verifying", external_id="todo-9")
    save_mail(web.store, 32, "Schule <schule@example.test>", "Unterlagen", [written])
    page = web.browser.request("GET", f"/vorschlag/{mail_id(32)}/a").body.decode()
    assert '<span class="badge accent">Gespeichert – Eintrag wird geprüft</span>' in page
