"""One authenticated entry point; overview links never start a paid operation."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from ..review.views import german_number
from ..rule_learning.service import digest
from .http import Response
from .labels import count_text
from .learning_pages import cost_hint, heading
from .pages import e, layout

UPDATED = "Seite wurde aktualisiert, bitte erneut bestätigen."


def run_date(timestamp: float, timezone: str) -> str:
    from zoneinfo import ZoneInfo
    return datetime.fromtimestamp(timestamp, UTC).astimezone(ZoneInfo(timezone)).strftime("%d.%m.%Y, %H:%M")


class LearningOverviewSite:
    def __init__(self, site: Any):
        self.site = site
        self.worker: Any = None
        site.app.route("GET", "/lernen", site.signed_in(self.home))
        site.app.route("POST", "/lernen", site.signed_in(self.legacy_post))
        site.app.route("GET", "/api/lernen/uebersicht", site.signed_in(self.status))

    def fingerprint(self, session: Any) -> str:
        mailbox = self.worker.jobs.state().model_dump(mode="json") if self.worker is not None else None
        service = self.site.rule_learning.service
        rules = service.overview("web:" + session.id) if service is not None else None
        return digest(json.dumps([mailbox, rules], sort_keys=True))

    def status(self, request: Any, session: Any) -> Response:
        return Response.json(200, {"fingerprint": self.fingerprint(session)})

    def legacy_post(self, request: Any, session: Any, form: Any) -> Response:
        return Response.html(409, layout("Lernseite aktualisiert",
            heading("Lernseite aktualisiert", UPDATED)
            + '<p><a class="button" href="/lernen/postfach">Aus dem Postfach lernen</a></p>', active="/lernen"))

    def home(self, request: Any, session: Any) -> Response:
        body = heading("Lernen", "Verbessere deine Themenregeln: mit einem Lernlauf aus dem Postfach "
                       "oder mit den bereits protokollierten Entscheidungen.", back=False)
        if self.worker is None:
            mailbox_status, last_run = "Lernlauf derzeit nicht verfügbar.", "Noch kein Lernlauf."
        else:
            state = self.worker.jobs.state()
            from .learning_site import LABELS
            mailbox_status = f"{LABELS[state.status]}: {count_text(state.cursor, 'Mail', 'Mails')} geprüft"
            if state.selection is not None:
                mailbox_status += f" von {state.selection.count} ausgewählten Mails"
            last_run = ("Letzter Lauf: " + run_date(state.started_at, self.site.configured_timezone)
                        if state.started_at else "Datum früherer Läufe nicht verfügbar.")
            if state.status == "empty":
                mailbox_status, last_run = "Noch kein Lernlauf gestartet.", "Noch kein Lernlauf."
        body += '<div class="learning-options">' + self.card("Aus dem Postfach lernen", "/lernen/postfach",
                          "Sinnvoll, wenn du neue Themen in vorhandenen Mails entdecken möchtest. "
                          "Der lesende Lauf schlägt Themen, Filter und Ordner vor.", mailbox_status, last_run)
        service = self.site.rule_learning.service
        if service is None:
            status, metric = "Regellernen derzeit nicht verfügbar.", "Noch keine Analyse."
        else:
            summary = service.overview("web:" + session.id)
            from .rule_learning_site import STATUSES
            status = STATUSES[summary["status"]]
            if summary["status"] == "review":
                status = (f'Prüfentwurf mit {count_text(summary["proposals"], "Vorschlag", "Vorschlägen")} '
                          "wartet." if summary["owned"]
                          else "Prüfentwurf in einer anderen Sitzung.")
            metric = (count_text(summary["new_decisions"], "neue verwertbare Entscheidung",
                                 "neue verwertbare Entscheidungen") + " seit der letzten Analyse, "
                      f'{german_number(summary["all_decisions"])} verwertbare insgesamt.')
            if not summary["available"]:
                status = ("In prompts.yaml fehlt decision_rule_learning. Den Block aus dem mitgelieferten "
                          "Beispiel übernehmen und die Konfiguration neu laden.")
        body += self.card("Aus Entscheidungen lernen", "/lernen/entscheidungen",
                          "Sinnvoll nach wiederholten Korrekturen oder Ablehnungen. Analysiert vorhandene "
                          "Entscheidungen und schlägt gezielte Änderungen deiner Themenregeln vor.", status, metric)
        body += '</div><p class="meta">Status wird automatisch lesend aktualisiert. '
        body += 'Das Öffnen dieser Seite startet keine Analyse.</p>'
        return Response.html(200, layout("Lernen", body, active="/lernen",
                                        fingerprint=self.fingerprint(session), state_url="/api/lernen/uebersicht"))

    @staticmethod
    def card(title: str, href: str, introduction: str, status: str, metric: str) -> str:
        return (f'<section class="card stack"><h2>{e(title)}</h2><p>{e(introduction)}</p>'
                f'<p role="status">{e(status)}</p><p>{e(metric)}</p>' + cost_hint()
                + f'<p><a class="button" href="{href}">{e(title)} öffnen</a></p></section>')
