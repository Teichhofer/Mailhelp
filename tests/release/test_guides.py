"""5.3 H5/H6: the current guides name only controls that exist and link only to existing sections."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUIDES = ["docs/Ersteinrichtung.md", "docs/Konten-verwalten.md", "docs/Ziele-einrichten.md", "docs/Bedienung.md",
          "docs/Fehlerbehebung.md", "docs/Betrieb.md"]
SOURCE = " ".join(" ".join(path.read_text(encoding="utf-8").split())
                  for path in (ROOT / "src" / "mailhelp").rglob("*.py"))


def slug(heading: str) -> str:
    """The anchor a Markdown renderer like GitHub derives from a heading."""
    text = re.sub(r"[^\w\- ]", "", heading.strip().casefold())
    return text.replace(" ", "-")


def anchors(document: Path) -> set[str]:
    return {slug(line.lstrip("#")) for line in document.read_text(encoding="utf-8").splitlines()
            if line.startswith("#")}


@pytest.mark.parametrize("guide", GUIDES)
def test_every_named_control_exists_in_the_application(guide):
    text = (ROOT / guide).read_text(encoding="utf-8")
    missing = []
    for phrase in re.findall(r"\*\*([^*]+)\*\*", text):
        phrase = " ".join(phrase.split())
        if phrase.endswith(":"):
            continue  # a structural word such as "Ergebnis:"
        parts = [part.strip() for part in phrase.split("→")]
        missing += [part for part in parts if part not in SOURCE]
    assert missing == []


@pytest.mark.parametrize("guide", GUIDES)
def test_every_relative_link_and_anchor_exists(guide):
    path = ROOT / guide
    broken = []
    for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
        if target.startswith(("http://", "https://")):
            continue
        name, _, anchor = target.partition("#")
        document = (path.parent / name).resolve() if name else path
        if not document.exists() or (anchor and anchor not in anchors(document)):
            broken.append(target)
    assert broken == []


def test_the_anchor_rule_matches_the_heading_format():
    assert slug("Postfächer (`imap.mailboxes`)") == "postfächer-imapmailboxes"
    assert slug("1. Installieren") == "1-installieren"
