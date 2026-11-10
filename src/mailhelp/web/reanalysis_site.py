"""5.1 (R6): "Aufgabe oder Termin übersehen?" on the mail page.

Starting, cancelling and adopting are web actions: the signed-in session and the
CSRF token are checked by the site, the analysis round and the shown proposal
versions are checked again when the action runs, and an idempotency key makes a
repeated click harmless. Adopting a result never approves an external write.
"""
from __future__ import annotations

import json
import secrets
from typing import TYPE_CHECKING, Any

from .. import state_names
from ..domain.mail import MailState
from ..domain.reanalysis import ACTIVE, ReanalysisJob, ReanalysisStatus, adoption_pending
from ..processing.reanalysis import ReanalysisRefused
from ..processing.reanalysis_adoption import Change, Comparison
from .auth import WebSession
from .http import Request, Response
from .pages import e, notice

if TYPE_CHECKING:
    from .site import MailhelpSite

STATUS_TEXT = {
    ReanalysisStatus.QUEUED: "Wartet auf den Start.",
    ReanalysisStatus.RUNNING: "Läuft – die Seite zeigt das Ergebnis nach dem Neuladen.",
    ReanalysisStatus.COMPLETED: "Abgeschlossen.",
    ReanalysisStatus.FAILED: "Fehlgeschlagen.",
    ReanalysisStatus.CANCELLED: "Abgebrochen.",
}
ERROR_TEXT = {
    "mail_missing": "Die Mail ist im Postfach nicht mehr abrufbar.",
    "uidvalidity_changed": "Das Postfach wurde neu nummeriert; die ursprüngliche Mail ist nicht mehr eindeutig.",
    "mailbox_unavailable": "Das Postfach ist nicht erreichbar.",
    "budget_exhausted": "Das Aufrufbudget dieser Nachanalyse ist aufgebraucht.",
    "model_failed": "Das Modell hat wiederholt keine verwertbare Antwort geliefert.",
    "stale_round": "Die Mail wurde inzwischen erneut ausgewertet.",
    "session_ended": "Die Sitzung, die die Nachanalyse gestartet hat, wurde beendet.",
}
REFUSED_TEXT = {
    "disabled": "Die Nachanalyse ist in den Einstellungen ausgeschaltet.",
    "stale": "Die Mail wurde inzwischen erneut ausgewertet. Bitte die Seite neu laden.",
    "processing": "Die Mail wird gerade noch verarbeitet.",
    "daily_limit": "Das Tageslimit für Nachanalysen ist erreicht.",
    "key_conflict": "Das Formular gehört zu einer anderen Mail. Bitte die Seite neu laden.",
    "not_completed": "Diese Nachanalyse ist nicht abgeschlossen.",
    "already_adopted": "Dieses Ergebnis wurde bereits übernommen.",
    "mail_missing": "Die Mail ist nicht mehr vorhanden.",
    "session_ended": "Die Sitzung wurde inzwischen beendet. Bitte erneut anmelden und neu starten.",
}
# Refusals after which this result can no longer be adopted; a new analysis is offered.
FINAL_REFUSALS = {"stale", "already_adopted", "mail_missing"}
CHANGE_TEXT = {
    Change.UNCHANGED: "Unverändert",
    Change.NEW: "Neu – wird als unbestätigter Vorschlag übernommen",
    Change.CHANGED: "Geändert – wird als neue Version übernommen",
    Change.PROTECTED: "Bereits angelegt oder in Anlage – bleibt unverändert",
    Change.REJECTED: "Früher verworfen – bleibt verworfen",
    Change.MISSING: "Nicht mehr erkannt – bleibt erhalten",
}
FIELD_NAMES = {"kind": "Art", "title": "Titel", "description": "Beschreibung", "due": "Frist", "start": "Beginn",
               "end": "Ende", "all_day": "Ganztägig", "location": "Ort", "responsibility": "Zuständigkeit",
               "certainty": "Sicherheit", "classification": "Einordnung", "open_questions": "Offene Fragen"}


class ReanalysisSite:
    def __init__(self, site: MailhelpSite, worker: Any):
        self.site, self.worker = site, worker
        route = site.app.route
        route("POST", r"/mail/(?P<mail_id>[a-f0-9]{24})/nachanalyse", site.signed_in(self.start))
        route("POST", r"/mail/(?P<mail_id>[a-f0-9]{24})/nachanalyse/(?P<job_id>[a-f0-9]{32})/abbrechen",
              site.signed_in(self.cancel))
        route("POST", r"/mail/(?P<mail_id>[a-f0-9]{24})/nachanalyse/(?P<job_id>[a-f0-9]{32})/uebernehmen",
              site.signed_in(self.adopt))
        site.reanalysis_page = self

    def _state(self, mail_id: str) -> MailState | None:
        state = self.site.views.store.peek_model(state_names.mail(mail_id), MailState)
        return state if isinstance(state, MailState) else None

    @staticmethod
    def _hidden(csrf: str, **fields: Any) -> str:
        values = {"csrf": csrf, "key": secrets.token_urlsafe(16), **fields}
        return "".join(f'<input type="hidden" name="{name}" value="{e(str(value))}">' for name, value in values.items())

    def section(self, mail_id: str, csrf: str) -> str:
        state = self._state(mail_id)
        if state is None or state.steps.completion != "completed":
            return ""
        jobs = self.worker.jobs.for_mail(mail_id)
        latest = jobs[-1] if jobs else None
        body = ('<section class="card reanalysis" id="nachanalyse" aria-labelledby="nachanalyse-titel">'
                '<h2 id="nachanalyse-titel">Aufgabe oder Termin übersehen?</h2>')
        if latest is not None and latest.source_round == state.analysis_round:
            body += self._job(latest, csrf)
            if latest.status in ACTIVE or self._awaiting_adoption(latest):
                return body + "</section>"
        return body + self._offer(state, csrf) + "</section>"

    def _awaiting_adoption(self, job: ReanalysisJob) -> bool:
        """A result that can still be adopted holds back a new start for the same round."""
        if job.status != ReanalysisStatus.COMPLETED or job.adopted_at is not None:
            return False
        if job.adoption_error in FINAL_REFUSALS:
            return False
        comparison = self.worker.adoption.comparison(job.id)
        return comparison is not None and comparison.adoptable

    def _offer(self, state: MailState, csrf: str) -> str:
        settings = self.worker.jobs.settings
        if not settings.enabled:
            return "<p>Die Nachanalyse ist in den Einstellungen ausgeschaltet.</p>"
        today = sum(job.created_at.date() == self.worker.jobs.clock().date() for job in self.worker.jobs.all())
        left = max(0, settings.max_jobs_per_day - today)
        return (f'<p>Mailhelp analysiert diese Mail (Analyserunde {state.analysis_round}) mit den aktuellen '
                'Einstellungen erneut. Bestehende Vorschläge und Entscheidungen bleiben erhalten; neue Befunde '
                'erscheinen nur als unbestätigte Vorschläge, nichts wird automatisch angelegt.</p>'
                f'<p class="meta">Budget: höchstens {settings.max_llm_calls_per_job} kostenpflichtige Modellaufrufe; '
                f'heute noch {left} von {settings.max_jobs_per_day} Nachanalysen möglich. Die tatsächlichen '
                'Kosten zeigt die Auswertung.</p>'
                f'<form method="post" action="/mail/{state.id}/nachanalyse">'
                + self._hidden(csrf, round=state.analysis_round)
                + '<label for="nachanalyse-hinweis">Hinweis für die Analyse (optional)</label>'
                '<textarea id="nachanalyse-hinweis" name="hint" rows="2" maxlength="500" '
                'placeholder="z. B. Bitte die Rückmeldefrist prüfen"></textarea>'
                + ('<button class="button primary" type="submit" disabled>Tageslimit erreicht</button>' if not left
                   else '<button class="button primary" type="submit">Erneut analysieren</button>')
                + '</form>')

    def _job(self, job: ReanalysisJob, csrf: str) -> str:
        text = STATUS_TEXT[job.status]
        if job.error is not None:
            text += " " + ERROR_TEXT[job.error.value]
        body = (f'<p role="status"><strong>Nachanalyse:</strong> {e(text)} '
                f'<span class="meta">{job.llm_calls} von {job.max_llm_calls} Modellaufrufen</span></p>')
        if job.status in ACTIVE:
            body += (f'<form method="post" action="/mail/{job.mail_id}/nachanalyse/{job.id}/abbrechen">'
                     + self._hidden(csrf)
                     + '<button class="button" type="submit">Nachanalyse abbrechen</button></form>')
        if job.status == ReanalysisStatus.COMPLETED:
            comparison = self.worker.adoption.comparison(job.id)
            if comparison is not None:
                body += self._comparison(comparison, job, csrf)
        return body

    def _comparison(self, comparison: Comparison, job: ReanalysisJob, csrf: str) -> str:
        rows = ""
        for item in comparison.items:
            shown = item.candidate or item.existing
            assert shown is not None
            fields = (f' <span class="meta">Geändert: {e(", ".join(FIELD_NAMES[name] for name in item.fields))}</span>'
                      if item.fields else "")
            rows += (f'<li class="change-{item.change.value}"><strong>{e(shown.title)}</strong> · '
                     f'{e(CHANGE_TEXT[item.change])}{fields}</li>')
        body = f'<h3>Vorher und nachher</h3><ul class="reanalysis-changes">{rows or "<li>Keine Vorschläge.</li>"}</ul>'
        if job.adopted_at is not None:
            return body + "<p>Übernommen. Die Vorschläge warten auf deine Bestätigung.</p>"
        if adoption_pending(job):
            return body + '<p role="status">Die Übernahme wird ausgeführt – bitte die Seite gleich neu laden.</p>'
        if job.adoption_error is not None:
            body += notice(REFUSED_TEXT.get(job.adoption_error, "Die Übernahme wurde abgelehnt."), "warn")
            if job.adoption_error in FINAL_REFUSALS:
                return body
        if not comparison.adoptable:
            return body + "<p>Die Nachanalyse ergab nichts Neues; es gibt nichts zu übernehmen.</p>"
        return (body + f'<form method="post" action="/mail/{job.mail_id}/nachanalyse/{job.id}/uebernehmen">'
                + self._hidden(csrf, round=comparison.analysis_round,
                               versions=json.dumps(comparison.versions, sort_keys=True))
                + '<p class="meta">Die Übernahme legt nichts an. Jeder Vorschlag braucht danach deine Bestätigung.</p>'
                  '<button class="button primary" type="submit">Ergebnis übernehmen</button></form>')

    def _reply(self, request: Request, message: str) -> Response:
        return self.site._reply(request, 409, message)

    def start(self, request: Request, session: WebSession, form: dict[str, str], mail_id: str) -> Response:
        state = self._state(mail_id)
        if state is None:
            return self._reply(request, REFUSED_TEXT["mail_missing"])
        try:
            expected = int(form["round"])
            self.worker.jobs.start(state, expected_round=expected, hint=form.get("hint"), key=form["key"],
                                   actor=f"web:{session.id}")
        except (KeyError, ValueError) as exc:
            reason = exc.reason if isinstance(exc, ReanalysisRefused) else ""
            return self._reply(request, REFUSED_TEXT.get(reason, "Das Formular ist unvollständig. Bitte neu laden."))
        self.worker.wake()
        return Response.redirect(f"/mail/{mail_id}#nachanalyse")

    def cancel(self, request: Request, session: WebSession, form: dict[str, str], mail_id: str,
               job_id: str) -> Response:
        job = self.worker.jobs.get(job_id)
        if job is None or job.mail_id != mail_id:
            return self._reply(request, REFUSED_TEXT["mail_missing"])
        self.worker.jobs.cancel(job_id)
        return Response.redirect(f"/mail/{mail_id}#nachanalyse")

    def adopt(self, request: Request, session: WebSession, form: dict[str, str], mail_id: str,
              job_id: str) -> Response:
        job = self.worker.jobs.get(job_id)
        if job is None or job.mail_id != mail_id:
            return self._reply(request, REFUSED_TEXT["mail_missing"])
        try:
            versions = json.loads(form["versions"])
            if not isinstance(versions, dict) or not all(
                    isinstance(key, str) and type(value) is int for key, value in versions.items()):
                raise ValueError("versions")
            self.worker.jobs.request_adoption(job_id, expected_round=int(form["round"]), expected_versions=versions,
                                              actor=f"web:{session.id}")
        except (KeyError, ValueError) as exc:
            reason = exc.reason if isinstance(exc, ReanalysisRefused) else ""
            return self._reply(request, REFUSED_TEXT.get(reason, "Das Formular ist unvollständig. Bitte neu laden."))
        self.worker.wake()
        return Response.redirect(f"/mail/{mail_id}#nachanalyse")

