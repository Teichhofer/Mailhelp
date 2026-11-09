"""Design tokens 5.0 (Planung 5.0, 21.1): contrast is computed from app.css, not asserted."""
import json
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / 'src' / 'mailhelp' / 'web' / 'static'
CSS = (STATIC / 'app.css').read_text(encoding='utf-8')

TEXTS = ('text', 'muted', 'accent', 'danger', 'ok', 'warn', 'kind-event', 'kind-task', 'kind-draft')
SURFACES = ('bg', 'surface', 'surface-2')
PAIRS = (('accent-text', 'accent'), ('accent', 'accent-soft'), ('text', 'accent-soft'), ('muted', 'accent-soft'),
         ('danger', 'danger-soft'), ('ok', 'ok-soft'), ('warn', 'warn-soft'),
         ('text', 'danger-soft'), ('text', 'ok-soft'), ('text', 'warn-soft'),
         ('sidebar-text', 'sidebar-bg'), ('sidebar-muted', 'sidebar-bg'),
         ('sidebar-text', 'sidebar-hover'), ('sidebar-text', 'sidebar-active'))


def tokens(block):
    return dict(re.findall(r'--([a-z0-9-]+):\s*(#[0-9a-f]{6})\s*;', block))


def light():
    return tokens(CSS[CSS.index(':root {'):CSS.index('@media (prefers-color-scheme: dark)')])


def dark():
    block = CSS[CSS.index('@media (prefers-color-scheme: dark)'):]
    return {**light(), **tokens(block[:block.index('\n}\n')])}


def luminance(colour):
    channels = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_contrast_formula_matches_the_wcag_reference_values():
    assert contrast('#000000', '#ffffff') == pytest.approx(21)
    assert contrast('#777777', '#ffffff') == pytest.approx(4.48, abs=0.01)
    # The colours of the first 5.0 draft that failed WCAG AA (Planung 5.0, 1.2).
    assert contrast('#059669', '#ffffff') < 4.5
    assert contrast('#ea580c', '#ffffff') < 4.5
    assert contrast('#0d9488', '#ffffff') < 4.5


@pytest.mark.parametrize('scheme', [light, dark], ids=['light', 'dark'])
def test_every_text_and_surface_pair_reaches_wcag_aa(scheme):
    palette = scheme()
    pairs = [(t, s) for t in TEXTS for s in SURFACES] + list(PAIRS)
    failures = [(t, s, round(contrast(palette[t], palette[s]), 2)) for t, s in pairs
                if contrast(palette[t], palette[s]) < 4.5]
    assert failures == []


def test_the_dark_scheme_redefines_every_colour_except_focus():
    assert set(light()) - set(tokens(CSS[CSS.index('@media (prefers-color-scheme: dark)'):])) == {'focus'}


def test_colours_come_from_tokens_outside_the_token_blocks():
    rules = CSS[CSS.index('*, *::before'):]
    assert re.findall(r'#[0-9a-fA-F]{6}\b', rules) == ['#ffffff']
    for removed in ('#14372d', '#f4faf6', '#b8cfc5', '#dceadf', '#204d3d', '#27654d', '#557969'):
        assert removed not in CSS


def test_theme_colour_is_the_same_everywhere():
    from mailhelp.web import pages
    accent = light()['accent']
    manifest = json.loads((STATIC / 'manifest.webmanifest').read_text(encoding='utf-8'))
    assert manifest['theme_color'] == accent
    assert manifest['background_color'] == light()['bg']
    assert f'<meta name="theme-color" content="{accent}">' in (STATIC / 'offline.html').read_text(encoding='utf-8')
    assert f'<meta name="theme-color" content="{accent}">' in Path(pages.__file__).read_text(encoding='utf-8')


def test_numbers_use_tabular_figures():
    assert re.search(r'\.stat strong \{[^}]*tabular-nums', CSS)
    assert re.search(r'\.count \{[^}]*tabular-nums', CSS)
