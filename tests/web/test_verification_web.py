"""5.2 V9: the check of a written entry in the web and in Telegram, and the protected read-only recheck."""
from datetime import date

from mailhelp import state_names
from mailhelp.domain.verification import VerificationState
from mailhelp.external.confirmed import execute_confirmed
from mailhelp.external.ical import CalendarFileWriter
from mailhelp.models import Proposal, ProposalStatus
from tests.fakes.shared_telegram_dialog import Telegram, callback
from tests.fakes.shared_web_actions import web as web  # noqa: F401 - the fixture
from tests.fakes.verifying_writer import SimulatedProvider, VerifyingWriter
from tests.scenarios.web_scenario import mail_id, proposal, save_mail

MAIL = mail_id(40)


def written(web, script, number=40, pid="a"):
    """A confirmed task written through the verifying flow; the first read follows *script*."""
    provider = SimulatedProvider()
    item = proposal(number, pid, title="Unterlagen senden", status="confirmed", confirmed_web_actor=None,
                    due=date(2026, 11, 11))
    save_mail(web.store, number, "Schule <schule@example.test>", "Unterlagen", [item])
    writer = VerifyingWriter(provider, script=script)
    web.dialog.writers["todoist"] = writer
    web.dialog.write_executor.execute(item)
    return provider, writer


def current(web, pid="a", number=40):
    return web.store.load_model(state_names.proposal(mail_id(number), pid), Proposal)


def page(web, pid="a", number=40):
    web.site.refresh_overview()
    return web.browser.request("GET", f"/vorschlag/{mail_id(number)}/{pid}").body.decode()


def test_a_deviation_is_shown_with_expected_and_actual_and_can_be_checked_again(web):
    provider, writer = written(web, [{"due": "2026-11-12"}])
    html = page(web)
    assert "Eintrag vorhanden, Angaben weichen ab" in html and "Erneut prüfen" in html
    assert ('<tr><th scope="row">Fälligkeit</th><td>11.11.2026</td><td>12.11.2026</td></tr>' in html)
    assert "Verwerfen" not in html  # a written entry is never rejected from here
    fields = web.form(f"/vorschlag/{MAIL}/a", kind="verify_entry")
    assert fields["version"] == "1" and fields["csrf"] and fields["key"]
    assert web.submit(fields).status == 303
    web.run()
    checks = web.dialog.write_executor.verification
    assert checks.load(current(web)).state == VerificationState.VERIFIED  # the fixed entry, read again
    assert current(web).status == ProposalStatus.CREATED and provider.writes == [f"mailhelp:{MAIL}:a:v1"]
    html = page(web)
    assert "Angelegt und geprüft" in html and "Frisch beim Anbieter geprüft am" in html
    assert "Erneut prüfen" not in html


def test_a_repeated_or_stale_recheck_has_no_second_effect(web):
    _provider, _writer = written(web, [None, None, None, None, None])
    checks = web.dialog.write_executor.verification
    record = checks.load(current(web))
    checks._save(record.model_copy(update={"state": VerificationState.NOT_FOUND, "next_check_at": None,
                                           "last_error": "not_visible"}))
    html = page(web)
    assert "Eintragung noch nicht bestätigt" in html and "Der Eintrag ist beim Anbieter nicht auffindbar" in html
    fields = web.form(f"/vorschlag/{MAIL}/a", kind="verify_entry")
    first, again = web.submit(fields), web.submit(fields)
    assert first.status == again.status == 303 and first.headers["Location"] == again.headers["Location"]
    web.run()
    assert checks.load(current(web)).attempts == 1  # restarted once, then one read
    old = dict(fields, key="b" * 32, version="2")
    assert web.submit(old).status == 409
    web.site.refresh_overview()
    assert web.submit(dict(fields, key="c" * 32)).status == 409  # no recheck offered while one runs


def test_a_recheck_needs_a_valid_session_when_it_runs(web):
    written(web, [{"title": "anders"}])
    fields = web.form(f"/vorschlag/{MAIL}/a", kind="verify_entry")
    assert web.submit(dict(fields, csrf="falsch")).status == 403
    web.submit(fields)
    web.dialog.review.web_authorizer = lambda actor: False  # signed out before the operator ran it
    web.run()
    checks = web.dialog.write_executor.verification
    assert checks.load(current(web)).state == VerificationState.MISMATCH


def test_a_recheck_is_refused_without_a_finished_check(web):
    written(web, [None])
    checks = web.dialog.write_executor.verification
    web.dialog.write_executor.verification = None
    item = current(web)
    from mailhelp.review.commands import CommandKind, CommandSource, ReviewCommand
    command = ReviewCommand(kind=CommandKind.VERIFY_ENTRY, source=CommandSource.TELEGRAM, actor="telegram:1:2",
                            mail_id=MAIL, proposal_id="a", version=item.version, idempotency_key="k" * 32)
    assert web.dialog.review.execute(command).status.value == "stale"
    web.dialog.write_executor.verification = checks
    assert web.dialog.review.execute(command.model_copy(update={"idempotency_key": "m" * 32})).status.value == "stale"
    assert web.dialog.review.execute(command.model_copy(update={"version": 5, "idempotency_key": "n" * 32})
                                     ).status.value == "stale"
    assert "Nachprüfung ausstehend – nächster Versuch" in page(web)


def test_telegram_offers_a_version_bound_recheck_for_the_authorized_chat(web):
    written(web, [{"due": None}])
    chat, text, markup = web.telegram.sent[-1]
    assert text.startswith("⚠️ Eintrag vorhanden, Angaben weichen ab") and chat == 2
    token = markup["inline_keyboard"][0][0]["callback_data"]
    web.telegram.updates = [callback(100, token, user=9)]  # another user: no effect
    web.run()
    checks = web.dialog.write_executor.verification
    assert checks.load(current(web)).state == VerificationState.MISMATCH
    web.telegram.updates = [callback(101, token)]
    web.run()
    web.telegram.updates = []
    web.run()
    assert checks.load(current(web)).state == VerificationState.VERIFIED
    assert web.telegram.sent[-1][1].startswith("✅ Angelegt und geprüft")


def test_the_overview_badge_and_a_calendar_file_name_the_check(web):
    written(web, [])
    web.site.refresh_overview()
    overview = web.browser.request("GET", "/").body.decode()
    assert "Angelegt und geprüft</span>" in overview
    item = proposal(41, "f", kind="event", title="Elternabend", status="confirmed", confirmed_web_actor=None,
                    target="telegram", start=date(2026, 12, 1), end=date(2026, 12, 2), all_day=True)
    save_mail(web.store, 41, "Schule <schule@example.test>", "Elternabend", [item])
    execute_confirmed(item, CalendarFileWriter(Telegram(), 2), web.dialog.persist,
                      verification=web.dialog.write_executor.verification)
    html = page(web, "f", 41)
    assert "Kalenderdatei bereitgestellt – Übernahme in den Kalender nicht prüfbar" in html
    assert "Erneut prüfen" not in html


def test_a_web_confirmation_reports_a_pending_check_not_a_created_entry(web):
    from mailhelp.review.commands import CommandKind, CommandSource, ReviewCommand
    item = proposal(42, "c", title="Formular", status="pending_confirmation", due=date(2026, 11, 11))
    save_mail(web.store, 42, "Schule <schule@example.test>", "Formular", [item])
    web.dialog.writers["todoist"] = VerifyingWriter(SimulatedProvider(), script=[None])
    actor = "web:synthetische-sitzung"
    web.dialog.review.web_authorizer = lambda value: value == actor
    result = web.dialog.review.execute(ReviewCommand(
        kind=CommandKind.CONFIRM, source=CommandSource.WEB, actor=actor, mail_id=mail_id(42), proposal_id="c",
        version=1, idempotency_key="v" * 32))
    assert result.message == "Gespeichert – der Eintrag wird beim Anbieter geprüft."
    assert current(web, "c", 42).status == ProposalStatus.VERIFYING
