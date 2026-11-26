"""8.7.11: static web assets have the same bytes, and so the same cache keys, on every platform.

Regression: the ``?v=`` cache keys hash the delivered bytes. Windows checkouts converted the stylesheet and
scripts to CRLF, so the frozen pages written on Windows never matched on Ubuntu CI (``app.css?v=78f1…``
against ``5a32…``) and the Docker image announced other keys than a local Windows installation.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mailhelp.web.app import PAGE_SCRIPTS, ROOT_FILES, STATIC_FILES, static_file

ROOT = Path(__file__).resolve().parents[2]
TEXT = sorted(name for name in (*STATIC_FILES, *ROOT_FILES) if not name.endswith(".png"))


@pytest.mark.parametrize("name", TEXT)
def test_regression_static_text_assets_are_checked_out_with_lf(name):
    assert b"\r" not in static_file(name), name


def test_the_rule_is_recorded_for_every_text_asset_type():
    rules = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    for suffix in sorted({Path(name).suffix for name in TEXT}):
        assert f"src/mailhelp/web/static/*{suffix} text eol=lf" in rules, suffix


def test_every_versioned_asset_is_a_checked_text_asset():
    assert {"app.css", *PAGE_SCRIPTS} <= set(TEXT) and "sw.js" in TEXT
