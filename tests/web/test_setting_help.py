"""Every editable setting has safe, documented help with a connected trigger."""
from html import escape
from pathlib import Path

from mailhelp.configuration import SETTINGS_FIELDS
from mailhelp.web.archive_site import setting_label, settings_page
from mailhelp.web.setting_help import EXTRA_HELP, SETTING_HELP, help_bubble


def test_all_settings_have_matching_documentation_and_connected_help():
    assert set(SETTING_HELP) == SETTINGS_FIELDS
    document = (Path(__file__).resolve().parents[2] / "docs/Web-Einstellungen.md").read_text(encoding="utf-8")
    page = settings_page([], {}, {}, "revision", "csrf")
    for name, explanation in SETTING_HELP.items():
        assert f"`{name}`" in document and explanation in document
        assert setting_label(name) in document
        identity = "help-" + name.replace(".", "-")
        assert page.count(f'id="{identity}"') == 1
        assert f'aria-describedby="{identity}"' in page
        assert escape(explanation, quote=True) in page
    assert page.count('role="tooltip"') == len(SETTINGS_FIELDS) + 1
    for explanation in EXTRA_HELP.values():
        assert explanation in document


def test_help_escapes_names_labels_and_text():
    html = help_bubble('unsafe"', '<img src=x>', '<script>alert("x")</script>')
    assert '<img' not in html and '<script>' not in html
    assert 'help-unsafe&quot;' in html and '&lt;script&gt;' in html
    assert 'type="button"' in html
