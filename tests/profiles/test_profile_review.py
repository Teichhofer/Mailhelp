"""Profile changes are local versions; both transports require separate confirmation."""
from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError
from shared_profiles import settings
from shared_telegram_dialog import callback, controller, proposal

from mailhelp.profile_binding import choices, policy_hash
from mailhelp.review.commands import CommandKind, CommandSource, ReviewCommand
from mailhelp.review.results import ResultStatus
from mailhelp.storage import JsonStore
from mailhelp.telegram.callbacks import Decision, DecisionAction
from mailhelp.telegram.decisions import AnswerRequired


def command(item, **changes):
    return ReviewCommand(kind=CommandKind.RETARGET, source="telegram", actor="telegram:1:2", mail_id=item.source_mail_id,
        proposal_id=item.id, version=item.version, idempotency_key="retarget-001",
        target_profile=2, proposal_hash="f" * 64, **changes)


def test_telegram_target_change_creates_new_unconfirmed_version_and_profile_status(tmp_path):
    cfg = settings(tmp_path)
    item = proposal(target=cfg.targets.task_target, target_provider="todoist")
    with JsonStore(tmp_path) as store:
        dialog, _, _ = controller(store)
        dialog.relevance_handler = NS(mailbox_settings=cfg)
        dialog.persist(item)
        dialog.presenter.profile_of = lambda _: "Standard"
        dialog.presenter.retarget_choices = lambda p: choices(cfg, p)
        dialog.presenter.profiles_status = lambda: "Zielprofil 2: konfiguriert"
        dialog.send_proposal(item)
        assert "Zielprofil: Standard" in dialog.telegram.sent[-1][1]
        buttons = dialog.telegram.sent[-1][2]["inline_keyboard"]
        target = next(button[0]["callback_data"] for button in buttons if button[0]["text"].startswith("Auf Zielprofil"))
        dialog.telegram.updates = [callback(1, target)]
        dialog.poll_once()
        current = dialog.repository.load_current(item.source_mail_id, item.id)
        assert current.version == 2 and current.target_profile == 2 and current.status == "pending_confirmation"
        assert all(writer.created == 0 for writer in dialog.writers.values())
        dialog.show_open_decisions()
        assert any("Zielprofil 2: konfiguriert" in row[1] for row in dialog.telegram.sent)
        dialog.presenter.profile_available = dialog.decision_service.profile_available = lambda _: False
        presentation = dialog.presenter.present(current)
        assert all("anlegen" not in button["text"] for row in presentation.reply_markup["inline_keyboard"] for button in row)
        with pytest.raises(AnswerRequired, match="Zielprofil"):
            dialog.decision_service.decide_with_status(Decision(mail_id=current.source_mail_id,
                proposal_id=current.id, version=current.version, action=DecisionAction.CONFIRM), 1, 2)


def test_retarget_rejects_missing_configuration_and_stale_target_policy(tmp_path):
    item = proposal()
    with JsonStore(tmp_path) as store:
        dialog, _, _ = controller(store)
        dialog.persist(item)
        assert dialog.review.execute(command(item)).status == ResultStatus.INVALID
        dialog.relevance_handler = NS(mailbox_settings=settings(tmp_path))
        assert dialog.review.execute(command(item)).status == ResultStatus.INVALID
        assert dialog.repository.load_current(item.source_mail_id, item.id).version == 1


@pytest.mark.parametrize("fields", [{"action": DecisionAction.RETARGET},
    {"action": DecisionAction.CONFIRM, "target_profile": 2},
    {"action": DecisionAction.CONFIRM, "target_profile": 2, "profile_hash": "f" * 64}])
def test_opaque_callback_requires_complete_profile_binding(fields):
    with pytest.raises(ValidationError):
        Decision(mail_id="a" * 24, proposal_id="p1", version=1, **fields)


def test_review_commands_cannot_smuggle_profile_numbers_into_other_actions():
    with pytest.raises(ValidationError):
        ReviewCommand(kind="reject", source="telegram", actor="telegram:1:2", mail_id="a" * 24,
            proposal_id="p1", version=1, idempotency_key="invalid-001", target_profile=2)


def test_profile_failure_health_deduplicates_and_keeps_other_writes_available(tmp_path):
    from shared_telegram_dialog import Writer
    one, two = Writer(), Writer()
    def failed(_):
        raise ConnectionError("private endpoint")
    two.reconcile = failed
    with JsonStore(tmp_path) as store:
        dialog, _, _ = controller(store, writers={"todoist": one, "todoist:2": two})
        blocked = proposal(status="confirmed", target_profile=2)
        assert dialog.write_executor.execute(blocked) == blocked
        assert store.load("service-health")["errors"] == {"tasks:2": "network"}
        assert "private" not in str(store.load("service-health"))
        dialog.persist(blocked)
        assert dialog.write_executor.execute(blocked).status == "confirmed"
        assert store.load("service-health")["version"] == 1
        ready = proposal(id="p2", source_mail_id="b" * 24, status="confirmed")
        dialog.persist(ready)
        assert dialog.write_executor.execute(ready).status == "created" and one.created == 1
        two.reconcile = lambda _: {"id": "already-created"}
        assert dialog.write_executor.execute(blocked).external_id == "already-created"
        assert store.load("service-health")["errors"] == {} and store.load("service-health")["version"] == 2


def test_web_retarget_card_displays_binding_and_requires_new_confirmation(profiled):
    web, cfg = profiled.web, profiled.app.settings
    item = proposal(source_mail_id="a" * 24, target=cfg.targets.task_target, target_provider="todoist")
    web.dialog.persist(item)
    web.site.views.profile_label = lambda _: "Privat"
    web.site.views.profile_available = lambda _: False
    path = f"/vorschlag/{item.source_mail_id}/{item.id}"
    page = web.browser.request("GET", path).body.decode()
    assert "Zielprofil" in page and "Privat" in page and "Zielprofil nicht verfügbar" in page
    form = web.form(path, action="/einstellungen/zielprofile/umstellen", number="2")
    assert web.browser.request("POST", "/einstellungen/zielprofile/umstellen", {**form, "number": "wrong"}).status == 422
    assert web.browser.request("POST", "/einstellungen/zielprofile/umstellen", form).status == 303
    web.run()
    moved = web.dialog.repository.load_current(item.source_mail_id, item.id)
    assert moved.version == 2 and moved.target_profile == 2 and moved.status == "pending_confirmation"
    assert web.writer.created == 0
