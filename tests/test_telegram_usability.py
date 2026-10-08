"""Synthetic conversation tests for readable proposals and safe local commands."""
from datetime import date, datetime
from unittest.mock import Mock

import pytest

from mailhelp.models import (Proposal, ProposalStatus, TelegramDialogState,
                             ProposalClarificationState, RelevanceDialog, MailState)
from mailhelp.storage import JsonStore
from mailhelp.telegram import Decision, DecisionAction, TelegramUpdate
from mailhelp.telegram.formatting import display_date, format_proposal, clarification_prompt, revision_summary
from mailhelp.telegram.persistence import clarification_name
from test_telegram_dialog import proposal, controller, message, callback, RevisionService, Writer


def command(c, text, index=1, **identity):
    c._handle(TelegramUpdate.model_validate(message(index, text, **identity)))


def begin(c, item):
    c.persist(item)
    c._decide(Decision(mail_id=item.source_mail_id, proposal_id=item.id,
                       version=item.version, action=DecisionAction.EDIT))


@pytest.mark.parametrize("text", ["/hilfe", "/start", "/status", "/offen", "/abbrechen", "/unbekannt", "/hilfe argument"])
def test_commands_do_not_reach_llm_or_writers_and_unauthorized_are_silent(tmp_path, text):
    with JsonStore(tmp_path) as store:
        service = Mock()
        writer = Writer()
        c, t, _ = controller(store, revision_service=service, writers={"todoist": writer})
        for identity in ({"user": 9}, {"chat": 9}):
            command(c, text, **identity)
        assert not t.sent
        command(c, text)
        assert len(t.sent) == 1
        assert not service.mock_calls
        assert writer.created == writer.reconciled == 0
        if text in {"/status", "/offen"}:
            assert t.sent[0][1] == "Keine offene Telegram-Entscheidung."
        elif text in {"/hilfe", "/start"}:
            assert all(name in t.sent[0][1] for name in ("/hilfe", "/status", "/offen", "/abbrechen"))
        elif text == "/abbrechen":
            assert "Keine aktive Bearbeitung" in t.sent[0][1]
        else:
            assert "Unbekannter Befehl" in t.sent[0][1]


def test_cancel_edit_survives_restart_and_repetition_without_external_write(tmp_path):
    item = proposal(kind="event", start="2026-10-15T18:00:00+02:00", end="2026-10-15T19:00:00+02:00")
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        begin(c, item)
        assert "Rückfrage zu „Aufgabe“" in t.sent[-1][1]
        assert "Beispiel" in t.sent[-1][1]
        assert store.load("telegram-dialog")["version"] == 1
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        t.updates = [message(10, "/abbrechen")]
        c.poll_once()
        assert c.repository.load_current(item.source_mail_id, item.id) == item
        assert store.load("telegram-dialog")["proposal_id"] is None
        assert c.awaiting_decision()
        buttons = t.sent[-1][2]["inline_keyboard"][0]
        assert [b["text"] for b in buttons] == ["Im Kalender anlegen", "Ändern", "Verwerfen"]
        for b, action in zip(buttons, (DecisionAction.CONFIRM, DecisionAction.EDIT, DecisionAction.REJECT)):
            assert c.validator.decision(b["callback_data"]).action == action
        count = len(t.sent)
        c.poll_once()  # duplicated update is not re-applied
        assert len(t.sent) == count
        command(c, "/abbrechen")
        assert "Keine aktive Bearbeitung" in t.sent[-1][1]


def test_cancel_incomplete_preserves_questions_and_no_confirm_button(tmp_path):
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        item = proposal(open_questions=["Welches Datum?"])
        begin(c, item)
        command(c, "/abbrechen")
        assert c.repository.load_current(item.source_mail_id, item.id) == item
        assert [b["text"] for b in t.sent[-1][2]["inline_keyboard"][0]] == ["Klären", "Verwerfen"]


@pytest.mark.parametrize("case", ["empty", "missing", "new_version", "created", "no_snapshot", "saved_answer"])
def test_cancel_boundaries(tmp_path, case):
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        item = proposal()
        begin(c, item)
        if case == "empty":
            store.save("telegram-dialog", TelegramDialogState().model_dump())
        elif case == "missing":
            store.save("telegram-dialog", TelegramDialogState(mail_id=item.source_mail_id, proposal_id="absent", version=1).model_dump())
        elif case == "new_version":
            c.persist(proposal(version=2))
        elif case == "created":
            c.persist(proposal(status="created", external_id="existing"))
        elif case == "no_snapshot":
            (tmp_path / f"proposal-{item.source_mail_id}-{item.id}-v1.json").unlink()
        else:
            state = ProposalClarificationState(mail_id=item.source_mail_id, proposal_id=item.id,
                version=1, question="Änderung?", authorized_answer="Neuer Titel")
            store.save(clarification_name(item.source_mail_id, item.id, 1), state.model_dump(mode="json"))
        command(c, "/abbrechen")
        if case == "saved_answer":
            assert "bereits gespeichert" in t.sent[-1][1]
            assert store.load("telegram-dialog")["proposal_id"] == item.id
            assert store.load_model(clarification_name(item.source_mail_id, item.id, 1), ProposalClarificationState) == state
        elif case == "empty":
            assert "Keine aktive Bearbeitung" in t.sent[-1][1]
        elif case == "no_snapshot":
            assert c.repository.load_current(item.source_mail_id, item.id).status == ProposalStatus.NEEDS_CLARIFICATION
        else:
            assert "nicht mehr aktuell" in t.sent[-1][1]


def test_cancel_delivery_failure_can_be_retried_after_restart(tmp_path):
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        item = proposal(description="synthetisch " * 330)
        begin(c, item)
        original_send = t.send
        t.send = Mock(side_effect=RuntimeError("offline"))
        with pytest.raises(RuntimeError, match="offline"):
            command(c, "/abbrechen")
        assert store.load("telegram-dialog")["proposal_id"] == item.id
        t.send = original_send
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        command(c, "/abbrechen")
        assert len(t.sent) >= 3
        assert store.load("telegram-dialog")["proposal_id"] is None
        assert c.repository.load_current(item.source_mail_id, item.id) == item


def test_cancel_keeps_legacy_answer_and_allows_invalid_answer_to_leave_dialog(tmp_path):
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        item = proposal(open_questions=["Wann?"])
        begin(c, item)
        legacy = TelegramDialogState(mail_id=item.source_mail_id, proposal_id=item.id,
            version=1, retry_required=True, question="Wann?", normalized_answer="Morgen")
        store.save("telegram-dialog", legacy.model_dump(mode="json"))
        command(c, "/abbrechen")
        assert "bereits gespeichert" in t.sent[-1][1]
        assert store.load_model("telegram-dialog", TelegramDialogState) == legacy
        begin(c, item)
        state = ProposalClarificationState(mail_id=item.source_mail_id, proposal_id=item.id,
            version=1, question="Wann?", authorized_answer="irgendwann", answer_status="invalid",
            interpretation_status="completed")
        name = clarification_name(item.source_mail_id, item.id, 1)
        store.save(name, state.model_dump(mode="json"))
        command(c, "/status")
        assert "Warte auf Antwort" in t.sent[-1][1]
        command(c, "/abbrechen")
        assert store.load("telegram-dialog")["proposal_id"] is None
        assert store.load_model(name, ProposalClarificationState) == state


@pytest.mark.parametrize("headers", [None, {"sender": "Schule", "subject": "Elternabend"}])
def test_overview_relevance_current_proposals_and_revision_state(tmp_path, headers):
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        item = proposal()
        state = MailState(id=item.source_mail_id, config_fingerprint="f" * 64,
            imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 1},
            display_headers=headers)
        store.save(f"mail-{item.source_mail_id}", state.model_dump(mode="json"))
        relevance = RelevanceDialog(mail_id=item.source_mail_id, version=1)
        c.relevance.open = lambda: [relevance]
        c.persist(item)
        c.persist(proposal(id="done", status="rejected"))
        begin(c, proposal(id="question", open_questions=["Wann?"]))
        command(c, "/status")
        text = t.sent[-1][1]
        # Snapshots and finished proposals are excluded; the edited one is current.
        assert text.count("„Aufgabe“") == 3
        assert "Aktuelle Entscheidung: „Aufgabe“ · Version 1" in text
        assert "Warte auf Bestätigung" in text and "Warte auf Antwort" in text
        assert ("Elternabend" if headers else "Mail ohne Betreff") in text
        for status, expected in [("pending", "Antwort gespeichert"), ("paused", "Verarbeitung pausiert")]:
            clarification = ProposalClarificationState(mail_id=item.source_mail_id, proposal_id=item.id,
                version=1, question="Titel?", authorized_answer="Neu", interpretation_status=status)
            store.save(clarification_name(item.source_mail_id, item.id, 1), clarification.model_dump(mode="json"))
            command(c, "/offen")
            assert expected in t.sent[-2][1]
        command(c, "/abbrechen")  # show proposal with/without source headers
        assert ("Schule" if headers else "Absender: —") in t.sent[-1][1]


def test_readable_dates_facts_questions_and_revision_summary():
    assert display_date(date(2026, 10, 15), "Europe/Berlin") == "15.10.2026"
    assert display_date(datetime.fromisoformat("2026-10-15T16:00:00+00:00"), "Europe/Berlin") == "15.10.2026 · 18:00 Uhr (UTC+0200)"
    assert display_date(None, "Europe/Berlin") == "—"
    for facts in ({"date": "2026-10-15", "start_time": "18:00:00"},
                  {"start": "2026-10-15T18:00:00+02:00"}):
        item = proposal(kind="event", open_questions=["Wann endet der Termin?"], known_temporal_facts=facts)
        text = format_proposal(item, "Europe/Berlin")
        prompt = clarification_prompt(item, "Europe/Berlin")
        assert "Wann endet der Termin?" in prompt and "19:30 Uhr" in prompt and "/abbrechen" in prompt
        assert "Bekanntes Datum:" in text
        if "start_time" in facts:
            assert "Bekannte Uhrzeit: 18:00 Uhr" in text
    assert "Beginn: —" in clarification_prompt(proposal(kind="event", open_questions=["Wann?"]), "Europe/Berlin")
    assert "Fälligkeit: —" in clarification_prompt(proposal(open_questions=["Wann?"]), "Europe/Berlin")
    before = proposal(title="Alt")
    after = proposal(title="Neu", version=2)
    summary = revision_summary(before, after, "Europe/Berlin")
    assert "Bisher: Titel: Alt" in summary and "Jetzt: Titel: Neu" in summary
    assert "Keine inhaltlichen Änderungen" in revision_summary(before, before.model_copy(update={"version": 2}), "Europe/Berlin")


def test_event_edit_revision_requires_new_confirmation_and_rejects_old_version(tmp_path):
    with JsonStore(tmp_path) as store:
        writer = Writer()
        c, t, _ = controller(store, revision_service=RevisionService(), writers={"google_calendar": writer})
        item = proposal(kind="event", start="2026-10-15T18:00:00+02:00", end="2026-10-15T19:00:00+02:00")
        begin(c, item)
        command(c, "/hilfe")
        assert store.load("telegram-dialog")["proposal_id"] == item.id
        c.revisions.answer("Beschreibung korrigieren")
        revised = c.repository.load_current(item.source_mail_id, item.id)
        assert revised.version == 2 and revised.status == ProposalStatus.PENDING_CONFIRMATION
        assert "Geändert seit Version 1" in t.sent[-1][1]
        assert writer.created == 0
        with pytest.raises(ValueError, match="veraltet"):
            c._decide(Decision(mail_id=item.source_mail_id, proposal_id=item.id, version=1, action=DecisionAction.CONFIRM))
        assert writer.created == 0

@pytest.mark.parametrize('headers', [None, {'sender': 'Ada', 'subject': 'Frage'}])
@pytest.mark.parametrize('receipt', ['completed', 'sending'])
def test_open_redisplays_after_restart_without_changing_delivery_or_authorization(tmp_path, receipt, headers):
    from mailhelp.models import ProposalNotification
    item = proposal(open_questions=['Welches Datum?'], description='synthetisch ' * 330)
    mail = MailState(id=item.source_mail_id, config_fingerprint='f' * 64,
        imap={'account_id': '0' * 24, 'folder': 'INBOX', 'uidvalidity': 1, 'uid': 1},
        proposals=[item], display_headers=headers, proposal_notifications=[ProposalNotification(proposal_id=item.id, proposal_version=1, status=receipt)])
    with JsonStore(tmp_path) as store:
        c, _, _ = controller(store)
        c.persist(item)
        store.save(f'mail-{item.source_mail_id}', mail.model_dump(mode='json'))
    with JsonStore(tmp_path) as store:
        writer = Writer()
        c, t, _ = controller(store, writers={'todoist': writer}, revision_service=RevisionService())
        c.show_open_decisions()
        assert 'Klärung erforderlich' in t.sent[0][1]
        assert len(t.sent) >= 3
        buttons = t.sent[-1][2]['inline_keyboard'][0]
        assert [b['text'] for b in buttons] == ['Klären', 'Verwerfen']
        decision = c.validator.decision(buttons[0]['callback_data'])
        assert (decision.proposal_id, decision.version, decision.action) == (item.id, 1, DecisionAction.EDIT)
        assert store.load('telegram-dialog') is None
        assert c.repository.load_mail(item.source_mail_id) == mail
        assert c.repository.load_current(item.source_mail_id, item.id) == item
        count = len(t.sent)
        c.poll_once()
        c.send_proposal(item)
        assert len(t.sent) == count
        for identity in ({'user': 9}, {'chat': 9}):
            command(c, '/offen', **identity)
            c._handle(TelegramUpdate.model_validate(callback(20, buttons[0]['callback_data'], **identity)))
        assert all('Nicht autorisierte Aktion' in msg[1] for msg in t.sent[count:])
        assert store.load('telegram-dialog') is None
        assert c.repository.load_current(item.source_mail_id, item.id) == item
        command(c, '/offen')
        assert len(t.sent) > count
        c._handle(TelegramUpdate.model_validate(callback(21, buttons[0]['callback_data'])))
        assert 'Welches Datum?' in t.sent[-2][1]
        c.revisions.answer('Beschreibung korrigieren')
        revised = c.repository.load_current(item.source_mail_id, item.id)
        assert revised.version == 2
        assert writer.created == writer.reconciled == 0
        with pytest.raises(ValueError, match='veraltet'):
            c._decide(decision)
        c._decide(decision.model_copy(update={'version': 2, 'action': DecisionAction.REJECT}))
        assert not c.awaiting_decision()


def test_open_restores_only_matching_active_question_and_does_not_assign_other_proposals(tmp_path):
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        active = proposal(id='active', open_questions=['Wann genau?'])
        begin(c, active)
        c.persist(proposal(id='other'))
        t.sent.clear()
        command(c, '/offen')
        assert 'Warte auf Antwort' in t.sent[0][1]
        # The active question is the current decision; others get no buttons.
        assert 'Warte auf Bestätigung oder Verwerfen' in t.sent[0][1]
        assert all(msg[2] is None for msg in t.sent)
        assert 'Wann genau?' in t.sent[-1][1]
        assert store.load('telegram-dialog')['proposal_id'] == 'active'
        c.persist(proposal(id='active', version=2, open_questions=['Neues Datum?']))
        t.sent.clear()
        command(c, '/offen')
        assert all(msg[2] is not None for msg in t.sent[1:])
        assert store.load('telegram-dialog')['version'] == 1


@pytest.mark.parametrize('legacy', [False, True])
def test_open_saved_answer_does_not_request_another_answer(tmp_path, legacy):
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        item = proposal(open_questions=['Wann?'])
        begin(c, item)
        if legacy:
            store.save('telegram-dialog', TelegramDialogState(mail_id=item.source_mail_id,
                proposal_id=item.id, version=1, retry_required=True, question='Wann?',
                normalized_answer='Morgen').model_dump(mode='json'))
        else:
            state = ProposalClarificationState(mail_id=item.source_mail_id, proposal_id=item.id,
                version=1, question='Wann?', authorized_answer='Morgen')
            store.save(clarification_name(item.source_mail_id, item.id, 1), state.model_dump(mode='json'))
        t.sent.clear()
        c.show_open_decisions()
        assert len(t.sent) == 1 and 'Antwort gespeichert' in t.sent[0][1]
        assert t.sent[0][2] is None
        c, t, _ = controller(store, revision_service=RevisionService())
        c.poll_once()
        revised = c.repository.load_current(item.source_mail_id, item.id)
        assert revised.version == 2
        assert revised.status == ProposalStatus.PENDING_CONFIRMATION
        assert store.load('telegram-dialog')['proposal_id'] is None


def test_open_send_failure_preserves_state_and_explicit_retry_works(tmp_path):
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        item = proposal(open_questions=['Wann?'])
        c.persist(item)
        original_send = t.send
        t.send = Mock(side_effect=RuntimeError('offline'))
        with pytest.raises(RuntimeError, match='offline'):
            c.show_open_decisions()
        assert c.repository.load_current(item.source_mail_id, item.id) == item
        assert store.load('telegram-dialog') is None
        t.send = original_send
        command(c, '/offen')
        assert t.sent[-1][2]['inline_keyboard'][0][0]['text'] == 'Klären'

def test_regression_open_after_restart_restores_completed_clarification(tmp_path):
    """A completed delivery used to leave /offen with text and no usable entry."""
    from mailhelp.models import ProposalNotification
    item = proposal(open_questions=['Welches Datum?'])
    with JsonStore(tmp_path) as store:
        c, _, _ = controller(store)
        c.persist(item)
        mail = MailState(id=item.source_mail_id, config_fingerprint='f' * 64,
            imap={'account_id': '0' * 24, 'folder': 'INBOX', 'uidvalidity': 1, 'uid': 1},
            proposals=[item], proposal_notifications=[ProposalNotification(
                proposal_id=item.id, proposal_version=1, status='completed')])
        store.save(f'mail-{item.source_mail_id}', mail.model_dump(mode='json'))
    with JsonStore(tmp_path) as store:
        c, t, _ = controller(store)
        command(c, '/offen')
        assert t.sent[-1][2] is not None
        buttons = t.sent[-1][2]['inline_keyboard'][0]
        assert buttons[0]['text'] == 'Klären'
        c._decide(c.validator.decision(buttons[0]['callback_data']))
        assert 'Welches Datum?' in t.sent[-1][1]
        assert store.load('telegram-dialog')['proposal_id'] == item.id
