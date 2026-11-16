"""Read-only briefing sections grouped by mailbox and its bound target profile."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

from .. import state_names
from ..domain.mail import MailState
from ..proposals.target_profiles import UnavailableWriter


# app is the running Application and views the review views; lower layers do not know their classes.
def sections(app: Any, views: Any) -> list[tuple[int, str, Any, Any, SimpleNamespace]]:
    writers = getattr(app, "profile_writers", None)
    profiles = getattr(writers, "profiles", {1: writers})
    result: list[tuple[int, str, Any, Any, SimpleNamespace]] = []
    for mailbox in app.settings.imap.enabled_mailboxes():
        if not mailbox.daily_briefing:
            continue
        pair = profiles.get(mailbox.target_profile)
        if pair is not None:
            calendar, tasks = pair.calendar, pair.tasks
        elif mailbox.target_profile == 1:
            calendar, tasks = app.calendar, app.todoist
        else:

            calendar = UnavailableWriter("calendar", "unavailable", mailbox.target_profile)
            tasks = UnavailableWriter("tasks", "unavailable", mailbox.target_profile)

        def overview(number: int = mailbox.id) -> Any:
            value = views.overview()

            def belongs(row: Any) -> bool:
                mail = app.store.peek_model(state_names.mail(row.mail_id), MailState)
                return mail is not None and app.orchestrator.mailbox_number(mail.imap.account_id) == number

            return replace(
                value,
                open=tuple(row for row in value.open if belongs(row)),
                relevance=tuple(row for row in value.relevance if belongs(row)),
            )

        result.append((mailbox.id, mailbox.label, calendar, tasks, SimpleNamespace(overview=overview)))
    return result


def configure(app: Any, briefing: Any, views: Any) -> None:
    if not app.settings.imap.legacy_format:
        briefing.mailboxes = lambda: sections(app, views)
