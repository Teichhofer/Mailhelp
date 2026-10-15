"""Credential editing is authenticated, local, versioned and never echoes secrets."""
import os

import pytest
import yaml
from shared_setup import configured  # noqa: F401

from mailhelp.config import _dotenv
from mailhelp.credentials import RECEIPTS, CredentialEdits, CredentialUnauthorized
from mailhelp.storage import CorruptState

SAVE = "/einstellungen/zugangsdaten/speichern"


@pytest.fixture(autouse=True)
def clean_credentials_environment(monkeypatch):
    for name in tuple(os.environ):
        if name.startswith(("IMAP_", "GOOGLE_OAUTH_", "TODOIST_", "CALDAV_", "MICROSOFT_",
                            "OPENROUTER_", "TELEGRAM_BOT_")):
            monkeypatch.delenv(name)


def test_credentials_are_a_separate_settings_area_with_empty_password_fields(configured):
    web, directory = configured.web, configured.tmp_path
    path = directory / ".env"
    original = 'IMAP_PASSWORD="synthetic-old-password"\nOPENROUTER_API_KEY="synthetic-old-api-key"\n'
    path.write_text(original)
    for _ in range(2):
        response = web.browser.request("GET", "/einstellungen")
        page = response.body.decode()
        assert response.status == 200 and 'href="#settings-credentials">Zugangsdaten</a>' in page
        assert '<h2 id="credentials-title">Zugangsdaten</h2>' in page
        assert "synthetic-old-password" not in page and "synthetic-old-api-key" not in page
        assert 'type="password" name="value" autocomplete="new-password"' in page
    assert path.read_text() == original
    assert web.commands.queued() == [] and web.writer.created == 0


@pytest.mark.parametrize("redact", [False, True])
def test_saving_a_credential_and_retrying_do_not_queue_or_contact_external_services(configured, redact):
    web, directory = configured.web, configured.tmp_path
    original = (directory / "config.yaml").read_bytes()
    if redact:
        web.logger.secrets = ("previous",)
    form = web.form("/einstellungen", action=SAVE, name="IMAP_PASSWORD")
    value = "synthetic-new-password"
    for _ in range(2):
        response = web.browser.request("POST", SAVE, {**form, "value": value})
        assert response.status == 200 and "Zugangsdaten in .env gespeichert" in response.body.decode()
        assert value not in response.body.decode()
    assert _dotenv(directory / ".env")["IMAP_PASSWORD"] == value
    assert (directory / "config.yaml").read_bytes() == original
    assert web.store.load_model(RECEIPTS, CredentialEdits).entries[0].status == "done"
    assert value not in (web.store.directory / (RECEIPTS + ".json")).read_text()
    assert value not in repr(web.logger.events)
    if redact:
        assert web.logger.secrets.count(value) == 1
    assert web.commands.queued() == [] and web.writer.created == 0 and web.writer.reconciled == 0
    assert "Zugangsdaten" in web.browser.request("GET", "/einstellungen").body.decode()


def test_authentication_csrf_and_revoked_sessions_protect_credentials(configured):
    web = configured.web
    form = web.form("/einstellungen", action=SAVE, name="IMAP_PASSWORD")
    assert web.browser.request("POST", SAVE, {**form, "csrf": "wrong", "value": "synthetic"}).status == 403
    web.auth.revoke_all()
    assert web.browser.request("POST", SAVE, {**form, "value": "synthetic"}).status == 403
    assert web.browser.request("GET", "/einstellungen").status == 303
    assert not (configured.tmp_path / ".env").exists()


@pytest.mark.parametrize("change", [{"name": "PATH"}, {"name": "MAILHELP_WEB_SECRET"}, {"value": ""},
                                    {"value": "synthetic\nINJECTED=bad"}, {"key": "bad"}])
def test_invalid_requests_never_echo_or_save_the_submitted_value(configured, change):
    web = configured.web
    form = web.form("/einstellungen", action=SAVE, name="IMAP_PASSWORD")
    response = web.browser.request("POST", SAVE, {**form, "value": "synthetic-rejected", **change})
    assert response.status == 422
    assert "synthetic-rejected" not in response.body.decode() and "INJECTED" not in response.body.decode()
    assert not (configured.tmp_path / ".env").exists()


def test_missing_fields_and_concurrent_changes_are_reported_without_secret_values(configured):
    web = configured.web
    form = web.form("/einstellungen", action=SAVE, name="IMAP_PASSWORD")
    assert web.browser.request("POST", SAVE, form).status == 422
    (configured.tmp_path / ".env").write_text("IMAP_PASSWORD=synthetic-concurrent\n")
    response = web.browser.request("POST", SAVE, {**form, "value": "synthetic-new"})
    assert response.status == 409 and "synthetic-new" not in response.body.decode()
    assert _dotenv(configured.tmp_path / ".env")["IMAP_PASSWORD"] == "synthetic-concurrent"


def test_unavailable_configuration_and_invalid_env_have_safe_settings_fallbacks(configured):
    web = configured.web
    form = web.form("/einstellungen", action=SAVE, name="IMAP_PASSWORD")
    (configured.tmp_path / ".env").write_text("synthetic-invalid-no-equals\n")
    page = web.browser.request("GET", "/einstellungen").body.decode()
    assert "Zugangsdatenverwaltung ist derzeit nicht verfügbar" in page
    assert "synthetic-invalid" not in page
    web.site.archive.configuration = None
    assert web.browser.request("POST", SAVE, {**form, "value": "synthetic"}).status == 503
    assert "Zugangsdaten" in web.browser.request("GET", "/einstellungen").body.decode()


@pytest.mark.parametrize("error,status", [(CredentialUnauthorized("synthetic"), 403),
                                        (PermissionError("synthetic-private-path"), 503),
                                        (OSError("synthetic-private-path"), 503),
                                        (CorruptState("synthetic-private-data"), 503)])
def test_execution_errors_are_sanitized_and_distinguish_revoked_sessions_from_file_errors(configured, monkeypatch,
                                                                                       error, status):
    web = configured.web
    form = web.form("/einstellungen", action=SAVE, name="IMAP_PASSWORD")
    def failed(*args):
        raise error
    monkeypatch.setattr("mailhelp.credentials.CredentialService.save", failed)
    response = web.browser.request("POST", SAVE, {**form, "value": "synthetic-new"})
    assert response.status == status and "synthetic" not in response.body.decode()


def test_override_and_inheritance_hints_never_disclose_values_and_escape_labels(configured, monkeypatch):
    web = configured.web
    monkeypatch.setenv("IMAP_PASSWORD", "synthetic-process-password")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "synthetic-inherited-id")
    path = configured.tmp_path / "config.yaml"
    cfg = yaml.safe_load(path.read_text())
    cfg["target_profiles"] = [{"id": 2, "label": "<script>profile</script>", "google_calendar": "primary",
                               "todoist_project": "inbox"}]
    path.write_text(yaml.safe_dump(cfg))
    page = web.browser.request("GET", "/einstellungen").body.decode()
    assert "Eine Prozessvariable überschreibt" in page
    assert "aus den globalen Zugangsdaten geerbt" in page
    assert "synthetic-process-password" not in page and "synthetic-inherited-id" not in page
    assert "&lt;script&gt;profile&lt;/script&gt;" in page and "<script>profile</script>" not in page
