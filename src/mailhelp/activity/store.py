"""Activity reports in the state store: one report file and blocks of up to 500 mails."""
from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from ..storage import StateStore
from .models import ActivityReport, ReportDefinition, ReportMail

CHUNK = 500
REPORT_PREFIX = "activity-report-"
MAILS_PREFIX = "activity-mails-"


def report_name(report_id: str) -> str:
    return f"{REPORT_PREFIX}{report_id}"


def mails_name(report_id: str, block: int) -> str:
    return f"{MAILS_PREFIX}{report_id}-{block}"


class ActivityReportStore:
    def __init__(self, store: StateStore):
        self.store = store

    def create(self, definition: ReportDefinition, addresses: list[str], domains: list[str]) -> ActivityReport:
        report = ActivityReport(id=uuid4().hex, definition=definition,
                                blocked_addresses=addresses, blocked_domains=domains)
        self.save(report)
        return report

    def reports(self) -> list[ActivityReport]:
        """Every report, newest first."""
        found = [self.store.load_model(name, ActivityReport) for name in self.store.names(REPORT_PREFIX)]
        return sorted((report for report in found if report is not None),
                      key=lambda report: report.created_at, reverse=True)

    def load(self, report_id: str) -> ActivityReport | None:
        return self.store.load_model(report_name(report_id), ActivityReport)

    def save(self, report: ActivityReport) -> None:
        self.store.save(report_name(report.id), report.model_dump(mode="json"))

    def _blocks(self, report_id: str) -> list[list[ReportMail]]:
        blocks = []
        while (raw := self.store.load(mails_name(report_id, len(blocks)))) is not None:
            blocks.append([ReportMail.model_validate(item) for item in raw])
        return blocks

    def mails(self, report_id: str) -> list[ReportMail]:
        return [mail for block in self._blocks(report_id) for mail in block]

    def mail(self, report_id: str, key: str) -> ReportMail | None:
        return next((mail for mail in self.mails(report_id) if mail.key == key), None)

    def save_mail(self, report_id: str, mail: ReportMail) -> None:
        """Replace the mail with the same key, or append it to the last block."""
        blocks = self._blocks(report_id)
        for number, block in enumerate(blocks):
            for position, existing in enumerate(block):
                if existing.key == mail.key:
                    block[position] = mail
                    self._save_block(report_id, number, block)
                    return
        if not blocks or len(blocks[-1]) >= CHUNK:
            blocks.append([])
        blocks[-1].append(mail)
        self._save_block(report_id, len(blocks) - 1, blocks[-1])

    def _save_block(self, report_id: str, number: int, block: list[ReportMail]) -> None:
        self.store.save(mails_name(report_id, number), [item.model_dump(mode="json") for item in block])

    def delete(self, report_id: str) -> None:
        """Remove the report and all its mail blocks at once."""
        for name in self.store.names(f"{MAILS_PREFIX}{report_id}-"):
            self.store.delete(name)
        self.store.delete(report_name(report_id))

    def remove_expired_texts(self, days: int | str, now: datetime) -> int:
        """Retention: drop full texts of finished reports; dates, senders and subjects stay."""
        if days == "unlimited":
            return 0
        removed = 0
        for report in self.reports():
            if report.finished_at is None:
                continue
            if days != "disabled" and report.finished_at > now - timedelta(days=days):
                continue
            for number, block in enumerate(self._blocks(report.id)):
                changed = [mail for mail in block if not mail.text_removed]
                if not changed:
                    continue
                for mail in changed:
                    mail.text, mail.text_removed = "", True
                    for event in mail.events:
                        event.evidence = ""
                removed += len(changed)
                self._save_block(report.id, number, block)
        return removed


__all__ = ["CHUNK", "ActivityReportStore", "mails_name", "report_name"]
