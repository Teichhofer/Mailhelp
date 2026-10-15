"""Credential forms contain only presence metadata and empty password inputs."""
from __future__ import annotations

from itertools import groupby

from ..credentials import CredentialSnapshot
from .forms import post_form
from .pages import e, notice


def credentials_section(snapshot: CredentialSnapshot | None, csrf: str) -> str:
    body = ('<section class="settings-section" id="settings-credentials" aria-labelledby="credentials-title">'
            '<h2 id="credentials-title">Zugangsdaten</h2>'
            '<p>Passwörter und API-Schlüssel verwalten. Bestehende Werte bleiben verborgen. '
            'Ein neuer Wert ersetzt nur den gewählten Zugang in <code>.env</code> und wirkt nach einem Neustart.</p>')
    if snapshot is None:
        return body + notice("Die Zugangsdatenverwaltung ist derzeit nicht verfügbar.", "warn") + '</section>'
    body += ('<p class="meta">Prozessvariablen haben weiterhin Vorrang vor <code>.env</code>. '
             'Gespeicherte Microsoft-Anmeldungen werden mit <code>mailhelp --microsoft-login</code> erneuert; '
             'die Google-Anmeldung mit <code>mailhelp --google-auth</code>.</p>')
    for group, fields in groupby(snapshot.fields, key=lambda item: item.group):
        body += '<section class="credential-group"><h3>' + e(group) + '</h3>'
        for item in fields:
            status = "vorhanden" if item.present else "fehlt"
            body += ('<details class="setting credential-setting"><summary><span>' + e(item.label)
                     + '</span><strong>' + status + '</strong></summary>'
                     '<p class="meta"><code>' + e(item.name) + '</code></p>')
            if item.overridden:
                body += notice("Eine Prozessvariable überschreibt diesen Wert aus .env. "
                               "Für die Verwendung des neuen Werts auch die Prozessumgebung anpassen.", "warn")
            if item.inherited:
                body += '<p class="meta">Der Zugang wird bisher aus den globalen Zugangsdaten geerbt.</p>'
            identity = "credential-" + item.name
            control = (f'<label for="{e(identity)}">Neuer Wert für {e(item.label)}</label>'
                       f'<input id="{e(identity)}" type="password" name="value" autocomplete="new-password" '
                       'maxlength="4000" required>')
            body += post_form("/einstellungen/zugangsdaten/speichern", csrf, control, "Zugang speichern",
                              name=item.name, expected=snapshot.revision, config_revision=snapshot.config_revision)
            body += '</details>'
        body += '</section>'
    return body + ('<p class="card-links"><a class="button" href="/einstellungen/zugangsdaten">'
                   'Alle Zugangsdaten und neue Konten</a> '
                   '<a class="button" href="/einrichtung">Verbindungen einrichten</a> '
                   '<a class="button" href="/diagnose">Zugriffe prüfen</a></p></section>')
