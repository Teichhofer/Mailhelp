"""8.7 §5.2: only the operator sets the valuation, at the host, with old/new values and an example."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from mailhelp.usage.operator_cli import CONFIRMATION, set_valuation
from mailhelp.usage.valuations import USAGE_DIRECTORY, Valuations

START = datetime(2026, 12, 1, 8, tzinfo=UTC)


def run(directory, rate, markup, answer=CONFIRMATION, at=START):
    lines: list[str] = []
    code = set_valuation(directory, rate, markup, ask=lambda prompt: lines.append(prompt) or answer,
                         out=lines.append, clock=lambda: at)
    return code, lines


def test_the_first_and_a_later_valuation_show_old_new_and_an_example(tmp_path):
    code, lines = run(tmp_path, "1,25", "25")
    assert code == 0 and "kein Bewertungsstand" in lines[0] and "1.25 USD je EUR, Aufschlag 25 %" in lines[1]
    assert lines[2] == "Beispiel: 0.01 USD ergeben 10,00 Punkte" and CONFIRMATION in lines[4]
    assert lines[5].startswith("Gespeichert: Stand 1")
    code, lines = run(tmp_path, "1.25", "0", at=START + timedelta(days=1))
    assert code == 0 and "Stand 1" in lines[0] and lines[2].endswith("8,00 Punkte (bisher 10,00 Punkte)")
    revisions = Valuations(tmp_path / USAGE_DIRECTORY).revisions()
    assert [(item.revision, item.markup_percent) for item in revisions] == [(1, Decimal(25)), (2, Decimal(0))]


def test_without_the_exact_confirmation_nothing_changes(tmp_path):
    code, lines = run(tmp_path, "1.25", "25", answer="ja")
    assert code == 1 and lines[-1] == "Nicht geändert." and not (tmp_path / USAGE_DIRECTORY).exists()


def test_invalid_values_are_refused_before_asking(tmp_path):
    for rate, markup in (("0", "25"), ("abc", "1"), ("1.25", "-5"), ("NaN", "0")):
        code, lines = run(tmp_path, rate, markup)
        assert code == 2 and lines[0].startswith("FEHLER: Kurs muss positiv") and len(lines) == 1


def test_an_unreadable_file_or_a_revision_in_the_past_is_reported(tmp_path):
    assert run(tmp_path, "1.25", "25")[0] == 0
    code, lines = run(tmp_path, "1.25", "25")  # same moment: must begin after the last
    assert code == 2 and "nach dem letzten" in lines[-1]
    (tmp_path / USAGE_DIRECTORY / "valuations.json").write_text("{", encoding="utf-8")
    code, lines = run(tmp_path, "1.25", "25")
    assert code == 2 and lines == ["FEHLER: Bewertungsstände sind nicht lesbar"]
