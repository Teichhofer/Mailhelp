"""8.9.2 (Planung 8.9 AP2): the building blocks of action identity, synthetic titles only."""
import copy
import json
from pathlib import Path

from mailhelp.llm.action_matching import evidence_score, identity, same_word, title_score, verbs, verified
from mailhelp.llm.quality_metrics import gate, report
from mailhelp.llm.stage_contract import compare_stages
from mailhelp.proposals.action_normalization import MailDateContext

ROOT = Path(__file__).resolve().parents[2]
CORPUS = json.loads((ROOT / "tests/fixtures/mail_corpus_v5/corpus.json").read_text(encoding="utf-8"))
BASELINE = json.loads((ROOT / "quality-reports/baseline-8.9.json").read_text(encoding="utf-8"))


def test_words_compounds_stems_and_short_words():
    assert same_word("belege", "reisekostenbelege") and same_word("rueckmelden", "rueckmeldung")
    assert not same_word("abc", "abcd")  # too short for a compound and a stem
    assert not same_word("rechnung", "rechner")
    assert verbs("Kopie zurückschicken") == {"send"} and verbs("Rechnung") == set()


def test_empty_titles_and_quotes_score_nothing():
    assert title_score("", "Bericht senden") == 0.0 and title_score("der die", "Bericht") == 0.0
    assert evidence_score("", "Bericht") == 0.0 and not verified("", "Bericht")
    assert evidence_score("Bericht bis Freitag", "bitte den Bericht senden") == 1 / 3  # {bericht} of three words


def test_a_weak_title_without_a_verified_quote_is_no_candidate():
    expected = {"title": "Protokoll senden", "evidence": "Bitte das Protokoll senden", "aliases": []}
    assert identity(expected, {"title": "Bericht senden", "evidence": "nicht in der Mail"}, "Bitte das Protokoll senden") is None
    # The same weak title passes with the overlapping verified quote of the expected action.
    assert identity(expected, {"title": "Unterlagen senden", "evidence": "das Protokoll senden"},
                    "Bitte das Protokoll senden") == 0.5 + 1.0
    alias = {**expected, "aliases": ["Sitzungsnotizen verschicken"]}
    assert identity(alias, {"title": "Sitzungsnotizen verschicken", "evidence": "x"}, "") == 2.0


def test_an_open_review_blocks_the_gate():
    answers = {case["id"]: {"result": {stage: copy.deepcopy(case["expected"][stage])
                                       for stage in ("relevance", "task_extraction", "event_extraction")}}
               for case in CORPUS["cases"]}
    events = answers["30_council_series"]["result"]["event_extraction"]["events"]
    for event in events:  # equal titles, one shared quote and no day: the pairs cannot be told apart
        event.update(title="Gemeinderatssitzung", evidence="Sitzungstermine 2027", date_text=None)
    result = report(CORPUS, answers, "model")
    assert result["totals"]["event"]["review"] > 0
    assert any("Review offen" in reason for reason in gate(result, BASELINE))


def test_stages_missing_after_an_error_are_not_compared():
    context = MailDateContext(date_context_status="missing", date_header_parsed=None, imap_received_at=None,
                              user_timezone=None)
    assert compare_stages(CORPUS["cases"][0], {}, "", context) == {}
