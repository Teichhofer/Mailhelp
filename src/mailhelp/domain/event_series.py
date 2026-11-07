"""Deterministic series identity, independent of displayed date suffixes."""
from __future__ import annotations

import hashlib
import unicodedata
from datetime import date


def series_key(mail_id: str, title: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", title).casefold().split())
    return hashlib.sha256(f"{mail_id}\0{normalized}".encode()).hexdigest()


def dated_title(title: str, day: date | None) -> str:
    if day is None:
        return title
    return f"{title[:487]} – {day:%d.%m.%Y}"
