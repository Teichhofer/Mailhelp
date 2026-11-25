"""One authenticated entry point; overview links never start a paid operation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..i18n import msg, tr
from ..review.proposal_evaluation import evaluate_proposals, get_learning_run_hint
from ..review.views import german_number
from ..rule_learning.service import digest
from .http import Response
from .labels import count_text
from .learning_pages import UPDATED, cost_hint, heading
from .learning_site import LABELS
from .pages import e, layout
from .proposal_evaluation_pages import learning_run_hint_banner
from .rule_learning_site import NOT_SET_UP, STATUSES

RULE_HELP = "/hilfe/dokumentation/bedienung/aus-entscheidungen-lernen"


def run_date(timestamp: float, timezone: str) -> str:
    return datetime.fromtimestamp(timestamp, UTC).astimezone(ZoneInfo(timezone)).strftime("%d.%m.%Y, %H:%M")


class LearningOverviewSite:
    def __init__(self, site: Any) -> None:
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
        return Response.html(
            409,
            layout(
                msg("Lernseite aktualisiert"),
                heading(msg("Lernseite aktualisiert"), UPDATED)
                + tr('<p><a class="button" href="/lernen/postfach">Aus dem Postfach lernen</a></p>'),
                active="/lernen",
            ),
        )

    def home(self, request: Any, session: Any) -> Response:
        customer = not self.site.auth.is_operator(session)
        body = heading(
            msg("Lernen"),
            msg(
                
                    "Verbessere deine Themenregeln: mit einem Lernlauf aus dem Postfach oder "
                    "mit den bereits protokollierten Entscheidungen."
                
            ),
            back=False,
        )
        mailbox_status, last_run = _mailbox_progress(self)
        store = getattr(self.site, "views", self.site).store if hasattr(self.site, "views") else self.site.store
        cfg = getattr(self.site.archive, "configuration", None)
        l_cfg = getattr(cfg.active, "learning", None) if cfg and hasattr(cfg, "active") else None
        run_hints_enabled = l_cfg.learning_run_hints_enabled if l_cfg is not None else True
        min_rejections = l_cfg.learning_run_hint_rejections if l_cfg is not None else 20
        learning_hint = get_learning_run_hint(store, enabled=run_hints_enabled, min_rejections=min_rejections)
        if learning_hint:
            body += learning_run_hint_banner(learning_hint, self.site.auth.csrf_token(session.id))
        body += '<div class="learning-options">' + self.card(
            msg("Aus dem Postfach lernen"),
            "/lernen/postfach",
            msg(
                
                    "Sinnvoll, wenn du neue Themen in vorhandenen Mails entdecken möchtest. Der "
                    "lesende Lauf schlägt Themen, Filter und Ordner vor."
                
            ),
            mailbox_status,
            last_run,
            customer=customer,
        )
        body += _decision_card(self, session, customer)
        store = getattr(self.site, "views", self.site).store if hasattr(self.site, "views") else self.site.store
        report = evaluate_proposals(store)
        if report.summary.total_decided:
            prop_status = tr("{p0} % Annahmequote", p0=f"{round(report.summary.total_quote)}")
            prop_metric = tr(
                "{p0} von {p1} Vorschlägen angenommen.",
                p0=report.summary.total_accepted,
                p1=report.summary.total_decided,
            )
        else:
            prop_status = msg("Noch keine entschiedenen Vorschläge.")
            prop_metric = msg("Erste Auswertungen nach den ersten Entscheidungen.")
        body += self.card(
            msg("Vorschläge"),
            "/lernen/vorschlaege",
            msg(
                
                    "Annahmequote messen: Wie viele Vorschläge nimmst du an, wie viele "
                    "verwirfst du? Aufgeschlüsselt nach Art, Thema und Absender."
                
            ),
            prop_status,
            prop_metric,
            cost=False,
        )
        body += tr('</div><p class="meta">Status wird automatisch lesend aktualisiert. ')
        body += tr("Das Öffnen dieser Seite startet keine Analyse.</p>")
        return Response.html(
            200,
            layout(
                msg("Lernen"),
                body,
                active="/lernen",
                fingerprint=self.fingerprint(session),
                state_url="/api/lernen/uebersicht",
            ),
        )

    @staticmethod
    def card(title: str, href: str, introduction: str, status: str, metric: str,
             more: str = "", cost: bool = True, customer: bool = False) -> str:
        cost_html = cost_hint(customer) if cost else ""
        return (
            f'<section class="card stack"><h2>{e(title)}</h2><p>{e(introduction)}</p>'
            f'<p role="status">{e(status)}</p>{more}<p>{e(metric)}</p>'
            + cost_html
            + tr('<p><a class="button" href="{p0}">{p1} öffnen</a></p></section>', p0=href, p1=e(title))
        )


def _decision_card(self: LearningOverviewSite, session: Any, customer: bool = False) -> str:
    body = ""
    service, more = self.site.rule_learning.service, ""
    if service is None:
        status, metric = msg("Regellernen derzeit nicht verfügbar."), msg("Noch keine Analyse.")
    else:
        summary = service.overview("web:" + session.id)
        status = STATUSES[summary["status"]]
        if summary["status"] == "review":
            status = (
                tr(
                    "Prüfentwurf mit {p0} wartet.",
                    p0=count_text(summary["proposals"], msg("Vorschlag"), msg("Vorschlägen")),
                )
                if summary["owned"]
                else msg("Prüfentwurf in einer anderen Sitzung.")
            )
        metric = count_text(
            summary["new_decisions"], msg("neue verwertbare Entscheidung"), msg("neue verwertbare Entscheidungen")
        ) + tr(" seit der letzten Analyse, {p0} verwertbare insgesamt.", p0=german_number(summary["all_decisions"]))
        if not summary["available"] and customer:
            status = NOT_SET_UP
        elif not summary["available"]:
            status = msg(

                    "In prompts.yaml fehlt der Schritt decision_rule_learning. Den Block aus "
                    "dem mitgelieferten Beispiel übernehmen und die Konfiguration neu laden."

            )
            more = tr('<p><a href="{p0}">Hilfe zum Lernen aus Entscheidungen</a></p>', p0=RULE_HELP)
    body += self.card(
        msg("Aus Entscheidungen lernen"),
        "/lernen/entscheidungen",
        msg(

                "Sinnvoll nach wiederholten Korrekturen oder Ablehnungen. Analysiert "
                "vorhandene Entscheidungen und schlägt gezielte Änderungen deiner Themenregeln vor."

        ),
        status,
        metric,
        more,
        customer=customer,
    )
    return body


def _mailbox_progress(self: LearningOverviewSite) -> tuple[str, str]:
    if self.worker is None:
        mailbox_status, last_run = msg("Lernlauf derzeit nicht verfügbar."), msg("Noch kein Lernlauf.")
    else:
        state = self.worker.jobs.state()
        mailbox_status = tr(
            "{p0}: {p1} geprüft", p0=LABELS[state.status], p1=count_text(state.cursor, "Mail", "Mails")
        )
        if state.selection is not None:
            mailbox_status += tr(" von {p0} ausgewählten Mails", p0=state.selection.count)
        last_run = (
            msg("Letzter Lauf: ") + run_date(state.started_at, self.site.configured_timezone)
            if state.started_at
            else msg("Datum früherer Läufe nicht verfügbar.")
        )
        if state.status == "empty":
            mailbox_status, last_run = msg("Noch kein Lernlauf gestartet."), msg("Noch kein Lernlauf.")
    return mailbox_status, last_run
