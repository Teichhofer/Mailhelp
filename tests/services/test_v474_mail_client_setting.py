"""4.7, step 18.5: the per-mailbox setting mail_client."""
import pytest
from pydantic import ValidationError

from mailhelp.config import Settings
from mailhelp.mailbox.imap import FetchedMail
from mailhelp.models import MailState
from mailhelp.storage import JsonStore
from mailhelp.web.mailbox_site import MAIL_CLIENTS, control
from tests.fakes.shared_profiles import ACCOUNT_ONE
from tests.fakes.shared_self_mail import orchestrator, own_settings


def configured(tmp_path, client):
    data = own_settings(tmp_path).model_dump(mode="json")
    if client is not None:
        data["imap"]["mailboxes"][0]["mail_client"] = client
    return Settings.model_validate(data)


def link(tmp_path, client):
    raw = (b"From: Verein <info@verein.example.test>\r\nSubject: Einladung\r\nMessage-ID: <a1@verein.example.test>\r\n"
           b"Date: Sat, 07 Nov 2026 10:00:00 +0000\r\n\r\nAm 5.12. um 9:30 Uhr.")
    with JsonStore(tmp_path / "data") as store:
        run = orchestrator(store, configured(tmp_path, client))
        state = MailState.model_validate(run.process(FetchedMail("INBOX", 1, 1, raw, account_id=ACCOUNT_ONE)).state)
    return state.proposals[0].mail_link


@pytest.mark.parametrize(("client", "prefix"), [
    (None, "message://"),                                   # default "auto" on a non-Gmail server
    ("gmail_web", "https://mail.google.com/"),
    ("outlook_web", "https://outlook.office.com/mail/search?q="),
    ("apple_mail", "message://"),
])
def test_the_configured_program_decides_the_link(tmp_path, client, prefix):
    assert link(tmp_path, client).startswith(prefix)


def test_none_switches_the_link_off(tmp_path):
    assert link(tmp_path, "none") is None


def test_the_setting_defaults_to_auto_and_accepts_only_known_programs(tmp_path):
    assert configured(tmp_path, None).imap.mailbox(1).mail_client == "auto"
    with pytest.raises(ValidationError):
        configured(tmp_path, "thunderbird")


def test_the_settings_page_offers_every_program_with_the_current_one_selected():
    html = control("mail_client", "gmail_web")
    assert all(f'value="{key}"' in html for key in MAIL_CLIENTS)
    assert '<option value="gmail_web" selected>' in html
    assert '<option value="auto" selected>' in control("mail_client", None)  # inherited default
