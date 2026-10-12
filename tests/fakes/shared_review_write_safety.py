"""Shared synthetic fixtures and doubles; no test-module dependencies."""




from mailhelp.action_normalization import MailDateContext
from mailhelp.config import TargetSettings
from mailhelp.models import ExtractedTask
from mailhelp.proposal_builder import ProposalBuilder


def reminder(mail_id, subject, day="2026-10-06", description="Unterlagen an Frau Muster senden"):
    context = MailDateContext("valid", f"{day}T10:00:00Z", f"{day}T10:00:00Z", "UTC")
    return ProposalBuilder(mail_id, TargetSettings(todoist_project="inbox", google_calendar="calendar"),
        context, "sender@example.test", subject).build([ExtractedTask(title="Unterlagen senden",
            description=description, evidence="Bitte senden", responsibility="user", certainty="certain",
            classification="new")], [])[0]
