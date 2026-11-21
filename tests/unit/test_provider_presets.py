"""Offline provider selection never sends account data to a discovery service."""
import pytest

from mailhelp.i18n import Locale, use_locale
from mailhelp.mailbox.provider_presets import apply_provider, detect_provider, providers
from mailhelp.web.provider_fields import provider_fields


@pytest.mark.parametrize("address,expected", [
    ("NAME@WEB.DE", "webde"), ("a@gmx.net", "gmx"), ("a@t-online.de", "telekom"),
    ("a@gmail.com", "gmail"), ("a@outlook.de", "outlook"), ("a@icloud.com", "icloud"),
    ("a@web.de.attacker.test", "manual"), ("no-address", "manual"), ("a@own.test", "manual"),
])
def test_detection_is_an_exact_domain_match(address, expected):
    assert detect_provider(address) == expected


def test_explicit_defaults_and_manual_override_do_not_mutate_input():
    before = {"provider": "auto", "provider_email": "a@web.de", "imap.host": "old.test"}
    result = apply_provider(before, initial=True)
    assert result["imap.host"] == "imap.web.de" and result["imap.port"] == "993"
    assert result["imap.connection_mode"] == "ssl" and result["IMAP_USERNAME"] == "a@web.de"
    assert before["imap.host"] == "old.test"
    assert apply_provider({"provider": "manual", "host": "custom.test"})["host"] == "custom.test"
    assert apply_provider({"provider": "strato", "provider_email": "a@own.test"})["host"] == "imap.strato.de"
    with pytest.raises(KeyError):
        apply_provider({"provider": "attacker"})


def test_catalogue_and_bilingual_help_escape_values():
    assert len(providers()) == 8
    for locale in (Locale.DE, Locale.EN):
        with use_locale(locale):
            html = provider_fields({"provider": "telekom", "provider_email": '<bad>"'}, "/preview")
            assert 'name="provider_apply"' in html and "secureimap" not in html
            assert "&lt;bad&gt;" in html and "<bad>" not in html
            assert ("separate password" if locale == Locale.EN else "separate Passwort") in html
    assert "role=\"status\"" not in provider_fields({}, "/preview")


def test_new_authentication_fields_do_not_change_legacy_fingerprints(tmp_path):
    from mailhelp.llm.fingerprints import _imap_before_3_1
    from tests.fakes.shared_application import settings
    assert not {"auth_method", "oauth_connection"} & set(_imap_before_3_1(settings(tmp_path)))


def test_existing_mailbox_controls_keep_the_exact_binding():
    from mailhelp.config import MailboxSettings
    from mailhelp.web.provider_fields import mailbox_oauth_controls
    box = MailboxSettings(id=2, host="imap.gmail.com", port=993, folders=["INBOX"])
    assert 'mailbox=2' in mailbox_oauth_controls(box, "csrf", 3, "revision")
    connected = box.model_copy(update={"auth_method": "gmail", "oauth_connection": "a" * 32})
    html = mailbox_oauth_controls(connected, "csrf", 3, "revision")
    assert '/postfach/oauth/trennen' in html and 'name="version" value="3"' in html


def test_presets_include_verified_connection_and_username_rules():
    from datetime import date

    for preset in providers().values():
        assert preset.port == 993 and preset.connection_mode == "ssl"
        assert preset.checked_on == date(2026, 11, 20)
    for initial in (False, True):
        result = apply_provider({"provider": "icloud", "provider_email": "apple@icloud.com"}, initial=initial)
        assert result["IMAP_USERNAME" if initial else "username"] == "apple"
    assert apply_provider({"provider": "webde", "provider_email": "name@web.de"})["username"] == "name@web.de"


def test_malformed_address_does_not_suggest_a_provider():
    assert detect_provider("name@other.test@web.de") == "manual"
    assert detect_provider("@web.de") == "manual"
