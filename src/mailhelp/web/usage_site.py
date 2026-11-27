"""8.7 §7.1: the usage in points – today, this month and a chosen period, without any money values.

Customers see only points of their own instance. Unvalued calls are counted and named, never shown
as free. The operator additionally sees the valuation in force; prices and exchange rates never
appear on a customer page.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from ..i18n import Locale, current, tr
from ..review.views import STAGE_LABELS
from ..usage.ledger import Purpose, Summary, summarize
from ..usage.points import current as current_valuation
from ..usage.points import display, total
from .auth import WebSession
from .http import Request, Response
from .pages import e, layout, page_head

if TYPE_CHECKING:
    from ..usage.valuations import UsageMeter
    from .site import MailhelpSite

PATH = "/verbrauch"
# 8.8.6 (Planung 8.8 AP5): the demo's fixed example – no ledger, no prices, the same in German and English.
SAMPLE_USAGE: tuple[tuple[str, str, Decimal], ...] = (
    ("2026-11-23", "relevance", Decimal("18")), ("2026-11-23", "summary", Decimal("24")),
    ("2026-11-23", "task_extraction", Decimal("11")), ("2026-11-24", "relevance", Decimal("15")),
    ("2026-11-24", "summary", Decimal("20")), ("2026-11-24", "event_extraction", Decimal("9")),
    ("2026-11-25", "relevance", Decimal("21")), ("2026-11-25", "summary", Decimal("27")),
    ("2026-11-25", "learning.topics", Decimal("40")),
)
MAX_DAYS = 366
# 8.7.4: steps outside mail processing; a learning run's calls carry the prefix "learning.".
FEATURE_LABELS = {
    "learning": "Aus dem Postfach lernen",
    "decision_rule_learning": "Aus Entscheidungen lernen",
    "settings_help": "Hilfschat",
    # 8.7.7: both steps of an activity report form one row
    "activity_relevance": "Tätigkeitsberichte",
    "activity_events": "Tätigkeitsberichte",
}


def stage_label(stage: str) -> str:
    feature = stage.split(".", 1)[0]
    if feature in FEATURE_LABELS:
        return tr(FEATURE_LABELS[feature])
    return tr(STAGE_LABELS[stage]) if stage in STAGE_LABELS else tr("Weitere KI-Schritte")


class UsageSite:
    def __init__(self, site: MailhelpSite) -> None:
        self.site = site
        self.meter: UsageMeter | None = None
        # Set by the demo: example values instead of a ledger.
        self.sample: tuple[tuple[str, str, Decimal], ...] | None = None
        site.app.route("GET", PATH, site.signed_in(self.page))

    def _period(self, query: str, today: date) -> tuple[date, date, bool]:
        """[start, end] inclusive from ?von=&bis=; this month when missing or invalid."""
        try:
            values = parse_qs(query, max_num_fields=4)
            start = date.fromisoformat(values["von"][0])
            end = date.fromisoformat(values["bis"][0])
        except (KeyError, ValueError, IndexError):
            return today.replace(day=1), today, False
        if end < start or (end - start).days >= MAX_DAYS:
            return today.replace(day=1), today, False
        return start, end, True

    def page(self, request: Request, session: WebSession) -> Response:
        english = current() is Locale.EN
        zone = ZoneInfo(self.site.configured_timezone)
        now = self.site.clock().astimezone(zone)
        head = page_head(tr("Verbrauch"), tr("Übersicht"),
                         tr("KI-Verarbeitung für dich, in Punkten. Schätzungen erscheinen getrennt davon."))
        if self.sample is not None:
            return Response.html(200, layout(tr("Verbrauch"), head + self._sample(english), active=PATH))
        if self.meter is None or not self.meter.valuations.revisions():
            body = head + "<p>" + tr("Die Verbrauchserfassung ist für diese Instanz noch nicht eingerichtet.") + "</p>"
            return Response.html(200, layout(tr("Verbrauch"), body, active=PATH))
        attempts = self.meter.ledger.attempts()
        today = now.date()
        start, end, chosen = self._period(request.query, today)

        def local(day: date) -> datetime:
            return datetime.combine(day, time(), zone)

        purpose = Purpose.CUSTOMER  # operator maintenance never counts as the customer's usage
        tiles = [(tr("Heute"), summarize(attempts, local(today), local(today + timedelta(days=1)), zone, purpose)),
                 (tr("Laufender Monat"), summarize(attempts, local(today.replace(day=1)),
                                                   local(today + timedelta(days=1)), zone, purpose))]
        period = summarize(attempts, local(start), local(end + timedelta(days=1)), zone, purpose)
        if chosen:
            tiles.append((tr("Zeitraum {start} bis {end}", start=start.isoformat(), end=end.isoformat()), period))
        started = self.meter.ledger.started_at()
        body = head + '<div class="tiles">' + "".join(self._tile(label, item, english) for label, item in tiles)
        body += "</div>"
        body += self._form(start, end)
        steps: dict[str, Decimal] = {}
        for stage, value in period.by_stage.items():
            # Several steps of one feature (a learning run) form one row; the sum stays exact.
            label = stage_label(stage)
            steps[label] = total([steps.get(label, Decimal(0)), value])
        body += self._table(tr("Nach Verarbeitungsschritt"), list(steps.items()), english)
        body += self._table(tr("Nach Tag"), [(day.isoformat(), value) for day, value in period.by_day.items()],
                            english)
        body += '<p class="meta">' + tr("Einzelwerte gerundet; Summen aus den genauen Werten.")
        if started is not None:
            body += " " + tr("Erfassung seit {start}.", start=e(started.astimezone(zone).date().isoformat()))
        body += "</p>"
        if self.site.auth.is_operator(session) and self.site.auth.customer_mode:
            valuation = current_valuation(self.meter.valuations.revisions(), self.site.clock())
            if valuation is not None:
                body += '<p class="meta">' + tr(
                    "Betreiber: Bewertungsstand {revision}, {rate} USD je EUR, Aufschlag {markup} %.",
                    revision=valuation.revision, rate=e(str(valuation.usd_per_eur)),
                    markup=e(str(valuation.markup_percent))) + "</p>"
        return Response.html(200, layout(tr("Verbrauch"), body, active=PATH))

    def _sample(self, english: bool) -> str:
        """The demo's example: same layout as the real page, clearly marked, without a period form."""
        assert self.sample is not None
        steps: dict[str, Decimal] = {}
        days: dict[str, Decimal] = {}
        for day, stage, value in self.sample:
            label = stage_label(stage)
            steps[label] = total([steps.get(label, Decimal(0)), value])
            days[day] = total([days.get(day, Decimal(0)), value])
        example = Summary(total([value for _day, _stage, value in self.sample]), len(self.sample), 0)
        hint = tr("Beispielwerte der Demo. In deiner eigenen Instanz stehen hier deine verbrauchten Punkte.")
        return (f'<p class="notice notice-info" role="status">{e(hint)}</p>'
                + '<div class="tiles">' + self._tile(tr("Beispielzeitraum"), example, english)
                + "</div>" + self._table(tr("Nach Verarbeitungsschritt"), list(steps.items()), english)
                + self._table(tr("Nach Tag"), list(days.items()), english))

    @staticmethod
    def _tile(label: str, summary: Summary, english: bool) -> str:
        detail = ""
        if summary.unclear:
            detail = '<span class="meta">' + tr(
                "Bekannte Teilsumme; {count} Aufruf(e) noch nicht bewertbar.", count=summary.unclear) + "</span>"
        return (f'<div class="tile"><span class="meta">{e(label)}</span>'
                f"<strong>{e(display(summary.points, english=english))}</strong>{detail}</div>")

    @staticmethod
    def _form(start: date, end: date) -> str:
        return ('<form method="get" action="/verbrauch" class="inline">'
                f'<label for="von">{tr("Von")}</label><input id="von" type="date" name="von" value="{start}">'
                f'<label for="bis">{tr("Bis")}</label><input id="bis" type="date" name="bis" value="{end}">'
                f'<button type="submit">{tr("Zeitraum anzeigen")}</button></form>')

    @staticmethod
    def _table(caption: str, rows: list[tuple[str, Decimal]], english: bool) -> str:
        if not rows:
            return ""
        cells = "".join(f"<tr><th scope=\"row\">{e(label)}</th><td>{e(display(value, english=english))}</td></tr>"
                        for label, value in rows)
        return (f"<table><caption>{e(caption)}</caption><thead><tr><th scope=\"col\">{tr('Bereich')}</th>"
                f"<th scope=\"col\">{tr('Punkte')}</th></tr></thead><tbody>{cells}</tbody></table>")


__all__ = ["PATH", "UsageSite"]
