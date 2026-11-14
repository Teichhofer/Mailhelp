"""6.2.1: corners, type sizes, shadows and colours come from one scale of tokens (Planung 6.2, 3.1)."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "mailhelp" / "web" / "static"
CSS = (STATIC / "app.css").read_text(encoding="utf-8")
RULES = CSS[CSS.index("*, *::before"):]
ROOT = CSS[:CSS.index("*, *::before")]


def declarations(name):
    return [value.strip() for value in re.findall(name + r":\s*([^;}]+?)\s*(?=[;}])", RULES)]


def test_every_corner_uses_a_radius_token():
    allowed = re.compile(r"^(0|50%|var\(--radius(-xs|-s|-m|-pill)?\))$")
    stray = [value for value in declarations("border-radius")
             if not all(allowed.match(part) for part in value.split())]
    assert stray == []


def test_every_type_size_uses_a_text_token():
    allowed = re.compile(r"^(0|[.\d]+em|var\(--text-(2xs|xs|s|m|base|l|xl|2xl|3xl)\))$")
    assert [value for value in declarations("font-size") if not allowed.match(value)] == []


def test_shadows_and_colours_outside_the_token_blocks_are_tokens():
    assert re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", RULES) == []
    assert [value for value in declarations("box-shadow") if not re.match(r"^(none|var\(--[a-z-]+\)|[0-9px .-]+var\(--[a-z-]+\))$", value)] == []


def test_every_token_used_is_defined():
    defined = set(re.findall(r"--([a-z0-9-]+):", ROOT)) | {"kind-colour", "sidebar-width"}
    assert {name for name in re.findall(r"var\(--([a-z0-9-]+)", RULES)} - defined == set()
