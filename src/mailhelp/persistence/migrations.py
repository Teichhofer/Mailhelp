"""Explizite, schrittweise Migrationen persistierter JSON-Dokumente."""
from __future__ import annotations

from typing import Any


def migrate_document(model_name: str, value: dict[str, Any]) -> bool:
    """Migrate *value* in place and report whether it must be written back."""
    mail_state = model_name == "MailState"
    migrated = mail_state and value.get("schema_version") in {6, 7, 8}
    clarification = model_name == "ProposalClarificationState"
    if clarification and value.get("schema_version") == 1:
        value.setdefault("normalized_answer", None)
        value.setdefault("answer_status", "valid" if value["normalized_answer"] else "pending")
        value.setdefault("question_status", "answered" if value["normalized_answer"] else "open")
        value.setdefault("proposal_revision_status", "pending")
        value["schema_version"] = 2
        migrated = True
    if clarification and value.get("schema_version") == 2:
        value.update(schema_version=3, revision_attempts=0, next_revision_at=None)
        migrated = True
    if clarification and value.get("schema_version") == 3:
        value.update(schema_version=4, authorized_answer=None,
                     interpretation_status="pending", interpretation_attempts=0,
                     next_interpretation_at=None)
        migrated = True
    if mail_state and value.get("schema_version") == 6:
        old_notification = value["steps"].pop("notification", "pending")
        value["steps"]["summary_notification"] = old_notification
        value["steps"]["proposal_notification"] = old_notification
        value["schema_version"] = 7
    if mail_state and value.get("schema_version") == 7:
        action_status = value["steps"].get("action_detection", "pending")
        default = "skipped" if action_status == "skipped" else "pending"
        value["steps"].update(action_router=default, task_extraction=default,
                              event_extraction=default)
        value.update(task_extraction=None, event_extraction=None)
        value["schema_version"] = 8
    if mail_state and value.get("schema_version") == 8:
        action_status = value["steps"].get("action_detection", "pending")
        default = "skipped" if action_status == "skipped" else "pending"
        value["steps"].update(normalization=default, proposal_building=default)
        if action_status == "completed":
            value["steps"].update(normalization="completed", proposal_building="completed")
        value["normalized_proposals"] = value.get("proposals", [])
        notification_status = value["steps"].get("proposal_notification", "pending")
        per_proposal = ("completed" if notification_status == "completed" else
                        "sending" if notification_status == "sending" else "pending")
        value["proposal_notifications"] = [
            {"proposal_id": proposal["id"], "proposal_version": proposal["version"],
             "status": per_proposal}
            for proposal in value.get("proposals", [])
        ]
        value["schema_version"] = 9
    return migrated
