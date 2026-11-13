"""Alt/new topic review with editable fields and strict server-side validation."""
from __future__ import annotations

import json
import secrets
from typing import Any

from ..rule_learning.mining import MAX_EVIDENCE, MAX_EVIDENCE_ALL
from ..rule_learning.models import RuleState, RuleTopic
from ..rule_learning.service import DecisionRuleLearning
from ..rule_learning.validation import RuleConflict, parse_yaml
from ..storage import CorruptState
from . import rule_preview
from .auth import WebSession
from .http import Request, Response
from .learning_overview import UPDATED
from .learning_pages import heading
from .pages import e, layout, notice
from .rule_compare import compare
from .site import MailhelpSite

LABELS = {"id": "Themen-ID", "name": "Name", "description": "Beschreibung",
          "examples": "Beispiele (ein Eintrag je Zeile)", "exclusions": "Ausschlüsse (ein Eintrag je Zeile)",
          "enabled": "Aktiv", "mailboxes": "Geltungsbereich"}
SIGNALS = {"positive_already_done": "Bereits erledigt (relevant)", "rejected_proposal": "Vorschlag abgelehnt",
           "manual_correction": "Von Hand korrigiert", "relevance_disagreement": "Relevanz korrigiert",
           "unclassified_confirmation": "Bestätigt ohne Thema"}
SCOPE_LABELS = {"new": "nur neue seit der letzten Analyse", "all": "alle bisherigen"}
STATUSES = {"empty": "Bereit", "queued": "Wartet", "running": "Analyse läuft", "review": "Vorschläge prüfen",
            "committing": "Übernahme unvollständig", "done": "Übernommen", "failed": "Analyse fehlgeschlagen",
            "interrupted": "Analyse unterbrochen"}


DECISIONS = {"accept": "Übernehmen", "reject": "Verwerfen – nicht wieder vorschlagen", "open": "Offen lassen"}


def count_text(accepted: int, rejected: int) -> str:
    """6.0.4: e.g. "2 zur Übernahme ausgewählt · 1 zum Verwerfen markiert." (learning.js uses the same)."""
    return f"{accepted} zur Übernahme ausgewählt · {rejected} zum Verwerfen markiert."


class RuleLearningSite:
    def __init__(self, site: MailhelpSite):
        self.site = site
        self.service: DecisionRuleLearning | None = None
        site.app.route("GET", "/lernen/entscheidungen", site.signed_in(self.home))
        site.app.route("POST", "/lernen/entscheidungen", site.signed_in(self.act))
        site.app.route("GET", "/themen/lernen", site.signed_in(self.legacy))
        site.app.route("POST", "/themen/lernen", site.signed_in(self.legacy_post))

    def legacy(self, request: Request, session: WebSession) -> Response:
        return Response(308, headers={"Location": "/lernen/entscheidungen"})

    def legacy_post(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        return self.render(session, 409, UPDATED)

    def home(self, request: Request, session: WebSession) -> Response:
        return self.render(session)

    def render(self, session: WebSession, status: int = 200, message: str = "",
               values: dict[str, str] | None = None) -> Response:
        if self.service is None:
            return Response.html(503, layout("Regellernen", notice("Regellernen ist nicht verfügbar.")))
        state = self.service.state("web:" + session.id)
        if state.status == "review" and values is None:
            try:
                values = rule_preview.editing(self.service, "web:" + session.id, state.version)
            except (OSError, CorruptState):
                status, message = 503, "Prüfstand nicht lesbar. Bitte Eingaben erneut prüfen."
        content = heading("Aus Entscheidungen lernen", "Sinnvoll nach wiederholten Korrekturen oder Ablehnungen: "
                          "Verbessern Sie Regeln mit den bereits protokollierten Entscheidungen. "
                          "Vorschläge werden vor jeder Übernahme einzeln geprüft.")
        content += notice(message, "error") if message else ""
        content += notice(state.message) if state.message else ""
        content += f'<p role="status">Analysestand: {e(STATUSES[state.status])} · Version {state.version}</p>'
        if state.status == "review":
            content += self.review(session, state, values or {})
        if state.status in {"empty", "done", "failed", "interrupted", "review"}:
            if state.status == "review":
                content += ('<details class="rule-reanalyze">'
                            '<summary>Neue kostenpflichtige Analyse vorbereiten</summary>')
            content += self.form(session, state, "analyze", (
                self.scopes(session, (values or {}).get("scope", "new"))
                + '<p>Die gewählten Entscheidungen werden mit den aktuellen Themenregeln analysiert. Betreff, '
                'begrenzte Textauszüge und Korrekturen gehen an den aktiven KI-Anbieter. Das kann Kosten '
                'verursachen. Es werden keine Mails abgerufen oder externen Einträge angelegt.</p>'
                '<label><input type="checkbox" name="confirm" value="yes" required> '
                'Datenübertragung und kostenpflichtige Analyse ausdrücklich starten</label>'
                '<p>Eine neue Analyse ersetzt einen noch offenen Prüfentwurf.</p>'
                '<button class="button" type="submit">Entscheidungen analysieren</button>'))
            if state.status == "review":
                content += '</details>'
        if state.status == "committing":
            content += self.form(session, state, "resume", (
                '<p>Eine bereits bestätigte lokale Übernahme ist unvollständig. Fortsetzen prüft alle '
                'Dateirevisionen erneut und startet keinen KI-Aufruf.</p>'
                '<label><input type="checkbox" name="confirm" value="yes" required> '
                'Bereits bestätigte Übernahme ausdrücklich abschließen</label>'
                '<button class="button" type="submit">Übernahme abschließen</button>'))
        content += self.rejected_list(session)
        return Response.html(status, layout("Regellernen", content, active="/lernen",
                                            refresh=2 if state.status in {"queued", "running"} else None))

    def rejected_list(self, session: WebSession) -> str:
        """6.0.4: earlier rejections with date and change; each can be admitted again."""
        assert self.service is not None
        history = self.service.history()
        if not history.rejected:
            return ""
        from datetime import UTC, datetime

        from .rule_preview import ACTIONS
        names = {"add_examples": "+ Beispiel", "remove_examples": "− Beispiel", "add_exclusions": "+ Ausschluss",
                 "remove_exclusions": "− Ausschluss", "name": "Name", "description": "Beschreibung",
                 "enabled": "Aktiv"}
        body = (f'<details class="rule-rejected" id="verworfen"><summary>Zuvor verworfene Vorschläge anzeigen '
                f'({len(history.rejected)})</summary><ul>')
        for item in reversed(history.rejected):
            changes = [f"{names[key]}: {'Ja' if value is True else 'Nein' if value is False else value}"
                       for key, value in item.changes.model_dump().items() if key in ("name", "description",
                                                                                    "enabled") and value is not None]
            changes += [f"{names[key]}: {entry}" for key, entries in item.changes.model_dump().items()
                        if isinstance(entries, list) for entry in entries]
            day = datetime.fromtimestamp(item.rejected_at, UTC).strftime("%d.%m.%Y")
            body += (f'<li><p><strong>{e(item.topic_name)}</strong> · {e(ACTIONS[item.action])} · '
                     f'{"relevant" if item.category == "relevant" else "Ausschlussthema"} · verworfen am {day}</p>'
                     + (f'<ul class="rule-rejected-changes">{"".join(f"<li>{e(text)}</li>" for text in changes)}'
                        '</ul>' if changes else "")
                     + '<form method="post" action="/lernen/entscheidungen">'
                     f'<input type="hidden" name="csrf" value="{e(self.site.auth.csrf_token(session.id))}">'
                     f'<input type="hidden" name="key" value="{secrets.token_hex(16)}">'
                     '<input type="hidden" name="action" value="readmit">'
                     f'<input type="hidden" name="rejected_version" value="{history.rejected_version}">'
                     f'<input type="hidden" name="fingerprint" value="{item.fingerprint}">'
                     f'<button class="button small" type="submit" aria-label="{e(item.topic_name)} wieder zulassen">'
                     'Wieder zulassen</button></form></li>')
        return body + "</ul></details>"

    def scopes(self, session: WebSession, chosen: str) -> str:
        """5.7.6: only the decisions since the last analysis, or every usable one in the log."""
        assert self.service is not None
        summary = self.service.overview("web:" + session.id)
        options = (("new", f'Nur neue Entscheidungen seit der letzten Analyse ({summary["new_decisions"]})',
                    f"Höchstens {MAX_EVIDENCE}, neueste zuerst; bereits analysierte werden übersprungen."),
                   ("all", f'Alle bisherigen verwertbaren Entscheidungen ({summary["all_decisions"]})',
                    f"Höchstens {MAX_EVIDENCE_ALL}, neueste zuerst. Mehr Belege, höhere Kosten; die "
                    "Nutzlastgrenze kann ältere Belege auslassen."))
        body = '<fieldset class="rule-scope"><legend>Welche Entscheidungen?</legend>'
        for value, label, hint in options:
            checked = " checked" if value == chosen else ""
            body += (f'<label><input type="radio" name="scope" value="{value}"{checked}> {e(label)}</label>'
                     f'<p class="meta">{e(hint)}</p>')
        return body + "</fieldset>"

    def form(self, session: WebSession, state: RuleState, action: str, body: str, key: str = "") -> str:
        return ('<form method="post" action="/lernen/entscheidungen" class="stack">'
                f'<input type="hidden" name="csrf" value="{e(self.site.auth.csrf_token(session.id))}">'
                f'<input type="hidden" name="version" value="{state.version}">'
                f'<input type="hidden" name="key" value="{e(key or secrets.token_hex(16))}">'
                f'<input type="hidden" name="action" value="{action}">{body}</form>')

    @staticmethod
    def action(proposal: Any, old: dict[str, Any] | None) -> str:
        if old is None:
            return "Neues Thema"
        return "Deaktivierung" if proposal.action == "disable" else "Änderung"

    @staticmethod
    def evidence(items: list[dict[str, Any]]) -> str:
        """Short entries (subject, decision, date); the excerpt opens on demand."""
        body = f'<details class="rule-evidence"><summary>Entscheidungsbelege ({len(items)})</summary><ul>'
        for item in items:
            date = item.get("recorded_at", "")[:10]
            changes = "".join(f"<dt>{e(key)}</dt><dd>{e(value)}</dd>" for key, value in item["changes"].items())
            body += (f'<li><strong>{e(item["subject"] or "Ohne Betreff")}</strong> · '
                     f'{e(SIGNALS.get(item["signal"], item["signal"]))}' + (f" · {e(date)}" if date else "")
                     + '<details><summary>Auszug anzeigen</summary>'
                     f'<p class="compare-text">{e(item["text"]) or "Kein Textauszug."}</p>'
                     + (f"<dl>{changes}</dl>" if changes else "")
                     + (f'<p>Antwort: {e(item["answer"])}</p>' if item.get("answer") else "")
                     + "</details></li>")
        return body + "</ul></details>"

    def review(self, session: WebSession, state: RuleState, values: dict[str, str]) -> str:
        known = {item["id"]: item for item in state.evidence}
        olds = [next((topic for topic in state.documents[proposal.category]["topics"]
                      if topic["id"] == proposal.topic_id), None) for proposal in state.proposals]
        kinds = [self.action(proposal, old) for proposal, old in zip(state.proposals, olds, strict=True)]
        counts = ", ".join(f"{kinds.count(kind)} {label}" for kind, label in (
            ("Änderung", "Änderungen"), ("Neues Thema", "neue Themen"), ("Deaktivierung", "Deaktivierungen"))
            if kinds.count(kind))
        body = (f'<section class="card rule-summary"><h2>Vorschläge prüfen</h2><p>{len(state.proposals)} Vorschläge'
                + (f": {counts}" if counts else "") + f' · aus {len(state.evidence)} Entscheidungen '
                f'({SCOPE_LABELS[state.scope]}'
                + (f"; {state.trimmed} ältere wegen der Nutzlastgrenze nicht übertragen" if state.trimmed else "")
                + (f"; {state.condensed} gleichartige Ablehnungen nur als Anzahl übertragen"
                   if state.condensed else "")
                + '); '
                f'{state.skipped} beschädigte, doppelte oder ungeeignete Zeilen übersprungen.</p><ol>'
                + "".join(f'<li><a href="#vorschlag-{index + 1}">{e(proposal.proposed.name)}</a> · {kind}</li>'
                          for index, (proposal, kind) in enumerate(zip(state.proposals, kinds, strict=True)))
                + '</ol></section>')
        for index, proposal in enumerate(state.proposals):
            old = olds[index]
            body += (f'<section class="card rule-review" id="vorschlag-{index + 1}"><div class="card-head">'
                     f'<h3>{e(proposal.proposed.name)}</h3><span class="badge accent">{kinds[index]}</span></div>'
                     + self.decision(index, values) +
                     f'<p>{e(proposal.rationale)}</p>'
                     + self.evidence([known[key] for key in proposal.evidence])
                     + '<div class="rule-diff"><section><h4>Bisherige Regel und Vorschlag</h4>'
                     + compare(old, proposal.proposed.model_dump(mode="json")) + '</section>'
                     '<section><h4>Vorgeschlagene Regel · bearbeiten</h4>')
            scope = proposal.proposed.mailboxes
            body += f'<p>Geltungsbereich: {e(scope if scope is not None else "alle Postfächer")}</p>'
            fields = proposal.proposed.model_dump(mode="json")
            body += (f'<input type="hidden" name="mailboxes-{index}" '
                     f'value="{e(json.dumps(fields["mailboxes"]))}">')
            for key in ("id", "name", "description", "examples", "exclusions", "enabled"):
                default = fields[key]
                text = ("\n".join(default) if isinstance(default, list)
                        else str(default).lower() if key == "enabled" else default)
                value = values.get(f"{key}-{index}", str(text))
                body += f'<label for="rule-{index}-{key}">{e(LABELS[key])}</label>'
                if key == "enabled":
                    body += (f'<select id="rule-{index}-{key}" name="{key}-{index}">'
                             f'<option value="true"{" selected" if value == "true" else ""}>Ja</option>'
                             f'<option value="false"{" selected" if value == "false" else ""}>Nein</option></select>')
                    continue
                body += (f'<textarea id="rule-{index}-{key}" name="{key}-{index}" rows="3">{e(value)}</textarea>'
                         if key in {"description", "examples", "exclusions"} else
                         f'<input id="rule-{index}-{key}" name="{key}-{index}" value="{e(value)}" required>')
            body += (f'<details><summary>Vollständiges Themen-YAML bearbeiten (optional)</summary>'
                     f'<label for="rule-{index}-yaml">YAML ersetzt die Feldwerte vollständig</label>'
                     f'<textarea id="rule-{index}-yaml" name="yaml-{index}" rows="8">'
                     f'{e(values.get(f"yaml-{index}", ""))}</textarea></details></section></div></section>')
        chosen = [self.chosen(index, values) for index in range(len(state.proposals))]
        body += ('<div class="confirm-bar"><p role="status" data-rule-count>'
                 f'{count_text(chosen.count("accept"), chosen.count("reject"))}</p>'
                 '<p>Im nächsten Schritt sehen Sie Ihre bearbeiteten Änderungen vor der Bestätigung.</p>'
                 '<button class="button" type="submit">Ausgewählte Änderungen prüfen</button></div>'
                 '<script src="/static/learning.js" defer></script>')
        return self.form(session, state, "preview", body)

    def preview(self, session: WebSession, form: dict[str, str]) -> Response:
        assert self.service is not None
        actor = "web:" + session.id
        draft, state = rule_preview.prepare(self.service, actor, int(form["version"]), self.choices(form), form,
                                            self.rejected(form))
        body = rule_preview.comparison(state, draft)
        body += self.form(session, state, "apply", (
            f'<input type="hidden" name="preview_key" value="{draft["key"]}">'
            '<label><input type="checkbox" name="confirm" value="yes" required> '
            + ('Ausgewählte Regeländerungen ausdrücklich bestätigen</label>'
               '<button class="button">Geprüfte Änderungen übernehmen</button>' if draft["choices"] else
               # 6.0.4: only rejections – no rule changes; the wording says what happens.
               'Verwerfen ausdrücklich bestätigen</label>'
               '<button class="button">Vorschläge verwerfen</button>')), key=draft["key"])
        body += '<p><a href="/lernen/entscheidungen">Weiter bearbeiten (anschließend erneut prüfen)</a></p>'
        return Response.html(200, layout("Änderungen prüfen", body, active="/lernen"))

    @staticmethod
    def chosen(index: int, values: dict[str, str]) -> str:
        """6.0.4: accept, reject or open (default); "selected-N=yes" of older forms means accept."""
        value = values.get(f"decision-{index}", "accept" if values.get(f"selected-{index}") == "yes" else "open")
        return value if value in DECISIONS else "open"

    def decision(self, index: int, values: dict[str, str]) -> str:
        current = self.chosen(index, values)
        body = ('<fieldset class="rule-decision"><legend>Entscheidung zu diesem Vorschlag</legend>')
        for value, label in DECISIONS.items():
            checked = " checked" if value == current else ""
            body += (f'<label><input type="radio" name="decision-{index}" value="{value}" data-rule-decision'
                     f'{checked}> {label}</label>')
        return body + "</fieldset>"

    @staticmethod
    def rejected(form: dict[str, str]) -> list[int]:
        return sorted(int(key.removeprefix("decision-")) for key, value in form.items()
                      if key.startswith("decision-") and value == "reject")

    @staticmethod
    def choices(form: dict[str, str]) -> list[dict[str, Any]]:
        selected = []
        indexes = sorted({int(key.split("-", 1)[1]) for key, value in form.items()
                          if (key.startswith("selected-") and value == "yes")
                          or (key.startswith("decision-") and value == "accept")})
        for index in indexes:
            if form.get(f"yaml-{index}", "").strip():
                topic = RuleTopic.model_validate(parse_yaml(form[f"yaml-{index}"]))
            else:
                values: dict[str, Any] = {key: form[f"{key}-{index}"] for key in ("id", "name", "description")}
                values["mailboxes"] = json.loads(form.get(f"mailboxes-{index}", "null"))
                values["enabled"] = {"true": True, "false": False}[form[f"enabled-{index}"]]
                for key in ("examples", "exclusions"):
                    text = form[f"{key}-{index}"]
                    values[key] = text.splitlines() if text else []
                topic = RuleTopic.model_validate(values)
            selected.append({"index": index, "topic": topic.model_dump(mode="json")})
        return selected

    def act(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        if self.service is None:
            return self.render(session, 503)
        try:
            actor = "web:" + session.id
            if form["action"] == "preview":
                return self.preview(session, form)
            payload: dict[str, Any] = {"confirm": form.get("confirm") == "yes"}
            if form["action"] == "analyze":
                payload["scope"] = form.get("scope", "new")
            if form["action"] == "apply":
                payload["choices"], payload["rejected"] = rule_preview.confirmed(self.service, actor, form)
            if form["action"] == "readmit":
                self.service.readmit(actor, int(form["rejected_version"]), form["key"], form["fingerprint"])
                return Response.redirect("/lernen/entscheidungen#verworfen")
            self.service.change(actor, int(form["version"]), form["key"], form["action"], payload)
        except PermissionError:
            return self.render(session, 403, "Sitzung nicht mehr gültig.", form)
        except RuleConflict as error:
            return self.render(session, 409, str(error), form)
        except (ValueError, KeyError, TypeError) as error:
            return self.render(session, 422, f"Regeln nicht gespeichert: {error}", form)
        except (OSError, CorruptState):
            return self.render(session, 503, "Schreiben unterbrochen; Übernahme nach Prüfung abschließen.", form)
        return Response.redirect("/lernen/entscheidungen")
