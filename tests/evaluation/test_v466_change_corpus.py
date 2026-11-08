"""4.6, step 17.7: synthetic changes and cancellations in corpus v3."""
import json
from pathlib import Path

from mailhelp.llm.evaluation import semantic_result
from mailhelp.proposals.action_normalization import MailDateContext

CORPUS = Path(__file__).parents[1] / "fixtures" / "mail_corpus_v3" / "corpus.json"
CHANGES = {"35_change_one_week_later": ("change", "04.12.2026"), "36_change_later_start": ("change", "26.11.2026"),
           "37_change_new_room": ("change", "24.11.2026"),
           "38_cancellation_without_replacement": ("cancellation", None)}
CONTEXT = MailDateContext(date_context_status="valid", date_header_parsed="2026-11-23T09:00:00+01:00",
                          imap_received_at=None, user_timezone="Europe/Berlin")


def cases():
    return {case["id"]: case for case in json.loads(CORPUS.read_text(encoding="utf-8"))["cases"]}


def test_the_four_cases_cover_move_new_start_new_room_and_cancellation():
    known = cases()
    for case_id, (classification, earlier) in CHANGES.items():
        (event,) = known[case_id]["expected"]["event_extraction"]["events"]
        assert (event["classification"], event["original_date_text"]) == (classification, earlier)
        assert known[case_id]["expected"]["action_route"]["event_count"] == 1
    assert known["37_change_new_room"]["expected"]["event_extraction"]["events"][0]["location"] == "Aula"
    # Every address is synthetic.
    assert all(".example.test" in known[case_id]["raw_email"].split("\n", 1)[0] for case_id in CHANGES)


def test_the_comparison_checks_the_earlier_day_of_a_change():
    (event,) = cases()["35_change_one_week_later"]["expected"]["event_extraction"]["events"]
    right = semantic_result("event_extraction", {"events": [event]}, CONTEXT)
    assert right["events"][0]["original_date"] == "2026-12-04"
    wrong = semantic_result("event_extraction", {"events": [{**event, "original_date_text": "05.12.2026"}]}, CONTEXT)
    assert wrong != right
    unreadable = semantic_result("event_extraction", {"events": [{**event, "original_date_text": "Freitag, kurz"}]},
                                 CONTEXT)
    assert unreadable["events"][0]["original_date"] == "freitag, kurz"
    missing = semantic_result("event_extraction", {"events": [{**event, "original_date_text": None}]}, CONTEXT)
    assert missing["events"][0]["original_date"] is None
