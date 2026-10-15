"""Further operational settings in the web interface (3.3.12, Planung 3.4 Phase 3)."""
from __future__ import annotations

import pytest
import yaml
from shared_web_v12 import configure

from mailhelp.configuration import SETTINGS_FIELDS, SETUP_FIELDS, AdminCommand, AdminKind, file_hash
from mailhelp.web.settings_pages import SETTING_GROUPS

VALID = {
    "imap.batch_size": 40, "imap.global_newest_first": True, "telegram.user_id": 42, "telegram.chat_id": -100,
    "telegram.sequential_questions": False, "smart_reply": True, "vision.enabled": False,
    "vision.max_images_per_mail": 5, "vision.max_image_bytes": 20000, "vision.max_edge_pixels": 2048,
    "daily_briefing.include_calendar": False, "daily_briefing.include_tasks": False,
    "daily_briefing.include_open": False, "activity_report.enabled": True, "activity_report.max_mails": 100,
    "activity_report.max_llm_calls": 200, "activity_report.max_share_of_llm_budget": 0.25,
    "activity_report.max_fulltext_chars": 5000, "activity_report.export_mails_without_events": False,
    "learning.parallel_llm_calls": 8, "retention.activity_report_days": "unlimited", "web.session_days": 7,
    "logging.console.enabled": False, "logging.file.enabled": False, "logging.llm.enabled": False,
    "logging.llm.level": "WARNING", "logging.telegram.enabled": False, "logging.telegram.level": "ERROR",
}
INVALID = {"imap.batch_size": 0, "telegram.user_id": 0, "vision.max_images_per_mail": 11,
           "activity_report.max_share_of_llm_budget": 2, "learning.parallel_llm_calls": 0,
           "web.session_days": 400, "logging.llm.level": "LAUT", "web.lan_access": True}


def candidate(service, tmp_path, name, value):
    return service.candidate(AdminCommand(kind=AdminKind.SETTINGS, actor="web:" + "a" * 16, idempotency_key="k" * 16,
                                          expected_hash=file_hash(tmp_path / "config.yaml"),
                                          patch={name: value}, acknowledged=True))


def test_every_new_setting_is_offered_grouped_and_validated(web, tmp_path):
    service, *_ = configure(web, tmp_path)
    assert set(VALID) | {"web.lan_access"} <= SETTINGS_FIELDS
    grouped = {name for name in SETTINGS_FIELDS for _, prefixes in SETTING_GROUPS if name.startswith(prefixes)}
    assert grouped == SETTINGS_FIELDS
    for name, value in VALID.items():
        stored = candidate(service, tmp_path, name, value)
        for part in name.split("."):
            stored = stored[part]
        assert stored == value, name
    for name, value in INVALID.items():
        with pytest.raises(ValueError):
            candidate(service, tmp_path, name, value)
    for excluded in ("data_directory", "web.host", "web.port", "web.enabled", "web.allowed_hosts",
                     "logging.file.filename", "limits.max_html_tags"):
        assert excluded not in SETTINGS_FIELDS
        with pytest.raises(ValueError, match="Nicht angebotene Einstellung"):
            candidate(service, tmp_path, excluded, 1)


def test_settings_page_shows_the_new_groups_with_their_controls(web, tmp_path):
    configure(web, tmp_path)
    page = web.browser.request("GET", "/einstellungen").body.decode()
    for group in ("Telegram", "Bildauswertung", "Tagesüberblick", "Tätigkeitsberichte", "Lernmodus", "Weboberfläche"):
        assert f">{group}<" in page
    assert "Mails je Abrufdurchlauf" in page and "Antwortentwürfe anbieten" in page
    form = web.form("/einstellungen", action="/einstellungen/speichern", name="imap.batch_size")
    accepted = web.browser.request("POST", "/einstellungen/speichern", {**form, "value": "60", "confirm": "yes"})
    assert accepted.status == 303
    web.run()
    assert yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))["imap"]["batch_size"] == 60


def test_historical_start_is_part_of_the_mailbox_setup():
    assert "imap.historical_start" in SETUP_FIELDS
    from mailhelp.configuration import MAILBOX_SETUP_FIELDS
    from mailhelp.web.setup_site import FIELDS, field_label
    assert "historical_start" in MAILBOX_SETUP_FIELDS and "imap.historical_start" in FIELDS[2]
    raw = {"imap": {"mailboxes": [{"id": 3, "label": "Verein"}]}}
    assert field_label(raw, "imap.mailboxes.0.historical_start").startswith("Ältere Mails nicht verarbeiten vor")
