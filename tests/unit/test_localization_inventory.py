"""7.8: interface coverage is checked independently of executable code coverage."""
import html
import json
import re
import string
from html.parser import HTMLParser
from pathlib import Path

from mailhelp.i18n import Locale, tr, use_locale
from mailhelp.i18n.en import EN
from mailhelp.web.js_texts import JS_TEXTS, messages
from mailhelp.web.pages import layout


class Shape(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, [(key, value) for key, value in attrs
                                if key not in {"title", "aria-label", "placeholder", "data-label"}]))

    def handle_endtag(self, tag):
        self.tags.append(("/" + tag, []))


def fields(text):
    return sorted(name for _text, name, _spec, _conversion in string.Formatter().parse(text) if name)


def test_inventory_has_both_languages_and_preserves_machine_attributes():
    inventory = json.loads((Path(__file__).resolve().parents[2] / "docs/Localization-7.8.json").read_text("utf-8"))
    assert len({row["surface"] for row in inventory}) >= 40
    for row in inventory:
        key = row["key"]
        assert key in EN, row
        assert fields(key) == fields(EN[key]), row
        assert Shape(key).tags == Shape(EN[key]).tags, row
        with use_locale(Locale.DE):
            assert tr(key) == key
        with use_locale(Locale.EN):
            assert tr(key) == EN[key]


def test_javascript_messages_are_transferred_as_escaped_data_for_each_language():
    assert all(text in EN for text in JS_TEXTS)
    assert messages(Locale.DE) == "{}"
    english = json.loads(messages(Locale.EN))
    assert set(english) == set(JS_TEXTS) and english["● Verbunden"] == "● Connected"
    with use_locale(Locale.EN):
        page = layout("Mailhelp", "<p>Private content</p>")
    encoded = re.search(r'data-ui-texts="([^"]+)"', page)[1]
    assert json.loads(html.unescape(encoded)) == english
    assert "Private content" in page


def test_form_payloads_stay_canonical_when_a_label_is_marked():
    from mailhelp.i18n import msg
    from mailhelp.web.forms import field, select
    from mailhelp.web.http import Response
    with use_locale(Locale.EN):
        assert 'value="nein"' in field("answer", "", msg("nein"), hidden=True)
        options = select("choice", msg("Antwort"), "nein", [(msg("nein"), msg("Nein"))])
        assert '<option value="nein" selected>No</option>' in options
        assert Response.text(400, msg("Abbrechen")).body == b"Cancel"
        assert Response.html(200, msg("Abbrechen")).body == b"Cancel"


def test_json_rendering_translates_owned_labels_and_preserves_user_strings_and_codes():
    from mailhelp.i18n import msg
    from mailhelp.web.http import Response
    with use_locale(Locale.EN):
        response = Response.json(200, {"label": msg("Offen"), "subject": "Offen", "code": "queued",
                                       "nested": (None, 3, [msg("Abbrechen"), "Abbrechen"])})
    assert json.loads(response.body) == {"label": "Open", "subject": "Offen", "code": "queued",
                                         "nested": [None, 3, ["Cancel", "Abbrechen"]]}
