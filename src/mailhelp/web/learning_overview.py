"""One authenticated entry point; overview links never start a paid operation."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..review.proposal_evaluation import evaluate_proposals, get_learning_run_hint
from ..review.views import german_number
from ..rule_learning.service import digest
from .http import Response
from .labels import count_text
from .learning_pages import UPDATED, cost_hint, heading
from .learning_site import LABELS
from .pages import e, layout
from .proposal_evaluation_pages import learning_run_hint_banner
from .rule_learning_site import STATUSES

RULE_HELP = "/hilfe/dokumentation/bedienung/aus-entscheidungen-lernen"



def run_date(timestamp: float, timezone: str) -> str:
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
            mailbox_status = f"{LABELS[state.status]}: {count_text(state.cursor, 'Mail', 'Mails')} geprüft"
            if state.selection is not None:
                mailbox_status += f" von {state.selection.count} ausgewählten Mails"
            last_run = ("Letzter Lauf: " + run_date(state.started_at, self.site.configured_timezone)
                        if state.started_at else "Datum früherer Läufe nicht verfügbar.")
            if state.status == "empty":
                mailbox_status, last_run = "Noch kein Lernlauf gestartet.", "Noch kein Lernlauf."
        store = getattr(self.site, "views", self.site).store if hasattr(self.site, "views") else self.site.store
        cfg = getattr(self.site.archive, "configuration", None)
        l_cfg = getattr(cfg.active, "learning", None) if cfg and hasattr(cfg, "active") else None
        run_hints_enabled = l_cfg.learning_run_hints_enabled if l_cfg is not None else True
        min_rejections = l_cfg.learning_run_hint_rejections if l_cfg is not None else 20
        learning_hint = get_learning_run_hint(store, enabled=run_hints_enabled, min_rejections=min_rejections)
        if learning_hint:
            body += learning_run_hint_banner(learning_hint, self.site.auth.csrf_token(session.id))
        body += '<div class="learning-options">' + self.card("Aus dem Postfach lernen", "/lernen/postfach",
                          "Sinnvoll, wenn du neue Themen in vorhandenen Mails entdecken möchtest. "
                          "Der lesende Lauf schlägt Themen, Filter und Ordner vor.", mailbox_status, last_run)
        service, more = self.site.rule_learning.service, ""
        if service is None:
            status, metric = "Regellernen derzeit nicht verfügbar.", "Noch keine Analyse."
        else:
            summary = service.overview("web:" + session.id)
            status = STATUSES[summary["status"]]
            if summary["status"] == "review":
                status = (f'Prüfentwurf mit {count_text(summary["proposals"], "Vorschlag", "Vorschlägen")} '
                          "wartet." if summary["owned"]
                          else "Prüfentwurf in einer anderen Sitzung.")
            metric = (count_text(summary["new_decisions"], "neue verwertbare Entscheidung",
                                 "neue verwertbare Entscheidungen") + " seit der letzten Analyse, "
                      f'{german_number(summary["all_decisions"])} verwertbare insgesamt.')
            if not summary["available"]:
                status = ("In prompts.yaml fehlt der Schritt decision_rule_learning. Den Block aus dem "
                          "mitgelieferten Beispiel übernehmen und die Konfiguration neu laden.")
                more = f'<p><a href="{RULE_HELP}">Hilfe zum Lernen aus Entscheidungen</a></p>'
        body += self.card("Aus Entscheidungen lernen", "/lernen/entscheidungen",
                          "Sinnvoll nach wiederholten Korrekturen oder Ablehnungen. Analysiert vorhandene "
                          "Entscheidungen und schlägt gezielte Änderungen deiner Themenregeln vor.", status, metric,
                          more)
        store = getattr(self.site, "views", self.site).store if hasattr(self.site, "views") else self.site.store
        report = evaluate_proposals(store)
        if report.summary.total_decided:
            prop_status = f"{round(report.summary.total_quote)} % Annahmequote"
            prop_metric = f"{report.summary.total_accepted} von {report.summary.total_decided} Vorschlägen angenommen."
        else:
            prop_status = "Noch keine entschiedenen Vorschläge."
            prop_metric = "Erste Auswertungen nach den ersten Entscheidungen."
        body += self.card("Vorschläge", "/lernen/vorschlaege",
                          "Annahmequote messen: Wie viele Vorschläge nimmst du an, wie viele verwirfst du? "
                          "Aufgeschlüsselt nach Art, Thema und Absender.",
                          prop_status, prop_metric, cost=False)
        body += '</div><p class="meta">Status wird automatisch lesend aktualisiert. '
        body += 'Das Öffnen dieser Seite startet keine Analyse.</p>'
        return Response.html(200, layout("Lernen", body, active="/lernen",
                                        fingerprint=self.fingerprint(session), state_url="/api/lernen/uebersicht"))

    @staticmethod
    def card(title: str, href: str, introduction: str, status: str, metric: str, more: str = "", cost: bool = True) -> str:
        cost_html = cost_hint() if cost else ""
        return (f'<section class="card stack"><h2>{e(title)}</h2><p>{e(introduction)}</p>'
                f'<p role="status">{e(status)}</p>{more}<p>{e(metric)}</p>' + cost_html
                + f'<p><a class="button" href="{href}">{e(title)} öffnen</a></p></section>')
