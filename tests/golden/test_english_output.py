"""7.8.1: the frozen English pages show no owned German label (an unmarked table or a raw join).

Mail content of the synthetic fixtures is German on purpose, so only whole text nodes, options and
accessible names are compared with the catalogue, never words inside a sentence.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

import pytest

from mailhelp.i18n.en import EN

OUTPUT = Path(__file__).parent / "output"
# Spelt the same in English, as a button ("Filter") next to the tab label "Filters".
SAME_IN_ENGLISH = {"Filter"}
OWNED = {key for key, value in EN.items() if key != value and "{" not in key and key not in SAME_IN_ENGLISH}
PAGES = sorted(OUTPUT.glob("*-en.html"))


def visible(text: str) -> set[str]:
    nodes = re.findall(r">([^<>]+)<", text) + re.findall(r'(?:aria-label|title|placeholder|alt)="([^"]+)"', text)
    return {html.unescape(node).strip() for node in nodes}


def test_every_frozen_page_has_an_english_twin():
    assert len(PAGES) >= 20
    assert {page.name.removesuffix("-en.html") for page in PAGES} <= {
        page.name.removesuffix(".html") for page in OUTPUT.glob("*.html")}


@pytest.mark.parametrize("page", PAGES, ids=lambda page: page.stem)
def test_english_pages_show_no_owned_german_label(page):
    assert sorted(visible(page.read_text(encoding="utf-8")) & OWNED) == []


def test_the_check_finds_an_untranslated_label():
    assert visible('<a href="/">Alle</a><button aria-label="Schließen">x</button>') & OWNED == {"Alle", "Schließen"}
