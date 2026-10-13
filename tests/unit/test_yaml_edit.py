"""Comment-preserving changes to config.yaml."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml
from shared_web_actions import web  # noqa: F401  (fixture)

from mailhelp.yaml_edit import YamlEditError, render, set_scalars

TEXT = """# Kopfkommentar
timezone: Europe/Berlin   # Anzeigezeitzone
poll_interval_seconds: 60
name: "a # kein Kommentar" # echter Kommentar
retention:
  # Fristen
  full_mail_days: 30

  debug_llm_days: disabled
timeouts:
  imap:
    timeout_seconds: 30
    retries: 2
  telegram:
    retries: 1
hosts: [a, b]
items:
  - eins
last: x
"""


def test_values_change_on_their_own_line_and_every_comment_stays():
    new = set_scalars(TEXT, {"poll_interval_seconds": 120, "timezone": "UTC",
                             "timeouts.imap.retries": 5, "retention.full_mail_days": "unlimited"})
    assert yaml.safe_load(new) == {**yaml.safe_load(TEXT), "poll_interval_seconds": 120, "timezone": "UTC",
                                   "retention": {"full_mail_days": "unlimited", "debug_llm_days": "disabled"},
                                   "timeouts": {"imap": {"timeout_seconds": 30, "retries": 5},
                                                "telegram": {"retries": 1}}}
    assert "timezone: UTC   # Anzeigezeitzone" in new
    assert new.count("#") == TEXT.count("#")
    assert len(new.splitlines()) == len(TEXT.splitlines())


def test_a_hash_inside_quotes_is_not_a_comment():
    new = set_scalars(TEXT, {"name": "b"})
    assert 'name: b # echter Kommentar' in new and yaml.safe_load(new)["name"] == "b"


def test_missing_keys_are_added_inside_their_section_or_at_the_end():
    new = set_scalars(TEXT, {"retention.analysis_days": 30, "timeouts.ollama.retries": 3,
                             "metrics.ollama_power_watts": 250.5, "metrics.enabled": True})
    data = yaml.safe_load(new)
    assert data["retention"] == {"full_mail_days": 30, "debug_llm_days": "disabled", "analysis_days": 30}
    assert data["timeouts"]["ollama"] == {"retries": 3}
    assert data["metrics"] == {"ollama_power_watts": 250.5, "enabled": True}
    lines = new.splitlines()
    assert lines.index("  analysis_days: 30") < lines.index("timeouts:")
    assert lines[-2:] == ["  ollama_power_watts: 250.5", "  enabled: true"]


def test_a_missing_key_in_an_empty_section_gets_the_default_indent():
    new = set_scalars("web:\nother: 1\n", {"web.port": 9000})
    assert yaml.safe_load(new) == {"web": {"port": 9000}, "other": 1}


def test_sections_and_structures_are_refused():
    with pytest.raises(YamlEditError, match="Abschnitt"):
        set_scalars(TEXT, {"timeouts.imap": 5})
    with pytest.raises(YamlEditError, match="einzelne Werte"):
        set_scalars(TEXT, {"hosts": ["c"]})


@pytest.mark.parametrize(("value", "expected"), [
    (10, "10"), (1.5, "1.5"), (True, "true"), (None, "null"), ("Europe/Berlin", "Europe/Berlin"),
    ("yes", "'yes'"), ("a: b", "'a: b'"), (date(2026, 10, 1), "2026-10-01"), ("Zürich", "Zürich"),
])
def test_scalars_are_rendered_as_yaml(value, expected):
    assert render(value) == expected
    assert yaml.safe_load(f"k: {render(value)}")["k"] == value


def test_web_settings_keep_the_comments_of_the_real_example(web, tmp_path):
    from shared_web_v12 import configure
    service, *_ = configure(web, tmp_path)
    example = Path("config.example.yaml").read_text(encoding="utf-8")
    base = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    # The example's comments with the synthetic test values.
    (tmp_path / "config.yaml").write_text(example, encoding="utf-8")
    text = set_scalars(example, {"data_directory": base["data_directory"]})
    (tmp_path / "config.yaml").write_text(text, encoding="utf-8")
    form = web.form("/einstellungen", action="/einstellungen/speichern", name="poll_interval_seconds")
    response = web.browser.request("POST", "/einstellungen/speichern", {**form, "value": "90", "confirm": "yes"})
    assert response.status == 303
    web.run()
    saved = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert yaml.safe_load(saved)["poll_interval_seconds"] == 90
    assert saved.count("#") == example.count("#")
    assert "  # Gültigkeit einer gekoppelten Browsersitzung in Tagen." in saved


def test_a_file_that_cannot_be_edited_safely_is_left_untouched(web, tmp_path, monkeypatch):
    from shared_web_v12 import configure

    from mailhelp.configuration import AdminCommand, AdminKind, file_hash
    from mailhelp.review.results import ResultStatus
    service, *_ = configure(web, tmp_path)
    path = tmp_path / "config.yaml"
    before = path.read_text(encoding="utf-8")
    monkeypatch.setattr("mailhelp.configuration.set_scalars", lambda text, changes: text)
    command = AdminCommand(kind=AdminKind.SETTINGS, actor=f"web:{web.auth.sessions()[0].id}",
                           idempotency_key="key-unsafe-1", expected_hash=file_hash(path),
                           patch={"poll_interval_seconds": 10}, acknowledged=True)
    result = service.execute(command)
    assert result.status == ResultStatus.INVALID and path.read_text(encoding="utf-8") == before


def test_continuation_lines_of_long_texts_are_not_keys():
    text = "hinweis: >\n  langer Text: kein Schlüssel\n  zweite Zeile\nport: 1\n"
    new = set_scalars(text, {"port": 2})
    assert yaml.safe_load(new) == {"hinweis": "langer Text: kein Schlüssel zweite Zeile\n", "port": 2}


# --- lists (IMAP folders discovered by the learning mode) ---------------------------

def test_new_folders_are_appended_and_comments_in_the_list_stay():
    from mailhelp.yaml_edit import set_list
    text = "imap:\n  folders:\n  - INBOX\n  # Arbeit\n  - Sent\n\n  host: x\nlast: 1\n"
    new = set_list(text, "imap.folders", ["INBOX", "Sent", "Archiv"])
    assert "  # Arbeit\n  - Sent\n  - Archiv\n" in new
    assert yaml.safe_load(new) == {"imap": {"folders": ["INBOX", "Sent", "Archiv"], "host": "x"}, "last": 1}


def test_a_changed_order_rewrites_the_list_and_inline_lists_stay_inline():
    from mailhelp.yaml_edit import set_list
    reordered = set_list("folders:\n- A\n- B\nx: 1\n", "folders", ["B", "A"])
    assert yaml.safe_load(reordered) == {"folders": ["B", "A"], "x": 1}
    inline = set_list("folders: [A]   # Ordner\n", "folders", ["A", "B"])
    assert inline == "folders: [A, B]   # Ordner\n"
    assert set_list("folders: [A]\n", "folders", ["A"]) == "folders: [A]\n"
    empty = set_list("folders:\nx: 1\n", "folders", ["A"])
    assert yaml.safe_load(empty) == {"folders": ["A"], "x": 1}


def test_lists_that_cannot_be_edited_are_refused():
    from mailhelp.yaml_edit import set_list
    with pytest.raises(YamlEditError, match="fehlt"):
        set_list("x: 1\n", "folders", ["A"])
    with pytest.raises(YamlEditError, match="keine Liste"):
        set_list("folders: INBOX\n", "folders", ["A"])


def test_learning_mode_adds_folders_without_losing_comments(tmp_path):
    from mailhelp.learning import add_discovered_folders
    path = tmp_path / "config.yaml"
    example = Path("config.example.yaml").read_text(encoding="utf-8")
    path.write_text(example, encoding="utf-8")
    configured = yaml.safe_load(example)["imap"]["folders"]
    merged = add_discovered_folders(path, configured, [*configured, "Archiv/2026"])
    saved = path.read_text(encoding="utf-8")
    assert merged[-1] == "Archiv/2026" and yaml.safe_load(saved)["imap"]["folders"] == merged
    assert saved.count("#") == example.count("#")
    assert len(saved.splitlines()) == len(example.splitlines()) + 1


def test_learning_mode_refuses_an_unsafe_folder_change(tmp_path, monkeypatch):
    from mailhelp.learning import add_discovered_folders
    path = tmp_path / "config.yaml"
    path.write_text("imap:\n  folders: [INBOX]\n", encoding="utf-8")
    monkeypatch.setattr("mailhelp.learning.set_list", lambda text, dotted, items: text)
    with pytest.raises(RuntimeError, match="von Hand"):
        add_discovered_folders(path, ["INBOX"], ["INBOX", "Neu"])
    assert path.read_text(encoding="utf-8") == "imap:\n  folders: [INBOX]\n"


def test_a_list_at_the_end_of_the_file():
    from mailhelp.yaml_edit import set_list
    assert set_list("x: 1\nfolders:\n- A\n", "folders", ["A", "B"]) == "x: 1\nfolders:\n- A\n- B\n"


def test_long_texts_with_line_breaks_stay_on_one_line():
    """A long personal text must not be wrapped onto continuation lines."""
    value = "Max Mustermann\nVorstand · Förderverein der Grundschule am Park\n" + "x" * 300
    rendered = render(value)
    assert "\n" not in rendered
    new = set_scalars("personal_info: ''\nport: 1\n", {"personal_info": value})
    assert yaml.safe_load(new) == {"personal_info": value, "port": 1} and len(new.splitlines()) == 2


def test_personal_information_is_edited_as_free_text_and_applies_live(web, tmp_path):
    from shared_web_v12 import configure
    service, _, _, active, _ = configure(web, tmp_path)
    page = web.browser.request("GET", "/einstellungen").body.decode()
    assert "<h2>Antworten</h2>" in page and "Persönliche Angaben für Antworten" in page
    assert '<textarea name="value" rows="6" maxlength="2000"></textarea>' in page
    assert "<strong>nicht gesetzt</strong>" in page
    form = web.form("/einstellungen", action="/einstellungen/speichern", name="personal_info")
    text = "Max Mustermann\r\nElternbeirat Klasse 4b\r\nBitte duzen <ok>"
    response = web.browser.request("POST", "/einstellungen/speichern", {**form, "value": text})
    body = response.body.decode()
    assert response.status == 200 and "<pre>Max Mustermann" in body and "&lt;ok&gt;" in body
    response = web.browser.request("POST", "/einstellungen/speichern", {**form, "value": text, "confirm": "yes"})
    assert response.status == 303
    web.run()
    expected = "Max Mustermann\nElternbeirat Klasse 4b\nBitte duzen <ok>"
    assert yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))["personal_info"] == expected
    # Applied without a restart.
    assert service.active.personal_info == expected and active[-1].personal_info == expected
    page = web.browser.request("GET", "/einstellungen").body.decode()
    assert "<strong>Max Mustermann Elternbeirat Klasse 4b Bitte duzen &lt;ok&gt;</strong>" in page
    assert "Elternbeirat Klasse 4b\nBitte duzen &lt;ok&gt;</textarea>" in page
    # Numbers stay text; long texts are shortened in the overview; control characters are refused.
    form = web.form("/einstellungen", action="/einstellungen/speichern", name="personal_info")
    response = web.browser.request("POST", "/einstellungen/speichern", {**form, "value": "1234", "confirm": "yes"})
    assert response.status == 303
    web.run()
    assert service.active.personal_info == "1234"
    form = web.form("/einstellungen", action="/einstellungen/speichern", name="personal_info")
    web.browser.request("POST", "/einstellungen/speichern", {**form, "value": "a" * 80, "confirm": "yes"})
    web.run()
    assert "<strong>" + "a" * 59 + "…</strong>" in web.browser.request("GET", "/einstellungen").body.decode()
    form = web.form("/einstellungen", action="/einstellungen/speichern", name="personal_info")
    assert web.browser.request("POST", "/einstellungen/speichern", {**form, "value": "a\x07b"}).status == 422
