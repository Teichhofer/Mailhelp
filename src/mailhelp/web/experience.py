"""Authenticated 2.0 endpoints; normal HTML forms are the authoritative path."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from ..formatting import format_datetime_local
from ..i18n import msg, tr
from ..notifications.drafts import INTENTS
from .actions import new_key
from .auth import WebSession
from .http import Request, Response
from .pages import e, layout
from .push_site import PushSite

_EDITOR_TEXT_1 = msg(
    '<section class="card draft-box kind-draft" id="antwort" '
    'aria-labelledby="antwort-titel"><p class="kind"><span class="kind-label">✍️ '
    'Antwortentwurf</span></p><h2 id="antwort-titel">Antworten</h2><form method="post" '
    'action="/mail/{p0}/entwurf" class="draft-intents">{p1}<input type="hidden" '
    'name="mode" value="generate"><div class="actions">{p2}</div><p class="meta" '
    'role="status">Mailhelp formuliert einen Entwurf, den du vor dem Speichern prüfst. '
    "Mailhelp sendet keine E-Mails.</p></form>"
)

_EDITOR_TEXT_2 = msg(
    '<form method="post" action="/mail/{p0}/entwurf">{p1}<h3>Entwurf: {p2}</h3><label '
    'for="draft-editor">Antworttext</label><textarea id="draft-editor" name="text" '
    'rows="10" maxlength="8000" required{p3}>{p4}</textarea><div class="actions"><button '
    'class="button primary" name="mode" value="save">Als Entwurf im Postfach '
    "speichern</button>{p5}</div></form>"
)

if TYPE_CHECKING:
    from ..notifications.drafts import DraftService
    from ..notifications.webpush import PushService
    from .site import MailhelpSite


class ExperienceSite:
    def __init__(self, site: MailhelpSite) -> None:
        self.site = site
        # Attached by the experience runtime when Web-Push or reply drafts are available.
        self.push: PushService | None = None
        self.drafts: DraftService | None = None
        self.push_page = PushSite(self)
        route = site.app.route
        route("GET", "/briefing", site.signed_in(self.briefing))
        route("GET", "/api/push/public-key", site.signed_in(self.public_key))
        route("POST", "/api/push/subscribe", site.signed_in(self.subscribe))
        route("POST", "/api/push/unsubscribe", site.signed_in(self.unsubscribe))
        route("POST", r"/mail/(?P<mail_id>[a-f0-9]{24})/entwurf", site.signed_in(self.draft_action))

    def public_key(self, request: Request, session: WebSession) -> Response:
        if self.push is None:
            return Response.json(503, {"error": msg("Web-Push ist deaktiviert."), "code": "push_disabled"})
        return Response.json(200, {"public_key": self.push.public_key})

    def subscribe(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        return self._subscription(session, form, True)

    def unsubscribe(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        return self._subscription(session, form, False)

    def _subscription(self, session: WebSession, form: dict[str, str], subscribe: bool) -> Response:
        if self.push is None:
            return Response.json(503, {"error": msg("Web-Push ist deaktiviert."), "code": "push_disabled"})
        if form.get("public_key") and form["public_key"] != self.push.public_key:
            return Response.json(409, {"code": "key_conflict"})
        try:
            value = {**json.loads(form["subscription"])} if subscribe else None
            self.push.change(session.id, form.get("key", ""), value)
        except PermissionError:
            return Response.json(401, {"code": "session_expired"})
        except ValueError as exc:
            code = "provider_not_allowed" if str(exc) == "Ung\u00fcltiger Push-Anbieter" else "invalid_subscription"
            return Response.json(400, {"code": code})
        except (KeyError, TypeError):
            return Response.json(400, {"code": "invalid_subscription"})
        return Response.json(200, {"ok": True})

    def controls(self, csrf: str, actor: str | None = None) -> str:
        return self.push_page.controls(csrf, actor)

    def inbox_zero(self) -> str:
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
        parts = [
            (counts["event"], msg("Termin angelegt"), msg("Termine angelegt")),
            (counts["task"], msg("Aufgabe angelegt"), msg("Aufgaben angelegt")),
            (counts["already_exists"], msg("Duplikat vorab abgeglichen"), msg("Duplikate vorab abgeglichen")),
            (counts["rejected"], msg("Vorschlag verworfen"), msg("Vorschläge verworfen")),
        ]
        details = ", ".join(f"{count} {one if count == 1 else many}" for count, one, many in parts if count)
        total = sum(counts.values())
        summary = (
            tr(
                "Heute {p0} {p1} verarbeitet: {p2}.",
                p0=total,
                p1=msg("Vorgang") if total == 1 else msg("Vorgänge"),
                p2=details,
            )
            if total
            else msg("Heute noch keine Vorgänge abgeschlossen.")
        )
        # 5.0.10: today's results as tiles; colour marks the kind, the label names it.
        tiles = "".join(
            f'<div class="kpi {kind}"><dt>{label}</dt><dd>{counts[key]}</dd></div>'
            for key, kind, label in (
                ("event", "kind-event", msg("📅 Termine")),
                ("task", "kind-task", msg("✅ Aufgaben")),
                ("already_exists", "", "🔁 Abgleiche"),
                ("rejected", "", msg("🗑️ Verworfen")),
            )
        )
        last = site.views.system(now).last_processed
        when = format_datetime_local(last, zone) if last else msg("noch keine")
        return tr(
            (
                '<section class="card inbox-zero" '
                'aria-labelledby="inbox-zero"><p><span class="badge '
                'ok">✓</span></p><h2 id="inbox-zero">Alles erledigt! Keine '
                'offenen Entscheidungen.</h2><p>{p0}</p><dl class="kpi-tiles" '
                'aria-label="Heute">{p1}</dl><p class="meta">Letzte verarbeitete '
                'Mail: {p2} · <a href="/status">Serverstatus</a> · <a '
                'href="/briefing">Tagesüberblick</a></p></section>'
            ),
            p0=e(summary),
            p1=tiles,
            p2=e(when),
        )

    def briefing(self, request: Request, session: WebSession) -> Response:
        saved = self.site.views.store.load("briefing-latest", {})
        return Response.html(
            200,
            layout(
                msg("Tagesüberblick"),
                tr("<h1>Tagesüberblick</h1><pre>")
                + e(saved.get("text", msg("Noch kein Tagesüberblick verfügbar.")))
                + "</pre>",
            ),
        )

    def editor(self, mail_id: str, csrf: str) -> str:
        """Three reply intents on every mail; the chosen draft is edited, then saved or discarded."""
        if self.drafts is None or not self.drafts.available(mail_id):
            return ""
        draft = self.drafts.get(mail_id) or {"version": 0, "status": "discarded"}
        version, status = draft["version"], draft["status"]
        state = {
            "discarded": "",
            "editing": msg("Bitte prüfen und bei Bedarf bearbeiten."),
            "saved": msg("Als Entwurf im Postfach abgelegt."),
            "simulated": msg("Speicherung im Testmodus simuliert."),
            "uncertain": msg(
                
                    "Schreibresultat unklar. Erneut speichern gleicht zuerst mit dem Postfach "
                    "ab und legt den Entwurf nur an, wenn er dort fehlt."
                
            ),
        }[status]
        if draft.get("error"):
            state = draft["error"] + " " + state

        def hidden() -> str:
            # Each form has its own idempotency key; a replay never collides with another action.
            return (f'<input type="hidden" name="csrf" value="{e(csrf)}">'
                    f'<input type="hidden" name="key" value="{new_key()}">'
                    f'<input type="hidden" name="version" value="{version}">')

        # An unclear APPEND must be reconciled first; a new draft would hide it.
        locked = " disabled" if status == "uncertain" else ""
        buttons = "".join(
            f'<button class="button" name="intent" value="{intent}"{locked}>{label}</button>'
            for intent, label in (
                ("accept", msg("Zusagen")),
                ("decline", msg("Absagen")),
                ("question", msg("Rückfrage")),
            )
        )
        html = tr(
            (_EDITOR_TEXT_1),
            p0=mail_id,
            p1=hidden(),
            p2=buttons,
        )
        if state:
            html += f'<p role="status">{e(state)}</p>'
        if status in {"saved", "simulated"} and draft.get("text"):
            html += tr(
                (
                    '<label for="draft-preview">Antworttext</label><textarea id="draft-preview" '
                    'rows="10" readonly>{p0}</textarea>'
                ),
                p0=f"{e(draft['text'])}",
            )
        if status in {"editing", "uncertain"}:
            readonly = " readonly" if status == "uncertain" else ""
            cancel = ("" if status == "uncertain" else
                      f'<button class="button" name="mode" value="cancel" formnovalidate>{e(tr("Abbrechen"))}</button>')
            html += tr(
                (_EDITOR_TEXT_2),
                p0=mail_id,
                p1=hidden(),
                p2=e(INTENTS.get(draft.get("intent") or "", msg("Antwort"))),
                p3=readonly,
                p4=e(draft["text"]),
                p5=cancel,
            )
        if status != "discarded" and draft.get("text"):
            html += tr(
                
                    '<button type="button" class="button" data-copy-draft>Antworttext '
                    'kopieren</button><p class="meta" data-copy-status role="status" aria-live="polite"></p>'
                
            )
        return html + '</section>'

    @staticmethod
    def _draft_error(message: str) -> Response:
        return Response.html(
            409,
            layout(
                tr("Entwurf nicht gespeichert"),
                tr(
                    "<h1>Entwurf nicht gespeichert</h1><p>{p0}</p>",
                    p0=e(message),
                ),
            ),
        )

    def draft_action(self, request: Request, session: WebSession, form: dict[str, str], mail_id: str) -> Response:
        if self.drafts is None:
            return Response.text(503, msg("Antwort-Entwürfe sind deaktiviert."))
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
            return self._draft_error(msg("Der Antworttext muss 1 bis 8000 Zeichen lang sein."))
        except (ValueError, PermissionError) as exc:
            # Only Mailhelp's own messages; mail content never reaches an exception text.
            return self._draft_error(tr("{p0}. Bitte die Seite neu laden.", p0=f"{exc}"))
        except KeyError:
            return self._draft_error(msg("Das Formular ist unvollständig. Bitte die Seite neu laden."))
        except Exception:
            if mode == "generate":
                return Response.text(503, msg("Entwurf konnte nicht erstellt werden. Bitte später erneut versuchen."))
            return Response.text(503, msg("Postfach derzeit nicht erreichbar. Schreibstatus vor Wiederholung prüfen."))
        return Response.redirect('/mail/{p0}#antwort'.format(p0=f'{mail_id}'))
