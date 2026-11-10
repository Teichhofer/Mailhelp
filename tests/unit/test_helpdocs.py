"""5.3 H7: the packaged help, its integrity check and the deterministic context selection."""
import json
import runpy
import shutil
import sys

import pytest

from devtools import help_index
from mailhelp import __version__
from mailhelp.helpdocs import DIRECTORY, HelpUnavailable, load


def ids(sections):
    return [section.id for section in sections]


def test_the_packaged_help_matches_the_released_sources():
    assert help_index.main(["--check"]) == 0
    base = load()
    assert len(base.sections) > 50 and len({section.id for section in base.sections}) == len(base.sections)
    assert {section.source for section in base.sections} == set(help_index.SOURCES)
    assert not any(word in source for source in help_index.SOURCES for word in ("Planung", "Release", "CHANGELOG"))
    assert all(section.size <= help_index.MAX_SECTION for section in base.sections)


def test_the_generator_splits_by_headings_and_long_sections(tmp_path, monkeypatch, capsys):
    text = "# Titel\n\nEinleitung `poll_interval_seconds`.\n\n## Lang\n" + "\n".join(
        f"| Zeile {number} | " + "x" * 300 + " |" for number in range(40)) + "\n\n### Leer\n\n## Größe ändern\nText\n"
    found = help_index.sections("docs/Beispiel.md", text, frozenset({"poll_interval_seconds"}))
    assert [item["id"] for item in found][:2] == ["beispiel/titel", "beispiel/lang"]
    assert any(item["id"] == "beispiel/lang-2" for item in found) and found[-1]["id"] == "beispiel/groesse-aendern"
    assert found[0]["setting_ids"] == ["poll_interval_seconds"] and found[-1]["path"] == ["Titel", "Größe ändern"]
    target = tmp_path / "hilfe"
    assert help_index.main([], target=target) == 0
    assert help_index.main(["--check"], target=target) == 0
    (target / "manifest.json").write_text("{}", encoding="utf-8")
    assert help_index.main(["--check"], target=target) == 1 and "veraltet" in capsys.readouterr().err
    monkeypatch.setattr(sys, "argv", ["help_index", "--check"])
    with pytest.raises(SystemExit) as stop:
        runpy.run_module("devtools.help_index", run_name="__main__")
    assert stop.value.code == 0


@pytest.mark.parametrize("damage", ["missing", "version", "revision", "json", "structure"])
def test_an_unusable_resource_disables_the_help(tmp_path, damage):
    copy = tmp_path / "hilfe"
    shutil.copytree(DIRECTORY, copy, ignore=shutil.ignore_patterns("*.py", "__pycache__"))
    manifest = json.loads((copy / "manifest.json").read_text(encoding="utf-8"))
    version = "0.0.1" if damage == "version" else __version__
    if damage == "missing":
        (copy / "sections.json").unlink()
    elif damage == "revision":
        (copy / "sections.json").write_text("[]", encoding="utf-8")
    elif damage == "json":
        (copy / "manifest.json").write_text("kein json", encoding="utf-8")
    else:
        payload = json.dumps([{"id": "x"}], ensure_ascii=False, sort_keys=True, indent=1)
        (copy / "sections.json").write_text(payload + "\n", encoding="utf-8")
        import hashlib
        manifest["revision"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        (copy / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(HelpUnavailable):
        load(copy, version)


def test_a_named_setting_a_question_and_a_follow_up_select_relevant_sections():
    base = load()
    assert ids(base.select("Was bewirkt das Abrufintervall?"))[0] == "web-einstellungen/mailabruf-und-betrieb"
    assert ids(base.select("Was bedeutet das?", setting_id="poll_interval_seconds"))[0] == \
        "web-einstellungen/mailabruf-und-betrieb"
    first = ids(base.select("Wie lege ich ein zweites Postfach an und ordne ihm einen anderen Kalender zu?"))
    assert "konten-verwalten/ein-postfach-einem-anderen-kalender-oder-einer-anderen-aufgabenliste-zuordnen" in first[:3]
    assert "betrieb/speichern-aktivieren-neuladen-und-neustart" == ids(
        base.select("Was ist der Unterschied zwischen Speichern, Aktivieren und Neuladen?"))[0]
    follow_up = ids(base.select("Und pro Postfach?", history=("Was bewirkt das Abrufintervall?",)))
    assert "web-einstellungen/mailabruf-und-betrieb" in follow_up


def test_no_section_is_claimed_for_an_unrelated_or_empty_question_and_limits_hold():
    base = load()
    assert base.select("Bananenbrot") == [] and base.select("Und dann?") == [] and base.select("") == []
    many = base.select("Postfach Kalender Aufgaben Ziel Zielprofil Konto")
    assert 0 < len(many) <= 6 and len(base.select("Postfach Kalender", limit=2)) == 2
    small = base.select("Postfach Kalender Aufgaben", budget=3000)
    assert sum(section.size for section in small) <= 3000
    assert base.get("betrieb/sicherung").title == "Sicherung" and base.get("gibt-es-nicht") is None


def test_a_checkout_with_crlf_line_endings_still_matches(tmp_path):
    # Git with core.autocrlf may check the packaged JSON out with CRLF; reading in text mode
    # folds it, so the revision still matches.
    copy = tmp_path / "hilfe"
    copy.mkdir()
    for name in ("sections.json", "manifest.json"):
        text = (DIRECTORY / name).read_text(encoding="utf-8")
        (copy / name).write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    assert load(copy).revision == load().revision
    assert help_index.main(["--check"], target=copy) == 0


def test_a_section_larger_than_the_remaining_budget_is_left_out():
    base = load()
    question = "Wie lege ich ein zweites Postfach an und ordne ihm einen anderen Kalender zu?"
    full = base.select(question)
    smallest = min(section.size for section in full)
    assert base.select(question, budget=1) == []
    kept = base.select(question, budget=smallest)
    assert [section.size for section in kept] == [smallest] and len(kept) < len(full)
