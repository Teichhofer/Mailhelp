"""Authenticated 2.0 endpoints; normal HTML forms are the authoritative path."""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from ..drafts import INTENTS
from ..formatting import format_datetime_local
from .actions import new_key
from .http import Response
from .pages import e, layout
from .setting_help import EXTRA_HELP, help_bubble


class ExperienceSite:
    def __init__(self, site):
        self.site, self.push, self.drafts = site, None, None
        route = site.app.route
        route("GET", "/briefing", site.signed_in(self.briefing))
        route("GET", "/api/push/public-key", site.signed_in(self.public_key))
        route("POST", "/api/push/subscribe", site.signed_in(self.subscribe))
        route("POST", "/api/push/unsubscribe", site.signed_in(self.unsubscribe))
        route("POST", r"/mail/(?P<mail_id>[a-f0-9]{24})/entwurf", site.signed_in(self.draft_action))

    def public_key(self, request, session):
        if self.push is None:
            return Response.json(503, {"error": "Web-Push ist deaktiviert."})
        return Response.json(200, {"public_key": self.push.public_key})

    def subscribe(self, request, session, form):
        return self._subscription(session, form, True)

    def unsubscribe(self, request, session, form):
        return self._subscription(session, form, False)

    def _subscription(self, session, form, subscribe):
        if self.push is None:
            return Response.json(503, {"error": "Web-Push ist deaktiviert."})
        try:
            value = json.loads(form["subscription"]) if subscribe else None
            self.push.change(session.id, form.get("key", ""), value)
        except (ValueError, KeyError, TypeError, PermissionError):
            return Response.json(400, {"error": "Abonnement nicht gespeichert. "
                                                "Bitte neu anmelden und erneut versuchen."})
        return Response.json(200, {"ok": True})

    def controls(self, csrf):
        return ('<section class="card"><div class="setting-row"><h2>Benachrichtigungen</h2>'
                + help_bubble('push', 'Benachrichtigungen', EXTRA_HELP['push']) + '</div>'
                +
                f'<div id="push-controls" data-csrf="{e(csrf)}">'
                '<div class="actions">'
                '<button type="button" class="button primary" id="push-enable">Push aktivieren</button>'
                '<button type="button" class="button" id="push-disable">Push deaktivieren</button></div>'
                '<p id="push-status" role="status">HTTPS oder localhost erforderlich. '
                'Auf iOS zuerst zum Home-Bildschirm hinzufügen.</p></div>'
                '<p><a href="/briefing">Tagesüberblick lesen</a></p></section>')

    def inbox_zero(self):
        """The finished state: today's results and the last processing time."""
        site = self.site
        zone, now = ZoneInfo(site.configured_timezone), site.clock()
        today = now.astimezone(zone).date()
        latest = {}
        for row in sorted(site.archive.queries.history(), key=lambda row: row["at"]):
            if row["proposal_id"] and datetime.fromisoformat(row["at"]).astimezone(zone).date() == today:
                latest[(row["mail_id"], row["proposal_id"])] = row
        counts = {"event": 0, "task": 0, "already_exists": 0, "rejected": 0}
        for row in latest.values():
            if row["status"] in {"created", "simulated"} and row["proposal_kind"] in counts:
                counts[row["proposal_kind"]] += 1
            elif row["status"] in counts:
                counts[row["status"]] += 1
        parts = [(counts["event"], "Termin angelegt", "Termine angelegt"),
                 (counts["task"], "Aufgabe angelegt", "Aufgaben angelegt"),
                 (counts["already_exists"], "Duplikat vorab abgeglichen", "Duplikate vorab abgeglichen"),
                 (counts["rejected"], "Vorschlag verworfen", "Vorschläge verworfen")]
        details = ", ".join(f"{count} {one if count == 1 else many}" for count, one, many in parts if count)
        total = sum(counts.values())
        summary = (f"Heute {total} {'Vorgang' if total == 1 else 'Vorgänge'} verarbeitet: {details}."
                   if total else "Heute noch keine Vorgänge abgeschlossen.")
        last = site.views.system(now).last_processed
        when = format_datetime_local(last, zone) if last else "noch keine"
        return ('<section class="card inbox-zero" aria-labelledby="inbox-zero">'
                '<p><span class="badge ok">✓</span></p>'
                '<h2 id="inbox-zero">Alles erledigt! Keine offenen Entscheidungen.</h2>'
                f'<p>{e(summary)}</p><p class="meta">Letzte verarbeitete Mail: {e(when)} · '
                '<a href="/status">Serverstatus</a> · <a href="/briefing">Tagesüberblick</a></p></section>')

    def briefing(self, request, session):
        saved = self.site.views.store.load("briefing-latest", {})
        return Response.html(200, layout("Tagesüberblick", '<h1>Tagesüberblick</h1><pre>'
            + e(saved.get("text", "Noch kein Tagesüberblick verfügbar.")) + '</pre>'))

    def editor(self, mail_id, csrf):
        """Three reply intents on every mail; the chosen draft is edited, then saved or discarded."""
        if self.drafts is None or not self.drafts.available(mail_id):
            return ""
        draft = self.drafts.get(mail_id) or {"version": 0, "status": "discarded"}
        version, status = draft["version"], draft["status"]
        state = {"discarded": "", "editing": "Bitte prüfen und bei Bedarf bearbeiten.",
                 "saved": "Im Postfach gespeichert.", "simulated": "Speicherung im Testmodus simuliert.",
                 "uncertain": "Schreibresultat unklar. Erneut speichern gleicht zuerst mit dem Postfach ab "
                              "und legt den Entwurf nur an, wenn er dort fehlt."}[status]
        if draft.get("error"):
            state = draft["error"] + " " + state
        def hidden():
            # Each form has its own idempotency key; a replay never collides with another action.
            return (f'<input type="hidden" name="csrf" value="{e(csrf)}">'
                    f'<input type="hidden" name="key" value="{new_key()}">'
                    f'<input type="hidden" name="version" value="{version}">')
        # An unclear APPEND must be reconciled first; a new draft would hide it.
        locked = " disabled" if status == "uncertain" else ""
        buttons = "".join(f'<button class="button" name="intent" value="{intent}"{locked}>{label}</button>'
                          for intent, label in (("accept", "Zusagen"), ("decline", "Absagen"),
                                                ("question", "Rückfrage")))
        html = (f'<section class="card draft-box" id="antwort" aria-labelledby="antwort-titel">'
                f'<h2 id="antwort-titel">Antworten</h2>'
                f'<form method="post" action="/mail/{mail_id}/entwurf" class="draft-intents">{hidden()}'
                f'<input type="hidden" name="mode" value="generate"><div class="actions">{buttons}</div>'
                '<p class="meta" role="status">Mailhelp formuliert einen Entwurf, den du vor dem Speichern '
                'prüfst. Mailhelp sendet keine E-Mails.</p></form>')
        if state:
            html += f'<p role="status">{e(state)}</p>'
        if status in {"editing", "uncertain"}:
            readonly = " readonly" if status == "uncertain" else ""
            cancel = ("" if status == "uncertain" else
                      '<button class="button" name="mode" value="cancel" formnovalidate>Abbrechen</button>')
            html += (f'<form method="post" action="/mail/{mail_id}/entwurf">{hidden()}'
                     f'<h3>Entwurf: {e(INTENTS.get(draft.get("intent") or "", "Antwort"))}</h3>'
                     f'<label for="draft-editor">Antworttext</label><textarea id="draft-editor" name="text" '
                     f'rows="10" maxlength="8000" required{readonly}>{e(draft["text"])}</textarea>'
                     '<div class="actions"><button class="button primary" name="mode" value="save">'
                     f'Als Entwurf im Postfach speichern</button>{cancel}</div></form>')
        return html + '</section>'

    @staticmethod
    def _draft_error(message):
        return Response.html(409, layout("Entwurf nicht gespeichert", '<h1>Entwurf nicht gespeichert</h1>'
                                         f'<p>{e(message)}</p>'))

    def draft_action(self, request, session, form, mail_id):
        if self.drafts is None:
            return Response.text(503, "Antwort-Entwürfe sind deaktiviert.")
        mode = form.get("mode")
        try:
            if mode not in {"generate", "save", "cancel"}:
                raise ValueError("Aktion fehlt")
            if not form["version"].isdecimal() or len(form["version"]) > 6:
                raise ValueError("Ungültige Entwurfsversion")
            version = int(form["version"])
            if mode == "generate":
                self.drafts.generate(session.id, mail_id, version, form["key"], form.get("intent", ""))
            elif mode == "cancel":
                self.drafts.cancel(session.id, mail_id, version, form["key"])
            else:
                self.drafts.act(session.id, mail_id, version, form["key"], form["text"])
        except ValidationError:
            return self._draft_error("Der Antworttext muss 1 bis 8000 Zeichen lang sein.")
        except (ValueError, PermissionError) as exc:
            # Only Mailhelp's own messages; mail content never reaches an exception text.
            return self._draft_error(f"{exc}. Bitte die Seite neu laden.")
        except KeyError:
            return self._draft_error("Das Formular ist unvollständig. Bitte die Seite neu laden.")
        except Exception:
            if mode == "generate":
                return Response.text(503, "Entwurf konnte nicht erstellt werden. Bitte später erneut versuchen.")
            return Response.text(503, "Postfach derzeit nicht erreichbar. Schreibstatus vor Wiederholung prüfen.")
        return Response.redirect(f"/mail/{mail_id}#antwort")
