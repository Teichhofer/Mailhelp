"""Comment-preserving changes to config.yaml."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from mailhelp.yaml_edit import YamlEditError, render, set_scalars
from test_web_actions import web  # noqa: F401  (fixture)

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
    from test_web_v12 import configure
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
    from mailhelp.configuration import AdminCommand, AdminKind, file_hash
    from mailhelp.review.results import ResultStatus
    from test_web_v12 import configure
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
