"""Synthetic raw facts and date context for the trusted proposal builder."""
from mailhelp.config import TargetSettings
from mailhelp.models import ExtractedEvent, ExtractedTask
from mailhelp.proposals.action_normalization import MailDateContext
from mailhelp.proposals.proposal_builder import ProposalBuilder


def context(**changes):
    values = dict(date_context_status="valid", date_header_parsed="2026-09-18T10:00:00+02:00",
                  imap_received_at="2026-09-18T10:01:00+02:00", user_timezone="Europe/Berlin")
    values.update(changes)
    return MailDateContext(**values)

def task(**changes):
    values = dict(title="Antworten", description="", evidence="Bitte antworten",
                  responsibility="user", certainty="certain", classification="new", due_text=None)
    values.update(changes)
    return ExtractedTask(**values)

def event(**changes):
    values = dict(title="Gemeinderat", description=None, evidence="Gemeinderat am 22.09.2026",
                  date_text="22.09.2026", time_text=None, end_time_text=None, location=None,
                  time_requirement="all_day",
                  video_link=None, responsibility="user", certainty="certain", classification="new")
    values.update(changes)
    return ExtractedEvent(**values)

def builder(source_sender="Ada <ada@example.test>", source_subject="Projektstand", **changes):
    targets = TargetSettings(todoist_project="todoist-1", google_calendar="calendar-1")
    return ProposalBuilder("a" * 24, targets, context(**changes), source_sender, source_subject)
