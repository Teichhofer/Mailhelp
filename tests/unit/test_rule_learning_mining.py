import json

import pytest

from mailhelp.rule_learning import mining
from mailhelp.rule_learning.mining import DecisionRuleMiner, signal
from tests.fakes.rule_learning import record


def test_missing_empty_malformed_and_duplicate_records_are_bounded_and_redacted(tmp_path):
    path = tmp_path / "decisions.jsonl"
    miner = DecisionRuleMiner(path, lambda text: text.replace("secret-token", "[entfernt]"))
    assert miner.mine() == ([], 0)
    values = [record(), record(), [], record(schema_version=2), record(identity="", kind="confirm"),
              record(identity="unused", kind="clarify"), {"schema_version": 1, "analysis": []}]
    path.write_text("bad json\n" + "\n".join(json.dumps(item) for item in values), encoding="utf-8")
    evidence, skipped = miner.mine()
    assert len(evidence) == 1 and skipped == 7
    assert "secret-token" not in str(evidence) and "[entfernt]" in str(evidence)
    assert miner.counts(evidence) == {"rejected_proposal": 1}
    path.write_text("", encoding="utf-8")
    assert miner.mine() == ([], 0)


@pytest.mark.parametrize("kind,changes,expected", [
    ("already_done", {}, "positive_already_done"),
    ("reject", {}, "rejected_proposal"),
    ("edit", {"proposal": {"changes": {"title": ["a", "b"]}}}, "manual_correction"),
    ("answer", {"proposal": {"changes": {"due_date": [None, "2026-11-12"]}}}, "manual_correction"),
    ("edit", {}, None), ("confirm", {}, None),
    ("confirm", {"analysis": {"relevance": {"topic_ids": []}}}, "unclassified_confirmation"),
    ("relevance", {"decision": "irrelevant"}, "relevance_disagreement"),
    ("relevance", {"decision": "relevant"}, None), ("relevance", {"decision": "unknown"}, None),
])
def test_the_actual_record_formats_have_distinct_signals(kind, changes, expected):
    assert signal(record(kind=kind, **changes)) == expected


def test_tail_limits_do_not_read_a_large_log_or_retain_excess_evidence(tmp_path, monkeypatch):
    path = tmp_path / "large.jsonl"
    monkeypatch.setattr(mining, "MAX_BYTES", 2000)
    monkeypatch.setattr(mining, "MAX_RECORDS", 3)
    monkeypatch.setattr(mining, "MAX_EVIDENCE", 2)
    rows = [record(identity=str(n), proposal={"changes": {"title": ["a", "b"], "status": [1, 2]}}) for n in range(20)]
    path.write_text("\n".join(json.dumps(item) for item in rows), encoding="utf-8")
    evidence, skipped = DecisionRuleMiner(path).mine()
    assert [item["id"] for item in evidence] == ["19", "18"] and skipped == 0
    assert set(evidence[0]["changes"]) == {"title"}


def test_a_record_with_invalid_utf8_is_skipped_as_corrupt(tmp_path):
    path = tmp_path / "decisions.jsonl"
    content = json.dumps(record()).encode("utf-8").replace(b"Elternbrief", b"Eltern\xffbrief")
    path.write_bytes(content)
    assert DecisionRuleMiner(path).mine() == ([], 1)
