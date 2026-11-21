"""Provider selection shared by initial setup and mailbox management."""
from ..config import MailboxSettings
from ..i18n import current, msg, tr
from ..mailbox.provider_presets import providers
from .forms import field, post_form, select
from .pages import e


def provider_fields(values: dict[str, str], action: str, mailbox: int = 1) -> str:
    presets = providers()
    selected = values.get("provider", "auto")
    choices = [("auto", msg("Automatisch erkennen")), ("manual", msg("Anderer Anbieter / Manuell"))]
    choices += [(key, preset.label) for key, preset in presets.items()]
    body = field("provider_email", msg("E-Mail-Adresse des Postfachs"), values.get("provider_email", ""))
    body += select("provider", msg("Mailanbieter"), selected, choices)
    body += (f'<button type="submit" class="button" name="provider_apply" value="yes" formaction="{e(action)}" '
             f'formnovalidate>{e(tr("Anbietereinstellungen laden"))}</button>')
    if selected in presets:
        preset = presets[selected]
        hint = preset.en if current() == "en" else preset.de
        body += f'<p role="status">{e(hint)} <a href="{e(preset.help_url)}" rel="noreferrer">'
        body += e(tr("Anleitung des Anbieters")) + "</a></p>"
    return body + oauth_links(mailbox)


def oauth_links(mailbox: int) -> str:
    body = f'<p><a href="/postfach/oauth?provider=gmail&amp;mailbox={mailbox}">'
    body += e(tr("Google-Postfach verbinden")) + "</a> · "
    body += f'<a href="/postfach/oauth?provider=microsoft&amp;mailbox={mailbox}">'
    body += e(tr("Microsoft-Postfach verbinden")) + "</a></p>"
    return body


def mailbox_oauth_controls(mailbox: MailboxSettings, csrf: str, version: int, revision: str) -> str:
    body = oauth_links(mailbox.id)
    if mailbox.oauth_connection:
        body += post_form("/postfach/oauth/trennen", csrf, "", msg("Postfachverbindung trennen"),
                          mailbox=mailbox.id, version=version, revision=revision)
    return body
