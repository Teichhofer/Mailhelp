"""Credential forms contain only presence metadata and empty password inputs."""

from __future__ import annotations

from itertools import groupby

from ..i18n import msg, tr
from ..runtime.credentials import CredentialSnapshot
from .forms import post_form
from .pages import e, notice

_CREDENTIALS_SECTION_TEXT_1 = msg(
    '<section class="settings-section" id="settings-credentials" '
    'aria-labelledby="credentials-title"><h2 '
    'id="credentials-title">Zugangsdaten</h2><p>Passwörter und API-Schlüssel verwalten. '
    "Bestehende Werte bleiben verborgen. Ein neuer Wert ersetzt nur den gewählten Zugang "
    "in <code>.env</code> und wirkt nach einem Neustart.</p>"
)

_CREDENTIALS_SECTION_TEXT_2 = msg(
    '<p class="meta">Prozessvariablen haben weiterhin Vorrang vor <code>.env</code>. '
    "Gespeicherte Microsoft-Anmeldungen werden mit <code>mailhelp "
    "--microsoft-login</code> erneuert; die Google-Anmeldung mit <code>mailhelp "
    "--google-auth</code>.</p>"
)

_CREDENTIALS_SECTION_TEXT_3 = msg(
    '<p class="card-links"><a class="button" href="/einstellungen/zugangsdaten">Alle '
    'Zugangsdaten und neue Konten</a> <a class="button" href="/einrichtung">Verbindungen '
    'einrichten</a> <a class="button" href="/diagnose">Zugriffe prüfen</a></p></section>'
)

_CREDENTIALS_SECTION_TEXT_4 = msg(
    '<label for="{p0}">Neuer Wert für {p1}</label><input id="{p2}" type="password" '
    'name="value" autocomplete="new-password" maxlength="4000" required>'
)


def credentials_section(snapshot: CredentialSnapshot | None, csrf: str) -> str:
    body = tr(_CREDENTIALS_SECTION_TEXT_1)
    if snapshot is None:
        return body + notice(tr("Die Zugangsdatenverwaltung ist derzeit nicht verfügbar."), "warn") + "</section>"
    body += tr(_CREDENTIALS_SECTION_TEXT_2)
    for group, fields in groupby(snapshot.fields, key=lambda item: item.group):
        body += '<section class="credential-group"><h3>' + e(group) + '</h3>'
        for item in fields:
            status = msg("vorhanden") if item.present else msg("fehlt")
            body += ('<details class="setting credential-setting"><summary><span>' + e(item.label)
                     + '</span><strong>' + status + '</strong></summary>'
                     '<p class="meta"><code>' + e(item.name) + '</code></p>')
            if item.overridden:
                body += notice(
                    tr(
                        "Eine Prozessvariable überschreibt diesen Wert aus .env. Für die "
                        "Verwendung des neuen Werts auch die Prozessumgebung anpassen."
                    ),
                    "warn",
                )
            if item.inherited:
                body += tr('<p class="meta">Der Zugang wird bisher aus den globalen Zugangsdaten geerbt.</p>')
            identity = "credential-" + item.name
            control = tr(
                (_CREDENTIALS_SECTION_TEXT_4),
                p0=e(identity),
                p1=e(item.label),
                p2=e(identity),
            )
            body += post_form(
                "/einstellungen/zugangsdaten/speichern",
                csrf,
                control,
                msg("Zugang speichern"),
                name=item.name,
                expected=snapshot.revision,
                config_revision=snapshot.config_revision,
            )
            body += '</details>'
        body += '</section>'
    return body + (tr(_CREDENTIALS_SECTION_TEXT_3))
