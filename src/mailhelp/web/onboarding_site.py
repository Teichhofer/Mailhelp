"""8.2: accessible 3-step self-service onboarding (/onboarding)."""
from __future__ import annotations

from typing import Any

from ..i18n import msg, stored, tr
from ..mailbox.provider_presets import detect_provider, providers
from ..runtime.onboarding import STARTER_PRESETS, OnboardingService, OnboardingState
from .auth import WebSession
from .forms import field, post_form
from .http import Request, Response
from .pages import e, error_page, layout


def _step_mailbox_box(state: OnboardingState, csrf: str, email: str = "") -> str:
    status = (tr('<p role="status">✓ Postfach geprüft: {summary}</p>', summary=e(stored(state.mailbox_summary)))
              if state.mailbox_checked else "")
    detected = detect_provider(email) if email else "manual"
    hint = ""
    if detected != "manual":
        preset = providers()[detected]
        hint = tr("<p>Erkannter Anbieter: <strong>{label}</strong> ({host}:{port}).</p>",
                  label=e(preset.label), host=e(preset.host), port=preset.port)
    oauth_links = (
        '<p><a class="button" href="/postfach/oauth?provider=gmail&amp;mailbox=1">'
        f'{e(tr("Gmail per OAuth verbinden"))}</a> · '
        '<a class="button" href="/postfach/oauth?provider=microsoft&amp;mailbox=1">'
        f'{e(tr("Microsoft-Postfach per OAuth verbinden"))}</a></p>'
    )
    controls = field("email", msg("E-Mail-Adresse des Postfachs"), email)
    return (
        '<section class="card"><h2>' + e(tr("Schritt 1: Postfach verbinden")) + "</h2>"
        + status + hint + oauth_links
        + post_form("/onboarding/postfach", csrf, controls, msg("Postfach prüfen und weiter"),
                    primary=not state.mailbox_checked, version=state.version)
        + "</section>"
    )


def _step_target_box(state: OnboardingState, csrf: str) -> str:
    status = (tr('<p role="status">✓ Zielsystem geprüft: {summary}</p>', summary=e(stored(state.target_summary)))
              if state.target_checked else "")
    tiles = (
        '<p><a class="button" href="/google/verbinden?profile=1">'
        f'{e(tr("Mit Google verbinden"))}</a> · '
        '<a class="button" href="/microsoft/verbinden?profile=1">'
        f'{e(tr("Mit Microsoft verbinden"))}</a> · '
        '<a class="button" href="/notion/verbinden?profile=1">'
        f'{e(tr("Mit Notion verbinden"))}</a></p>'
    )
    return (
        '<section class="card"><h2>' + e(tr("Schritt 2: Zielsystem verbinden")) + "</h2>"
        + status + tiles
        + post_form("/onboarding/ziel", csrf, "", msg("Zielsystem prüfen und weiter"),
                    primary=state.mailbox_checked and not state.target_checked, version=state.version)
        + "</section>"
    )


def _step_topics_box(state: OnboardingState, csrf: str) -> str:
    boxes = "".join(
        f'<label><input type="checkbox" name="preset_{e(key)}" value="1"'
        f'{" checked" if key in state.selected_presets else ""}> {e(tr(label))}</label>'
        for key, (label, _topic) in STARTER_PRESETS.items()
    )
    dryrun_form = post_form(
        "/onboarding/probelauf", csrf, f"<fieldset><legend>{e(tr('Starter-Themenprofile'))}</legend>{boxes}</fieldset>",
        msg("5 aktuelle Mails probeweise im Testmodus auswerten"),
        primary=state.target_checked and not state.dryrun_results, version=state.version,
    )
    preview = ""
    if state.dryrun_results:
        items = "".join(
            f"<li><strong>{e(stored(item.title))}</strong> – {e(stored(item.detail))}</li>"
            for item in state.dryrun_results
        )
        preview = (
            '<div class="notice notice-info" role="status"><p>'
            + e(tr("Testmodus-Vorschau: Es wurden keine externen Termine oder Aufgaben angelegt."))
            + f"</p><ul>{items}</ul></div>"
        )
    confirm = (
        f'<label><input type="checkbox" name="confirm" value="yes" required> '
        f'{e(tr("Einrichtung übernehmen und produktiven Betrieb aktivieren"))}</label>'
    )
    activate_form = post_form(
        "/onboarding/aktivieren", csrf, confirm, msg("Produktiven Betrieb aktivieren"),
        primary=bool(state.dryrun_results), version=state.version,
    )
    return (
        '<section class="card"><h2>' + e(tr("Schritt 3: Themen wählen & Probelauf im Testmodus")) + "</h2>"
        + dryrun_form + preview + activate_form + "</section>"
    )


class OnboardingSite:
    def __init__(self, site: Any, service: OnboardingService, expert_path: str = "/einrichtung", *,
                 navigation: bool = True) -> None:
        self.site, self.service, self.expert_path, self.navigation = site, service, expert_path, navigation
        for method, path, handler in (("GET", "/onboarding", self.page),
                                      ("POST", "/onboarding/postfach", self.save_mailbox),
                                      ("POST", "/onboarding/ziel", self.save_target),
                                      ("POST", "/onboarding/probelauf", self.dryrun),
                                      ("POST", "/onboarding/aktivieren", self.activate),
                                      ("POST", "/onboarding/ueberspringen", self.skip)):
            site.app.route(method, path, site.signed_in(handler))

    def _render(self, state: OnboardingState, csrf: str, *, email: str = "", status: int = 200) -> Response:
        header = (
            f"<h1>{e(tr('Mailhelp einrichten (3 Schritte)'))}</h1>"
            + tr("<p>Geführte Ersteinrichtung ohne manuelle Server- oder Token-Dateien. "
                 'Jederzeit <a href="{expert}">zur Expertenansicht</a> wechselbar.</p>',
                 expert=e(self.expert_path))
        )
        skip_form = post_form("/onboarding/ueberspringen", csrf, "", msg("Onboarding überspringen"),
                              version=state.version)
        body = (header + _step_mailbox_box(state, csrf, email) + _step_target_box(state, csrf)
                + _step_topics_box(state, csrf) + skip_form)
        response = Response.html(status, layout(tr("Onboarding"), body, signed_in=self.navigation))
        response.headers["Cache-Control"] = "no-store"
        return response

    def _failed(self, text: str) -> Response:
        response = Response.html(409, error_page(tr("Onboarding-Schritt nicht möglich"), text,
                                                 signed_in=self.navigation))
        response.headers["Cache-Control"] = "no-store"
        return response

    def page(self, _request: Request, session: WebSession) -> Response:
        return self._render(self.service.state(), self.site.auth.csrf_token(session.id))

    def save_mailbox(self, _request: Request, session: WebSession, form: dict[str, str]) -> Response:
        try:
            state = self.service.record_mailbox(
                "web:" + session.id, int(form["version"]), form["key"], form)
        except PermissionError:
            return Response.text(403, msg("Sicherheitsprüfung fehlgeschlagen."))
        except (KeyError, ValueError):
            return self._failed(tr("Postfachprüfung fehlgeschlagen oder Einrichtungsstand veraltet."))
        return self._render(state, self.site.auth.csrf_token(session.id), email=form.get("email", ""))

    def save_target(self, _request: Request, session: WebSession, form: dict[str, str]) -> Response:
        try:
            state = self.service.record_target(
                "web:" + session.id, int(form["version"]), form["key"], form)
        except PermissionError:
            return Response.text(403, msg("Sicherheitsprüfung fehlgeschlagen."))
        except (KeyError, ValueError):
            return self._failed(tr("Zielprüfung fehlgeschlagen. Zuerst Schritt 1 abschließen."))
        return self._render(state, self.site.auth.csrf_token(session.id))

    def dryrun(self, _request: Request, session: WebSession, form: dict[str, str]) -> Response:
        presets = [key for key in STARTER_PRESETS if form.get(f"preset_{key}") == "1"]
        try:
            state = self.service.run_dryrun(
                "web:" + session.id, int(form["version"]), form["key"], presets)
        except PermissionError:
            return Response.text(403, msg("Sicherheitsprüfung fehlgeschlagen."))
        except (KeyError, ValueError):
            return self._failed(tr("Probelauf nicht möglich. Bitte mindestens ein Themenprofil wählen."))
        return self._render(state, self.site.auth.csrf_token(session.id))

    def activate(self, _request: Request, session: WebSession, form: dict[str, str]) -> Response:
        try:
            self.service.activate(
                "web:" + session.id, int(form["version"]), form["key"], form.get("confirm", ""))
        except PermissionError:
            return Response.text(403, msg("Sicherheitsprüfung fehlgeschlagen."))
        except (KeyError, ValueError):
            return self._failed(tr("Aktivierung nicht möglich. Bitte Probelauf und Bestätigung prüfen."))
        return Response.redirect("/" if self.navigation else self.expert_path)

    def skip(self, _request: Request, session: WebSession, form: dict[str, str]) -> Response:
        try:
            self.service.skip("web:" + session.id, int(form["version"]), form["key"])
        except PermissionError:
            return Response.text(403, msg("Sicherheitsprüfung fehlgeschlagen."))
        except (KeyError, ValueError):
            return self._failed(tr("Onboarding-Stand wurde inzwischen geändert."))
        return Response.redirect(self.expert_path)


__all__ = ["OnboardingSite"]
