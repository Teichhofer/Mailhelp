"""Channel-neutral review layer: commands, service, read models and the store lock."""
from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from mailhelp.adapter import PermanentError, UncertainWriteError
from mailhelp.domain.processing import (
    AnswerStatus,
    ProposalClarificationState,
    ProposalRevisionStatus,
    TelegramOutboxEntry,
    TelegramOutboxGate,
    TelegramOutboxState,
)
from mailhelp.models import (
    ActionLedger,
    ActionLedgerEntry,
    DisplayHeaders,
    MailRunCounters,
    MailRunEntry,
    MailRunState,
    TelegramDialogState,
)
from mailhelp.review import CommandKind, CommandSource, ResultStatus, ReviewCommand, StaleCommand
from mailhelp.review.cards import card_content, yes_no_question
from mailhelp.review.views import RECENT_LIMIT, ReviewViews
from mailhelp.storage import CorruptState, JsonStore
from mailhelp.telegram.ledger import ActionLedgerService

action_key = ActionLedgerService.action_key
from shared_review import command as command
from shared_review import mail_state as mail_state
from shared_review import setup as setup
from shared_review import web as web
from shared_telegram_dialog import RelevanceHandler, Writer, controller, proposal, relevance_state

MAIL = "a" * 24
OTHER = "b" * 24
TELEGRAM = "telegram:1:2"
EVENT = dict(kind="event", start="2026-10-21T12:30:00+02:00", end="2026-10-21T15:30:00+02:00",
             target="calendar")










# --- commands -----------------------------------------------------------------

@pytest.mark.parametrize("changes", [
    {"kind": CommandKind.CONFIRM, "proposal_id": None},
    {"kind": CommandKind.RELEVANCE, "proposal_id": "p1", "decision": "relevant"},
    {"kind": CommandKind.ANSWER, "proposal_id": "p1"},
    {"kind": CommandKind.ANSWER, "proposal_id": "p1", "text": "   "},
    {"kind": CommandKind.CONFIRM, "proposal_id": "p1", "text": "ja"},
    {"kind": CommandKind.RELEVANCE, "proposal_id": None},
    {"kind": CommandKind.REJECT, "proposal_id": "p1", "decision": "relevant"},
    {"kind": CommandKind.REJECT, "proposal_id": "p1", "idempotency_key": "kurz"},
])
def test_incomplete_or_mixed_commands_are_rejected(changes):
    data = {"source": "web", "actor": "web:s", "mail_id": MAIL, "version": 1,
            "idempotency_key": "key-00000001", **changes}
    with pytest.raises(ValidationError):
        ReviewCommand.model_validate(data)


# --- service: decisions ----------------------------------------------------------

def test_web_confirmation_writes_exactly_the_confirmed_version(tmp_path):
    writer = Writer()
    with JsonStore(tmp_path) as store:
        dialog, telegram, _ = setup(store, proposal(), writers={"todoist": writer})
        result = web(dialog).execute(command(CommandKind.CONFIRM))
        assert (result.status, result.message) == (ResultStatus.WRITTEN, "Angelegt.")
        assert writer.versions == [1]
        assert store.load(f"proposal-{MAIL}-p1")["status"] == "created"
        # Telegram stays consistent: the write result is reported there too.
        assert "✅ Angelegt als Aufgabe" in telegram.sent[-1][1]
        # A second, identical confirmation is stale and writes nothing.
        again = web(dialog).execute(command(CommandKind.CONFIRM, key="key-00000002"))
        assert again.status == ResultStatus.STALE and writer.created == 1


@pytest.mark.parametrize(("status", "kind", "expected"), [
    ("pending_confirmation", CommandKind.REJECT, (ResultStatus.DONE, "Vorschlag verworfen.")),
    ("pending_confirmation", CommandKind.START_CLARIFICATION,
     (ResultStatus.DONE, "Bearbeitung gestartet – bitte die Rückfrage beantworten.")),
    ("needs_clarification", CommandKind.CONFIRM,
     (ResultStatus.NEEDS_ANSWER, "Zuerst müssen die offenen Fragen beantwortet werden")),
    ("rejected", CommandKind.CONFIRM, (ResultStatus.STALE, "Der Vorschlag wurde inzwischen geändert oder entschieden")),
    ("created", CommandKind.REJECT, (ResultStatus.STALE, "Der Vorschlag wurde inzwischen geändert oder entschieden")),
])
def test_each_decision_in_allowed_and_forbidden_states(tmp_path, status, kind, expected):
    item = proposal(status=status, open_questions=["Ort?"] if status == "needs_clarification" else [])
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, item, writers={"todoist": Writer()})
        result = web(dialog).execute(command(kind))
    assert (result.status, result.message) == expected


def test_version_conflict_and_unknown_proposal_are_stale(tmp_path):
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, proposal(version=2))
        service = web(dialog)
        assert service.execute(command(CommandKind.CONFIRM, version=1)).status == ResultStatus.STALE
        missing = service.execute(command(CommandKind.CONFIRM, proposal_id="unknown"))
        assert (missing.status, missing.message) == (ResultStatus.STALE, "Vorschlag wurde nicht gefunden")
        # A web identifier that the decision model refuses is invalid, not a crash.
        invalid = service.execute(command(CommandKind.CONFIRM, proposal_id="x" * 40,
                                          source=CommandSource.TELEGRAM, actor=TELEGRAM))
        assert (invalid.status, invalid.message) == (ResultStatus.INVALID, "Die Eingabe ist ungültig.")
        with pytest.raises(StaleCommand):
            service.execute(command(CommandKind.CONFIRM, version=1), raise_errors=True)


@pytest.mark.parametrize(("writer", "expected"), [
    (Writer(error=UncertainWriteError("timeout")), ResultStatus.WRITE_UNCERTAIN),
    (Writer(error=PermanentError("denied")), ResultStatus.WRITE_FAILED),
])
def test_unclear_and_failed_writes_are_reported_as_such(tmp_path, writer, expected):
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, proposal(), writers={"todoist": writer})
        assert web(dialog).execute(command(CommandKind.CONFIRM)).status == expected


def test_confirmation_without_writer_is_reported_as_not_written(tmp_path):
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, proposal())
        result = web(dialog).execute(command(CommandKind.CONFIRM))
    assert (result.status, result.message) == (
        ResultStatus.NOT_WRITTEN, "Bestätigt; keine externe Anlage ausgeführt.")


def test_duplicate_needs_a_second_confirmation_in_the_web(tmp_path):
    writer = Writer()
    earlier = proposal(source_mail_id=OTHER)
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, proposal(), writers={"todoist": writer})
        store.save("action-ledger", ActionLedger(entries=[ActionLedgerEntry(
            action_key=action_key(earlier), action_key_version=2, mail_id=OTHER, proposal_id="p1",
            proposal_version=1, kind="task", title="Aufgabe", target="inbox")]).model_dump(mode="json"))
        service = web(dialog)
        first = service.execute(command(CommandKind.CONFIRM))
        assert first.status == ResultStatus.NEEDS_DUPLICATE_CONFIRMATION
        assert first.message.startswith("Diese Aktion wurde bereits früher angelegt")
        assert writer.created == 0
        second = service.execute(command(CommandKind.CONFIRM_DUPLICATE, key="key-00000002"))
        assert second.status == ResultStatus.WRITTEN and writer.created == 1


def test_telegram_commands_keep_the_telegram_texts(tmp_path):
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, proposal())
        result = dialog.review.execute(command(CommandKind.REJECT, source=CommandSource.TELEGRAM,
                                               actor=TELEGRAM))
    assert (result.status, result.message) == (ResultStatus.DONE, "✅ Vorschlag wurde verworfen.")


# --- service: authorization ------------------------------------------------------

@pytest.mark.parametrize(("source", "actor", "allowed"), [
    (CommandSource.TELEGRAM, "telegram:9:2", True),
    (CommandSource.WEB, "web:session", None),
    (CommandSource.WEB, "web:session", False),
    (CommandSource.WEB, "telegram:1:2", True),
    (CommandSource.WEB, "web:other", True),
])
def test_unauthorized_commands_change_nothing(tmp_path, source, actor, allowed):
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, proposal())
        if allowed is not None:
            web(dialog, allowed)
        result = dialog.review.execute(command(CommandKind.REJECT, source=source, actor=actor))
        assert (result.status, result.message) == (ResultStatus.UNAUTHORIZED, "Nicht autorisiert.")
        assert store.load(f"proposal-{MAIL}-p1")["status"] == "pending_confirmation"


# --- service: answers and cancel -----------------------------------------------

def test_web_answer_revises_and_requires_a_new_confirmation(tmp_path):
    item = proposal(open_questions=["Wann ist es fällig?"])
    with JsonStore(tmp_path) as store:
        dialog, telegram, _ = setup(store, item)
        result = web(dialog).execute(command(CommandKind.ANSWER, text="Freitag"))
        assert (result.status, result.message) == (
            ResultStatus.DONE, "Antwort übernommen – der Vorschlag wird aktualisiert.")
        current = store.load(f"proposal-{MAIL}-p1")
        assert (current["version"], current["status"]) == (2, "pending_confirmation")
        # The old version can no longer be confirmed; the new one must be.
        assert web(dialog).execute(command(CommandKind.CONFIRM, version=1)).status == ResultStatus.STALE
        assert any("Übernommen" in text for _, text, _ in telegram.sent)


def test_web_change_request_on_a_complete_proposal_reopens_it(tmp_path):
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, proposal())
        web(dialog).execute(command(CommandKind.ANSWER, text="Titel: Neu"))
        assert store.load(f"proposal-{MAIL}-p1-v1")["status"] == "pending_confirmation"
        assert store.load(f"proposal-{MAIL}-p1")["version"] == 2


def test_web_answer_takes_over_an_idle_telegram_dialog_but_not_a_running_retry(tmp_path):
    first = proposal(open_questions=["Ort?"])
    second = proposal(id="p2", open_questions=["Ort?"])
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, first, second)
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=MAIL, proposal_id="p2", version=1).model_dump(mode="json"))
        assert web(dialog).execute(command(CommandKind.ANSWER, text="Raum 3")).status == ResultStatus.DONE
        assert store.load(f"proposal-{MAIL}-p1")["version"] == 2
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=MAIL, proposal_id="p1", version=2, retry_required=True,
            question="Ort?", normalized_answer="Raum 3").model_dump(mode="json"))
        busy = web(dialog).execute(command(CommandKind.ANSWER, proposal_id="p2", text="Raum 4"))
        assert busy.status == ResultStatus.BUSY
        assert store.load(f"proposal-{MAIL}-p2")["version"] == 1


def test_web_answer_on_the_active_dialog_reuses_it(tmp_path):
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, proposal(open_questions=["Ort?"]))
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=MAIL, proposal_id="p1", version=1).model_dump(mode="json"))
        web(dialog).execute(command(CommandKind.ANSWER, text="Raum 3"))
        assert store.load(f"proposal-{MAIL}-p1")["version"] == 2


def test_cancel_needs_the_running_clarification_of_this_version(tmp_path):
    with JsonStore(tmp_path) as store:
        dialog, telegram, _ = setup(store, proposal())
        service = web(dialog)
        stale = service.execute(command(CommandKind.CANCEL_CLARIFICATION))
        assert (stale.status, stale.message) == (
            ResultStatus.STALE, "Für diesen Vorschlag läuft keine Bearbeitung")
        service.execute(command(CommandKind.START_CLARIFICATION))
        done = service.execute(command(CommandKind.CANCEL_CLARIFICATION, key="key-00000002"))
        assert done.status == ResultStatus.DONE
        assert store.load(f"proposal-{MAIL}-p1")["status"] == "pending_confirmation"
        assert store.load("telegram-dialog")["proposal_id"] is None
        assert any("Bearbeitung geschlossen" in text for _, text, _ in telegram.sent)


# --- service: relevance --------------------------------------------------------

def test_relevance_from_the_web_uses_the_current_offset(tmp_path):
    with JsonStore(tmp_path) as store:
        store.save(f"mail-{MAIL}", relevance_state(MAIL).model_dump(mode="json"))
        store.save("telegram-offset", {"schema_version": 1, "offset": 41})
        dialog, _, _ = controller(store)
        handler = RelevanceHandler(store)
        dialog.relevance_handler = handler
        service = web(dialog)
        result = service.execute(command(CommandKind.RELEVANCE, decision="relevant"))
        assert (result.status, result.message) == (ResultStatus.DONE, "Mail als relevant eingestuft.")
        assert store.load(f"mail-{MAIL}")["relevance_dialog"]["telegram_offset"] == 41
        assert handler.resumed == [MAIL]
        again = service.execute(command(CommandKind.RELEVANCE, decision="irrelevant"))
        assert (again.status, again.message) == (
            ResultStatus.STALE, "Die Relevanzfrage ist veraltet oder bereits beantwortet")


def test_relevance_irrelevant_and_telegram_offsets(tmp_path):
    with JsonStore(tmp_path) as store:
        store.save(f"mail-{MAIL}", relevance_state(MAIL).model_dump(mode="json"))
        store.save(f"mail-{OTHER}", relevance_state(OTHER).model_dump(mode="json"))
        dialog, _, _ = controller(store)
        dialog.relevance_handler = RelevanceHandler(store)
        result = web(dialog).execute(command(CommandKind.RELEVANCE, decision="irrelevant"))
        assert result.message == "Mail als irrelevant eingestuft."
        # Without any processed update the first durable offset is 1.
        assert store.load(f"mail-{MAIL}")["relevance_dialog"]["telegram_offset"] == 1
        telegram = dialog.review.execute(command(
            CommandKind.RELEVANCE, mail_id=OTHER, decision="relevant",
            source=CommandSource.TELEGRAM, actor=TELEGRAM, replay_offset=7))
        assert telegram.message == "✅ E-Mail wurde als relevant eingestuft."
        assert store.load(f"mail-{OTHER}")["relevance_dialog"]["telegram_offset"] == 7


def test_a_review_error_from_the_relevance_dialog_is_kept(tmp_path, monkeypatch):
    with JsonStore(tmp_path) as store:
        dialog, _, _ = controller(store)

        def stale(*_):
            raise StaleCommand("bereits entschieden")

        monkeypatch.setattr(dialog, "decide_relevance", stale)
        result = web(dialog).execute(command(CommandKind.RELEVANCE, decision="relevant"))
    assert (result.status, result.message) == (ResultStatus.STALE, "bereits entschieden")


# --- views -----------------------------------------------------------------------

def test_overview_orders_current_first_and_marks_queued_and_editing(tmp_path):
    task = proposal(id="task", due="2026-10-30")
    event = proposal(id="event", open_questions=["Wann beginnt der Termin?"], kind="event",
                     known_temporal_facts={"date": "2026-10-21"}, target="calendar")
    held = proposal(id="held", open_questions=["Ist die Nutzerin oder der Nutzer für diesen Eintrag zuständig?"],
                    responsibility="unclear")
    with JsonStore(tmp_path) as store:
        setup(store, task, event, held)
        store.save("telegram-outbox", TelegramOutboxState(
            active=TelegramOutboxGate(kind="proposal", mail_id=MAIL, proposal_id="event", version=1),
            entries=[TelegramOutboxEntry(id="1" * 32, kind="proposal", mail_id=MAIL, proposal_id="held",
                                         version=1, created_at=datetime.now(UTC))],
        ).model_dump(mode="json"))
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=MAIL, proposal_id="task", version=1).model_dump(mode="json"))
        overview = ReviewViews(store, "Europe/Berlin").overview()
    event_view, task_view, held_view = overview.open
    assert [view.proposal_id for view in overview.open] == ["event", "task", "held"]
    assert event_view.current and not task_view.current
    assert event_view.question == "Wann beginnt der Termin?" and event_view.example == "„21.10.2026 14:00“"
    assert event_view.card.when == "21.10.2026"
    assert event_view.actions == {CommandKind.REJECT, CommandKind.ANSWER}
    assert task_view.editing and task_view.state == "Rückfrage offen"
    assert task_view.question == "Was soll geändert werden?"
    assert task_view.actions == {CommandKind.CONFIRM, CommandKind.REJECT, CommandKind.ANSWER,
                                 CommandKind.CANCEL_CLARIFICATION}
    assert task_view.card.due == "30.10.2026" and task_view.confirm_label == "Als Aufgabe anlegen"
    assert held_view.queued and held_view.yes_no and held_view.question == "Bist du dafür zuständig?"
    assert held_view.state == "Klärung nötig"
    assert (task_view.sender, task_view.subject) == ("Ada Muster", "Elternabend")


def test_answer_saved_paused_and_unwritable_states(tmp_path):
    saved = proposal(id="saved", open_questions=["Ort?"])
    paused = proposal(id="paused", open_questions=["Ort?"])
    manual = proposal(id="manual", classification="unsupported")
    with JsonStore(tmp_path) as store:
        setup(store, saved, paused, manual, test_mode=True)
        store.save(f"clarification-{MAIL}-saved-v1", ProposalClarificationState(
            mail_id=MAIL, proposal_id="saved", version=1, question="Ort?",
            authorized_answer="Raum 3").model_dump(mode="json"))
        store.save(f"clarification-{MAIL}-paused-v1", ProposalClarificationState(
            mail_id=MAIL, proposal_id="paused", version=1, question="Ort?",
            authorized_answer="Raum 3", answer_status=AnswerStatus.VALID, question_status="answered",
            normalized_answer="Raum 3", interpretation_status="completed",
            proposal_revision_status=ProposalRevisionStatus.PAUSED).model_dump(mode="json"))
        views = {view.proposal_id: view for view in ReviewViews(store, "UTC", test_mode=True).overview().open}
    assert views["saved"].answer_saved and views["saved"].actions == frozenset()
    assert views["saved"].state == "Antwort gespeichert – wird verarbeitet"
    assert views["paused"].paused and views["paused"].state.startswith("Verarbeitung pausiert")
    assert not views["manual"].card.writable and views["manual"].question == "Was soll geändert werden?"
    assert views["manual"].card.classification == "Manuell prüfen"
    assert views["manual"].confirm_label == "Simulieren"


def test_a_running_retry_counts_as_a_saved_answer(tmp_path):
    with JsonStore(tmp_path) as store:
        setup(store, proposal(open_questions=["Ort?"]))
        store.save("telegram-dialog", TelegramDialogState(
            mail_id=MAIL, proposal_id="p1", version=1, retry_required=True,
            question="Ort?", normalized_answer="Raum 3").model_dump(mode="json"))
        view = ReviewViews(store, "UTC").overview().open[0]
    assert view.answer_saved and view.actions == frozenset()


def test_recent_results_are_newest_first_and_limited(tmp_path):
    with JsonStore(tmp_path) as store:
        base = datetime(2026, 10, 1, tzinfo=UTC)
        for index in range(RECENT_LIMIT + 2):
            mail_id = f"{index:024x}"
            item = proposal(id="p1", source_mail_id=mail_id, status="created",
                            external_link="https://todoist.test/1")
            setup(store, item, mail_id=mail_id, uid=index + 1, updated=base + timedelta(hours=index))
        # A decided proposal without its mail record sorts last.
        store.save("proposal-ffffffffffffffffffffffff-p9",
                   proposal(id="p9", source_mail_id="f" * 24, status="rejected").model_dump(mode="json"))
        overview = ReviewViews(store, "UTC").overview()
    assert len(overview.recent) == RECENT_LIMIT
    assert overview.recent[0].mail_id == f"{RECENT_LIMIT + 1:024x}"
    assert overview.recent[0].state == "Angelegt"
    assert overview.recent[0].external_link == "https://todoist.test/1"
    assert overview.open == ()


def test_views_skip_damaged_records_without_moving_them(tmp_path):
    with JsonStore(tmp_path) as store:
        setup(store, proposal())
        (tmp_path / f"proposal-{MAIL}-broken.json").write_text("{", encoding="utf-8")
        (tmp_path / f"proposal-{MAIL}-invalid.json").write_text('{"id": 1}', encoding="utf-8")
        (tmp_path / "mail-run-broken.json").write_text("[", encoding="utf-8")
        overview = ReviewViews(store, "UTC").overview()
        assert overview.damaged == 3 and len(overview.open) == 1
        assert (tmp_path / f"proposal-{MAIL}-broken.json").exists()
        assert not list(tmp_path.glob("*.corrupt")) and not list(tmp_path.glob("*.invalid"))


def test_relevance_questions_run_status_and_fingerprint(tmp_path):
    with JsonStore(tmp_path) as store:
        state = relevance_state(MAIL).model_copy(update={
            "display_headers": DisplayHeaders(sender="Schule <info@schule.test>", subject="Ausflug")})
        store.save(f"mail-{MAIL}", state.model_dump(mode="json"))
        store.save(f"mail-{OTHER}", relevance_state(OTHER).model_dump(mode="json"))
        store.save("mail-cccccccccccccccccccccccc", mail_state("c" * 24).model_dump(mode="json"))
        entries = [MailRunEntry(account_id="0" * 24, folder="INBOX", uidvalidity=1, uid=1,
                                status="completed", analysis_terminal="completed"),
                   MailRunEntry(account_id="0" * 24, folder="INBOX", uidvalidity=1, uid=2)]
        for name, created in (("mail-run-a", datetime(2026, 10, 1, tzinfo=UTC)),
                              ("mail-run-b", datetime(2026, 10, 2, tzinfo=UTC))):
            store.save(name, MailRunState(
                run_id="00000000-0000-0000-0000-000000000001", created_at=created, entries=entries,
                counters=MailRunCounters(discovered=1, completed=1)).model_dump(mode="json"))
        views = ReviewViews(store, "UTC")
        overview = views.overview()
        assert [(item.sender, item.subject) for item in overview.relevance] == [
            ("Schule", "Ausflug"), ("—", "Mail ohne Betreff")]
        assert overview.run.counters["completed"] == 2 and overview.run.counters["discovered"] == 2
        assert not overview.run.run_complete
        assert overview.run.started_at == datetime(2026, 10, 2, tzinfo=UTC)
        setup(store, proposal(), mail_id="d" * 24)
        changed = views.overview()
        assert changed.fingerprint != overview.fingerprint
        assert views.overview().fingerprint == changed.fingerprint
    empty = ReviewViews(JsonStore(tmp_path / "empty"), "UTC").overview()
    assert (empty.run.counters, empty.run.run_complete, empty.run.started_at) == ({}, True, None)


def test_single_proposal_lookup_and_missing_mail(tmp_path):
    with JsonStore(tmp_path) as store:
        store.save(f"proposal-{MAIL}-solo", proposal(id="solo").model_dump(mode="json"))
        views = ReviewViews(store, "UTC")
        view = views.proposal(MAIL, "solo")
        assert (view.sender, view.subject, view.updated_at) == ("—", "—", None)
        assert views.proposal(MAIL, "other") is None


def test_card_content_hides_defaults_and_keeps_full_texts():
    long, evidence = "Wort " * 100, "Beleg " * 100
    card = card_content(proposal(**EVENT, description=long, evidence=evidence,
                                 location="Aula", video_link="https://meet.test/x"), "Europe/Berlin")
    assert card.when == "21.10.2026, 12:30–15:30 Uhr" and card.due is None
    assert (card.location, card.video_link) == ("Aula", "https://meet.test/x")
    assert card.description.endswith("…") and card.description_full == long.strip()
    assert len(card.evidence) <= 200 and card.evidence_full == evidence
    assert (card.responsibility, card.certainty, card.classification) == (None, None, None)
    task = card_content(proposal(location=None), "UTC")
    assert (task.when, task.location, task.video_link, task.due) == (None, None, None, None)
    assert yes_no_question("Ist die extrahierte Information sicher belegt?")
    assert not yes_no_question("Wo findet es statt?")


# --- store: thread safety and read-only access ---------------------------------

def test_peek_reads_without_quarantine_or_saving_migrations(tmp_path):
    with JsonStore(tmp_path) as store:
        assert store.peek("missing", "default") == "default"
        assert store.peek_model("missing", TelegramDialogState) is None
        (tmp_path / "broken.json").write_text("{", encoding="utf-8")
        with pytest.raises(CorruptState, match="Beschädigter Zustand: broken.json"):
            store.peek("broken")
        store.save("dialog", {"schema_version": 1, "mail_id": 5})
        with pytest.raises(CorruptState, match="Schemawidriger Zustand: dialog.json"):
            store.peek_model("dialog", TelegramDialogState)
        assert (tmp_path / "broken.json").exists() and (tmp_path / "dialog.json").exists()
        with pytest.raises(ValueError):
            store.peek("../x")


def test_parallel_reads_during_writes_never_fail(tmp_path):
    """Regression for the web: on Windows os.replace failed while a reader had the file open."""
    errors = []
    with JsonStore(tmp_path) as store:
        store.save("state", {"value": 0})
        stop = threading.Event()

        def read():
            while not stop.is_set():
                try:
                    with store.locked():
                        assert store.peek("state")["value"] >= 0
                        store.names()
                except Exception as exc:
                    errors.append(exc)

        readers = [threading.Thread(target=read) for _ in range(4)]
        for thread in readers:
            thread.start()
        try:
            for value in range(200):
                store.save("state", {"value": value})
        finally:
            stop.set()
            for thread in readers:
                thread.join()
    assert errors == []


def test_answer_and_cancel_check_the_referenced_version(tmp_path):
    with JsonStore(tmp_path) as store:
        dialog, _, _ = setup(store, proposal(version=3))
        service = web(dialog)
        missing = service.execute(command(CommandKind.ANSWER, proposal_id="gone", text="x"))
        assert (missing.status, missing.message) == (ResultStatus.STALE, "Vorschlag wurde nicht gefunden")
        stale = service.execute(command(CommandKind.CANCEL_CLARIFICATION, version=2))
        assert (stale.status, stale.message) == (
            ResultStatus.STALE, "Der Vorschlag wurde inzwischen geändert oder entschieden")
