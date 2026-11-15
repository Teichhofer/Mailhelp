"""Own-device diagnosis and explicit, versioned profile changes for Web Push."""
from __future__ import annotations

import re
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

from ..config import Settings, read_yaml
from ..config.configuration import AdminCommand, AdminKind, ConfigurationConflict, file_hash
from ..config.notifications import effective_profile
from ..mailbox.mailbox_settings import effective_settings
from ..runtime.setup import profile_patch
from .actions import new_key
from .auth import WebSession
from .http import Request, Response
from .pages import e, layout

if TYPE_CHECKING:
    from .experience import ExperienceSite
    from .site import MailhelpSite

SERVER_OFF = 'Web-Push ist am Server ausgeschaltet. Unter Einrichtung einschalten und Mailhelp neu starten.'
STAGES = ('Server bietet Push an', 'Sichere Verbindung', 'Browser kann Push', 'Berechtigung',
          'Hintergrunddienst aktiv', 'Abonnement passt zum Server', 'Am Server gespeichert',
          'Neue Vorschläge werden per Push gemeldet', 'Letzte Zustellung')


class PushSite:
    def __init__(self, feature: ExperienceSite) -> None:
        self.feature = feature
        self.site: MailhelpSite = feature.site
        for method, path, handler in (
            ('GET', '/api/push/status', self.status), ('POST', '/api/push/test', self.test),
            ('GET', '/push/kanaele', self.channels), ('POST', '/push/kanaele', self.apply_channels)):
            self.site.app.route(method, path, self.site.signed_in(handler))

    def snapshot(self, actor: str | None) -> dict[str, Any]:
        push = self.feature.push
        configuration = self.site.archive.configuration
        profiles = []
        if configuration is not None:
            settings = configuration.active
            for box in settings.imap.enabled_mailboxes():
                profile = effective_profile(effective_settings(settings, box.id))
                profiles.append({'mailbox': box.id, 'label': box.label,
                                 'decisions': 'web_push' in profile.categories.decisions,
                                 'daily_briefing': 'web_push' in profile.categories.daily_briefing})
        overview = self.site.views.overview()
        runtime = getattr(self.site.setup_page, 'runtime', None)
        return {'offered': push is not None, 'public_key': push.public_key if push else None,
                'key_changed': push.key_changed if push else False,
                'key_fingerprint': push.fingerprint if push else None,
                'subject_example': bool(push and push.subject == 'mailto:admin@example.invalid'),
                'device': push.status(actor or '') if push else {'registered': False, 'last_code': 'disabled'},
                'profiles': profiles, 'waiting': len(overview.open) + len(overview.relevance),
                'diagnostic_version': runtime.diagnostics.state().version if runtime else 0,
                'test_available': runtime is not None}

    def status(self, request: Request, session: WebSession) -> Response:
        return Response.json(200, self.snapshot(session.id))

    def warnings(self) -> tuple[str, ...]:
        push = self.feature.push
        if push is None:
            return ()
        return tuple(text for condition, text in (
            (push.subject == 'mailto:admin@example.invalid',
             'Web-Push: VAPID-Absender ist ein Beispielwert. Kontaktadresse unter Einrichtung eintragen.'),
            (push.key_changed, 'Web-Push: Serverschlüssel wurde geändert. Geräte müssen neu aktiviert werden.'))
            if condition)

    def controls(self, csrf: str, actor: str | None) -> str:
        state = self.snapshot(actor)
        device = state['device']
        channels = all(p['decisions'] for p in state['profiles'])
        rows = []
        for number, title in enumerate(STAGES, 1):
            value = 'noch nicht geprüft'
            if number == 1:
                value = '✓' if state['offered'] else '✗'
            if number == 7:
                value = '✓' if device['registered'] else '✗'
            if number == 8:
                value = '✓' if channels else '✗'
            if number == 9:
                value = {'accepted': 'Zuletzt an den Anbieter übergeben',
                         'provider_rejected': 'Vom Anbieter abgelehnt – neu aktivieren.',
                         'expired': 'Abonnement abgelaufen – neu aktivieren.'}.get(
                             device['last_code'], 'noch nicht geprüft')
            rows.append(f'<li data-push-stage="{number}">{title}: <span>{e(value)}</span></li>')
        actions = ''
        if state['offered']:
            actions = ('<button type="button" class="button primary" id="push-enable">Push aktivieren</button>'
                       '<button type="button" class="button" id="push-disable">Push deaktivieren</button>'
                       '<button type="button" class="button" id="push-test" disabled>'
                       'Test-Push an dieses Gerät senden</button>')
        message = ('Push-Zustand wird geprüft.' if state['offered'] else SERVER_OFF)
        links = '<a class="button" href="/einrichtung">Einrichtung öffnen</a>'
        if state['offered'] and device['registered'] and not channels:
            message = 'Neue Vorschläge werden nicht per Push gemeldet.'
            links += ' <a class="button" href="/push/kanaele">Web-Push für neue Vorschläge einschalten</a>'
        for profile in state['profiles']:
            if not profile['decisions']:
                links += (f'<p>{e(profile["label"])}: Neue Vorschläge werden nicht per Push gemeldet. '
                          f'<a href="/push/kanaele?postfach={profile["mailbox"]}">Web-Push einschalten</a></p>')
        warning = ('<p class="notice warn">VAPID-Absender ist ein Beispielwert. '
                   'Eine gültige Kontaktadresse unter Einrichtung eintragen.</p>' if state['subject_example'] else '')
        return ('<section class="card"><h2>Benachrichtigungen</h2>'
                f'<div id="push-controls" data-csrf="{e(csrf)}" data-offered="{str(state["offered"]).lower()}">'
                f'<ol>{"".join(rows)}</ol><div class="actions">{actions}</div>'
                f'<p id="push-status" role="status">{e(message)}</p>{links}{warning}'
                f'<p>{state["waiting"]} Vorschläge warten schon. <a href="/offen">Offen lesen</a></p>'
                '<noscript>Push aktivieren benötigt JavaScript. Die Serverstufen stehen oben.</noscript>'
                '</div><p><a href="/briefing">Tagesüberblick lesen</a></p></section>')

    def _channel_command(self, session: WebSession, fields: dict[str, str]) -> tuple[AdminCommand, dict[str, Any]]:
        configuration = self.site.archive.configuration
        if configuration is None:
            raise ValueError('Konfiguration nicht verfügbar')
        path = configuration.directory / 'config.yaml'
        settings = Settings.model_validate(read_yaml(path))
        number = int(fields.get('postfach', '0'))
        effective = effective_settings(settings, number) if number else settings
        profile = effective_profile(effective).model_copy(deep=True)
        before = profile.categories.model_dump()
        for category in ('decisions', 'daily_briefing'):
            channels = getattr(profile.categories, category)
            if 'web_push' not in channels:
                channels.append('web_push')
        if number and settings.imap.mailboxes:
            boxes = settings.imap.configured_mailboxes()
            index = next(i for i, box in enumerate(boxes) if box.id == number)
            values = [box.model_dump(mode='json') for box in boxes]
            override = boxes[index].notifications
            notifications = override.model_dump(mode='json', exclude_none=True) if override else {}
            categories = notifications.setdefault('categories', {})
            for category in ('decisions', 'daily_briefing'):
                categories[category] = getattr(profile.categories, category)
            values[index]['notifications'] = notifications
            patch = {'imap.mailboxes': values}
        else:
            patched = settings.model_copy(update={'notifications': profile})
            patch = profile_patch(patched)
        command = AdminCommand(kind=AdminKind.SETUP, actor='web:' + session.id,
                               idempotency_key=fields.get('key') or new_key(), patch=patch,
                               expected_hash=fields.get('expected_hash') or file_hash(path), acknowledged=True)
        configuration.candidate(command)
        return command, before

    def channels(self, request: Request, session: WebSession) -> Response:
        fields = {name: values[0] for name, values in parse_qs(request.query).items()}
        try:
            command, before = self._channel_command(session, fields)
        except (ValueError, StopIteration, LookupError, OSError):
            return Response.text(422, 'Profil nicht verfügbar; Einstellungen prüfen.')
        hidden = {'csrf': self.site.auth.csrf_token(session.id), 'key': command.idempotency_key,
                  'expected_hash': command.expected_hash, 'postfach': fields.get('postfach', '0'), 'confirm': 'yes'}
        details = ''.join(f'<li>{e(category)}: bisher {e(before[category])}; '
                          f'neu {e(list(dict.fromkeys(before[category] + ["web_push"])))}</li>'
                          for category in ('decisions', 'daily_briefing'))
        inputs = ''.join(f'<input type="hidden" name="{name}" value="{e(value)}">'
                         for name, value in hidden.items())
        return Response.html(200, layout('Web-Push bestätigen', '<h1>Web-Push für neue Vorschläge einschalten</h1>'
            '<p>Entscheidungen und Tagesüberblick zusätzlich per Web-Push melden. '
            'Bisherige Kanäle bleiben erhalten.</p>'
            f'<ul>{details}</ul><form method="post" action="/push/kanaele">{inputs}'
            '<button type="submit" class="button primary">Änderung bestätigen</button></form>'
            '<a href="/einstellungen?bereich=benachrichtigungen">Abbrechen</a>'))

    def apply_channels(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        try:
            if form.get('confirm') != 'yes' or not form.get('key') or not form.get('expected_hash'):
                raise ValueError('Bestätigung fehlt')
            command, _ = self._channel_command(session, form)
        except ConfigurationConflict:
            return Response.text(409, 'Einstellungen geändert; Vorschau erneut öffnen.')
        except (ValueError, StopIteration, LookupError, OSError):
            return Response.text(422, 'Änderung nicht bestätigt oder Profil nicht verfügbar.')
        return self.site.archive.queue(request, command)

    def test(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        runtime = getattr(self.site.setup_page, 'runtime', None)
        if runtime is None or self.feature.push is None:
            return Response.json(503, {'code': 'push_disabled'})
        try:
            version = int(form['version'])
            key = form['key']
            if not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', key):
                raise ValueError('invalid key')
        except (KeyError, ValueError):
            return Response.json(400, {'code': 'invalid_request'})
        device = self.feature.push.status(session.id)
        if not device['registered']:
            return Response.json(409, {'code': 'device_not_registered'})
        if device['rejected']:
            return Response.json(409, {'code': 'provider_rejected'})
        if not device['key_matches']:
            return Response.json(409, {'code': 'key_conflict'})
        now = self.site.clock()
        with self.site.views.store.locked():
            state = self.site.views.store.load('push-test-limits', {})
            own = state.get(session.id, {})
            recent = {key: stamp for key, stamp in own.items()
                      if stamp > (now - timedelta(minutes=1)).isoformat()}
            if key not in recent and len(recent) >= 3:
                return Response.json(429, {'code': 'rate_limited'})
            recent[key] = now.isoformat()
            state[session.id] = recent
            self.site.views.store.save('push-test-limits', state)
        try:
            runtime.diagnostics.run(session.id, 'push_test', version, key)
        except (ValueError, KeyError, PermissionError):
            return Response.json(409, {'code': 'test_stale'})
        result = runtime.diagnostics.state().results['push_test']
        code = 'accepted'
        if result.status != 'ready':
            code = self.feature.push.status(session.id)['last_code']
            if result.code == 'timeout':
                code = 'test_timeout'
            elif code in {'accepted', 'not_tested'}:
                code = 'test_failed'
        return Response.json(200, {'code': code,
                                   'diagnostic_version': runtime.diagnostics.state().version})
