"""The producer/worker seam must cover every sendable category."""

import re
from pathlib import Path

from mailhelp.config.notifications import CATEGORIES


def test_every_producer_category_has_a_fixed_worker_text_and_target():
    worker = Path("src/mailhelp/web/static/sw.js").read_text(encoding="utf-8")
    entries = set(re.findall(r"^\s*(\w+): \{ body:", worker, re.M))
    assert set(CATEGORIES) | {"test"} <= entries
    assert "information" in entries
