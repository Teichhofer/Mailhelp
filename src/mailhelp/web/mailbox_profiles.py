"""Target profiles on the mailbox settings: list, save and retarget (7.0, R5)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..config import TargetProfileSettings
from ..domain.proposal import Proposal
from ..i18n import msg, tr
from ..proposals.profile_binding import choices
from ..proposals.profile_usage import profile_references
from ..review.commands import CommandKind, CommandSource, ReviewCommand
from . import mailbox_site as mailbox_site_module
from .auth import WebSession
from .forms import post_form
from .http import Request, Response
from .initial_pages import hosted_google_box, hosted_target_boxes
from .pages import e

_PROFILES_TEXT_1 = msg(
    '<p><a href="/einstellungen/postfaecher">Postfächer</a> · <a '
    'href="/diagnose">Diagnose je Profil</a> · <a href="/einrichtung">Standardprofil 1 '
    'bearbeiten</a></p><p><a href="/hilfe/google-playground">Google: '
    'OAuth-Playground-Anleitung</a> · <a href="/auth/google/start?profile=1">Google für '
    'Profil 1 verbinden</a> · <a href="/auth/microsoft?profile=1">Microsoft für Profil 1 '
    'verbinden</a> · <a href="/auth/google/kalender?profile=1">Google-Kalender für Profil '
    '1 auswählen</a> · <a href="/auth/google/aufgabenlisten?profile=1">Google-Tasks-Liste '
    'für Profil 1 auswählen</a> · <a href="/auth/notion/start?profile=1">Notion für '
    'Profil 1 verbinden</a> · <a href="/notion/datenquelle?profile=1">Notion-Datenquelle '
    "für Profil 1 auswählen</a> · <a "
    'href="/notion/zuordnung?profile=1">Notion-Eigenschaften für Profil 1 zuordnen</a></p>'
)

_PROFILES_TEXT_2 = msg(
    '<p><a href="/auth/google/start?profile={p0}">Google verbinden</a> · <a '
    'href="/auth/microsoft?profile={p1}">Microsoft verbinden</a> · <a '
    'href="/auth/google/kalender?profile={p2}">Google-Kalender auswählen</a> · <a '
    'href="/auth/google/aufgabenlisten?profile={p3}">Google-Tasks-Liste auswählen</a> · '
    '<a href="/auth/notion/start?profile={p4}">Notion verbinden</a> · <a '
    'href="/notion/datenquelle?profile={p5}">Notion-Datenquelle auswählen</a> · <a '
    'href="/notion/zuordnung?profile={p6}">Notion-Eigenschaften zuordnen</a></p>'
)

if TYPE_CHECKING:
    from .mailbox_site import MailboxSite


def profiles(site: MailboxSite, request: Request, session: WebSession) -> Response:
    if site.runtime is None:
        return site.unavailable()
    cfg = site.runtime.setup.draft_settings()
    body = tr(_PROFILES_TEXT_1)
    hosted = cfg.hosted_auth.enabled
    if hosted:
        # 8.0 / 8.2: hosted instances connect Google, Microsoft and Notion through Inboxstride.
        body += hosted_google_box(cfg.targets.model_dump()) + hosted_target_boxes(cfg.targets.model_dump())
    for profile in cfg.target_profiles:
        references = profile_references(site.site.views.store, cfg, profile.id)
        body += '<section class="card"><h2>' + e(profile.label) + f" · {profile.id}</h2>"
        body += tr(
            (_PROFILES_TEXT_2),
            p0=profile.id,
            p1=profile.id,
            p2=profile.id,
            p3=profile.id,
            p4=profile.id,
            p5=profile.id,
            p6=profile.id,
        )
        if hosted:
            body += (hosted_google_box(profile.model_dump(), profile.id)
                     + hosted_target_boxes(profile.model_dump(), profile.id))
        for field, value in profile.model_dump().items():
            if field == "id":
                continue
            body += post_form(
                "/einstellungen/zielprofile/speichern",
                site.site.auth.csrf_token(session.id),
                mailbox_site_module.control(field, value, prefix=f"profile-{profile.id}"),
                "Profiländerung vormerken",
                number=profile.id,
                field=field,
                version=site.runtime.setup.state().version,
            )
        body += tr("<p>Verwendet von: ") + e(references) + "</p>"
        if not references:
            body += post_form(
                "/einstellungen/zielprofile/speichern",
                site.site.auth.csrf_token(session.id),
                "",
                msg("Profil entfernen"),
                number=profile.id,
                action="remove",
                version=site.runtime.setup.state().version,
            )
        body += "</section>"
    body += tr('<section class="card"><h2>Zielprofil hinzufügen</h2>')
    fields = "".join(
        mailbox_site_module.control(name, value, prefix="new-profile").replace('name="value"', f'name="{name}"')
        for name, value in (
            ("id", ""),
            ("label", ""),
            ("calendar_provider", "google"),
            ("google_calendar", "primary"),
            ("task_provider", "todoist"),
            ("todoist_project", ""),
        )
    )
    body += post_form(
        "/einstellungen/zielprofile/speichern",
        site.site.auth.csrf_token(session.id),
        fields,
        msg("Neues Profil vormerken"),
        action="add",
        version=site.runtime.setup.state().version,
    )
    return site.page(msg("Zielprofile"), body + "</section>" + site.preview(session))


def save_profile(site: MailboxSite, request: Request, session: WebSession, form: dict[str, str]) -> Response:
    if site.runtime is None:
        return site.unavailable()
    try:
        cfg = site.runtime.setup.draft_settings()
        profiles = [profile.model_dump() for profile in cfg.target_profiles]
        if form.get("action") == "add":
            profile: dict[str, Any] = {
                name: form[name]
                for name in ("label", "calendar_provider", "google_calendar", "task_provider", "todoist_project")
            }
            profile["id"] = int(form["id"])
            profiles.append(TargetProfileSettings.model_validate(profile).model_dump())
        elif form.get("action") == "remove":
            profiles = [value for value in profiles if value["id"] != int(form["number"])]
        else:
            value = next(profile for profile in profiles if profile["id"] == int(form["number"]))
            if form["field"] not in TargetProfileSettings.model_fields or form["field"] == "id":
                raise ValueError("Profilnummern bleiben stabil")
            value[form["field"]] = form["value"]
        site.runtime.setup.save(
            f"web:{session.id}",
            int(form["version"]),
            form["key"],
            6,
            {"target_profiles": profiles},
            request_signature={name: value for name, value in form.items() if name not in {"csrf", "key"}},
        )
    except (ValueError, KeyError, StopIteration, PermissionError):
        return Response.text(409, msg("Profilentwurf nicht gespeichert; Verweise, Angaben und Version prüfen."))
    return Response.redirect("/einstellungen/zielprofile")


def target_forms(site: MailboxSite, proposal: Proposal, session: WebSession) -> str:
    if site.runtime is None:
        return ""
    cfg = site.runtime.app.settings
    body = ""
    for number, name, digest in choices(cfg, proposal):
        body += post_form(
            "/einstellungen/zielprofile/umstellen",
            site.site.auth.csrf_token(session.id),
            "",
            tr("Auf Zielprofil {p0} umstellen", p0=f"{name}"),
            mail_id=proposal.source_mail_id,
            proposal_id=proposal.id,
            version=proposal.version,
            number=number,
            digest=digest,
        )
    return body


def retarget(site: MailboxSite, request: Request, session: WebSession, form: dict[str, str]) -> Response:
    try:
        command = ReviewCommand(
            kind=CommandKind.RETARGET,
            source=CommandSource.WEB,
            actor=f"web:{session.id}",
            mail_id=form["mail_id"],
            proposal_id=form["proposal_id"],
            version=int(form["version"]),
            idempotency_key=form["key"],
            target_profile=int(form["number"]),
            proposal_hash=form["digest"],
        )
    except (ValueError, KeyError):
        return Response.text(422, msg("Ungültige Zielwahl."))
    return site.site.archive.queue(request, command)
