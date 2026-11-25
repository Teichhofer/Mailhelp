"""8.7 §6: the durable usage ledger (Abnahme 9–13, 17, 18); synthetic attempts only."""
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from mailhelp.usage.ledger import Purpose, UsageCorrupt, UsageLedger, summarize
from mailhelp.usage.points import CostStatus, Valuation
from mailhelp.usage.valuations import (
    LEDGER,
    PURPOSE,
    UsageMeter,
    ValuationError,
    Valuations,
    operator_purpose,
)

BERLIN = ZoneInfo("Europe/Berlin")
START = datetime(2026, 12, 1, 8, tzinfo=UTC)
MAIL = "a" * 24


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


def valuation(rate: str = "1.25", markup: str = "25", revision: int = 1) -> Valuation:
    return Valuation(revision=revision, usd_per_eur=Decimal(rate), markup_percent=Decimal(markup),
                     valid_from=START - timedelta(days=1), actor="operator-cli")


def test_an_attempt_is_written_before_the_call_and_settled_once(tmp_path):
    clock = Clock()
    ledger = UsageLedger(tmp_path / LEDGER, clock)
    ledger.begin("call-1:1", "relevance", Purpose.CUSTOMER, valuation(), MAIL)
    [line] = (tmp_path / LEDGER).read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["type"] == "begun" and "prompt" not in line
    ledger.settle("call-1:1", 0.01, "gen-1")
    ledger.settle("call-1:1", 0.02, "gen-1")  # Abnahme 12: the same result again
    ledger.begin("call-1:1", "relevance", Purpose.CUSTOMER, valuation())  # a duplicate begin
    ledger.settle("unknown", 0.5)
    [attempt] = UsageLedger(tmp_path / LEDGER, clock).attempts()  # Abnahme 13: after a restart
    assert attempt.points == Decimal(10) and attempt.settled is not None
    assert attempt.settled.cost_usd == Decimal("0.01") and attempt.settled.provider_id == "gen-1"
    assert attempt.begun.mail_id == MAIL and len((tmp_path / LEDGER).read_text().splitlines()) == 2


def test_acceptance_12_retries_and_fallbacks_are_new_attempts_that_count(tmp_path):
    ledger = UsageLedger(tmp_path / LEDGER, Clock())
    for number, cost in enumerate((0.004, 0.006), start=1):
        ledger.begin(f"call-1:{number}", "extraction", Purpose.CUSTOMER, valuation(markup="0"))
        ledger.settle(f"call-1:{number}", cost)
    summary = summarize(ledger.attempts(), START - timedelta(days=1), START + timedelta(days=1), BERLIN)
    assert summary.points == Decimal(8) and summary.counted == 2 and summary.complete


def test_acceptance_9_a_running_attempt_keeps_the_valuation_it_began_with(tmp_path):
    ledger = UsageLedger(tmp_path / LEDGER, Clock())
    ledger.begin("old", "relevance", Purpose.CUSTOMER, valuation())
    ledger.begin("new", "relevance", Purpose.CUSTOMER, valuation(markup="0", revision=2))
    for attempt in ("new", "old"):
        ledger.settle(attempt, "0.01")
    assert [item.points for item in ledger.attempts()] == [Decimal(10), Decimal(8)]
    assert [item.begun.valuation.revision for item in ledger.attempts()] == [1, 2]


def test_acceptance_11_and_13_missing_invalid_and_unsettled_attempts_stay_unclear(tmp_path):
    ledger = UsageLedger(tmp_path / LEDGER, Clock())
    for name, cost in (("zero", 0), ("missing", None), ("negative", -1), ("open", "skip")):
        ledger.begin(name, "help", Purpose.CUSTOMER, valuation())
        if cost != "skip":
            ledger.settle(name, cost)
    statuses = {item.begun.attempt: (item.settled.status if item.settled else None, item.points)
                for item in ledger.attempts()}
    assert statuses == {"zero": (CostStatus.REPORTED, Decimal(0)), "missing": (CostStatus.MISSING, None),
                        "negative": (CostStatus.INVALID, None), "open": (None, None)}
    summary = summarize(ledger.attempts(), START - timedelta(days=1), START + timedelta(days=1), BERLIN)
    assert summary.points == 0 and summary.counted == 4 and summary.unclear == 3 and not summary.complete
    # A result proven later is added once.
    ledger.settle("open", 0.01)
    assert summarize(ledger.attempts(), START, START + timedelta(days=1), BERLIN).unclear == 2


def test_an_append_torn_by_a_crash_is_ignored_and_never_continued(tmp_path):
    path = tmp_path / LEDGER
    ledger = UsageLedger(path, Clock())
    ledger.begin("a", "relevance", Purpose.CUSTOMER, valuation())
    with path.open("a", encoding="utf-8") as stream:
        stream.write('{"type": "settled", "attempt": "a", "at"')
    restarted = UsageLedger(path, Clock())
    assert restarted.attempts()[0].settled is None  # still unclear, no invented cost
    restarted.settle("a", 0.01)
    assert UsageLedger(path, Clock()).attempts()[0].points == Decimal(10)
    assert path.read_text(encoding="utf-8").count("\n") == 2
    assert (tmp_path / (LEDGER + ".torn")).read_text(encoding="utf-8") == '{"type": "settled", "attempt": "a", "at"\n'


def test_acceptance_12_duplicated_lines_count_an_attempt_once(tmp_path):
    path = tmp_path / LEDGER
    ledger = UsageLedger(path, Clock())
    ledger.begin("a", "relevance", Purpose.CUSTOMER, valuation())
    ledger.settle("a", 0.01)
    lines = path.read_text(encoding="utf-8").splitlines()
    stray = lines[1].replace('"attempt": "a"', '"attempt": "z"')
    path.write_text("\n".join([lines[0], lines[0], lines[1], lines[1], stray]) + "\n", encoding="utf-8")
    [attempt] = UsageLedger(path, Clock()).attempts()
    assert attempt.points == Decimal(10)


def test_a_refused_connection_is_neither_used_nor_unclear_and_settles_once(tmp_path):
    ledger = UsageLedger(tmp_path / LEDGER, Clock())
    ledger.not_sent("unknown")
    ledger.begin("a", "relevance", Purpose.CUSTOMER, valuation())
    ledger.not_sent("a")
    ledger.not_sent("a")
    ledger.settle("a", 0.01)
    [attempt] = ledger.attempts()
    assert attempt.settled is not None and attempt.settled.status is CostStatus.NOT_SENT
    assert attempt.points is None and not attempt.unclear
    summary = summarize(ledger.attempts(), START - timedelta(days=1), START + timedelta(days=1), BERLIN)
    assert summary.points == 0 and summary.complete and summary.counted == 1


def test_a_damaged_line_in_the_middle_is_reported_not_guessed(tmp_path):
    path = tmp_path / LEDGER
    UsageLedger(path, Clock()).begin("a", "relevance", Purpose.CUSTOMER, valuation())
    path.write_text("not json\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(UsageCorrupt, match="Zeile 1"):
        UsageLedger(path, Clock())
    path.write_text("[]\n" + path.read_text(encoding="utf-8").split("\n", 1)[1], encoding="utf-8")
    with pytest.raises(UsageCorrupt):
        UsageLedger(path, Clock())


def test_acceptance_10_days_follow_the_local_time_zone_across_daylight_saving(tmp_path):
    clock = Clock()
    ledger = UsageLedger(tmp_path / LEDGER, clock)
    # 2027-03-28: Berlin switches to summer time; 22:30 UTC on the 27th is 23:30 local, 22:30 UTC on the 28th 00:30.
    for name, moment in (("before", datetime(2027, 3, 27, 22, 30, tzinfo=UTC)),
                         ("after", datetime(2027, 3, 28, 22, 30, tzinfo=UTC))):
        clock.now = moment
        ledger.begin(name, "relevance", Purpose.CUSTOMER, valuation(markup="0"))
        ledger.settle(name, 0.01)
    summary = summarize(ledger.attempts(), datetime(2027, 3, 1, tzinfo=UTC), datetime(2027, 4, 1, tzinfo=UTC),
                        BERLIN)
    assert {day.isoformat(): value for day, value in summary.by_day.items()} == {
        "2027-03-27": Decimal(8), "2027-03-29": Decimal(8)}
    assert summary.points == Decimal(16) and summary.by_stage == {"relevance": Decimal(16)}
    month = summarize(ledger.attempts(), datetime(2027, 3, 28, tzinfo=UTC), datetime(2027, 4, 1, tzinfo=UTC), BERLIN)
    assert month.counted == 1  # an attempt belongs to the period in which it began, exactly once


def test_operator_maintenance_is_not_customer_usage(tmp_path):
    ledger = UsageLedger(tmp_path / LEDGER, Clock())
    for name, purpose in (("c", Purpose.CUSTOMER), ("o", Purpose.OPERATOR)):
        ledger.begin(name, "relevance", purpose, valuation())
        ledger.settle(name, 0.01)
    window = (START - timedelta(days=1), START + timedelta(days=1), BERLIN)
    assert summarize(ledger.attempts(), *window).points == Decimal(10)
    assert summarize(ledger.attempts(), *window, purpose=None).points == Decimal(20)


def test_an_invalid_mail_reference_is_not_stored(tmp_path):
    ledger = UsageLedger(tmp_path / LEDGER, Clock())
    ledger.begin("a", "relevance", Purpose.CUSTOMER, valuation(), "../etc")
    assert ledger.attempts()[0].begun.mail_id is None


def test_recording_starts_with_the_first_attempt(tmp_path):
    clock = Clock()
    ledger = UsageLedger(tmp_path / LEDGER, clock)
    assert ledger.started_at() is None
    ledger.begin("a", "relevance", Purpose.CUSTOMER, valuation())
    assert ledger.started_at() == START


def test_acceptance_18_without_a_valuation_nothing_is_recorded_or_invented(tmp_path):
    clock = Clock()
    meter = UsageMeter(tmp_path, clock)
    assert not meter.begin("a", "relevance") and meter.ledger.attempts() == []
    meter.settle("a", 0.01)
    assert not (tmp_path / LEDGER).exists()


def test_the_meter_binds_the_valuation_valid_when_the_attempt_begins(tmp_path):
    clock = Clock()
    meter = UsageMeter(tmp_path, clock)
    meter.valuations.add(Decimal("1.25"), Decimal("25"), "operator-cli", START)
    assert meter.begin("a", "relevance", MAIL)
    clock.now = START + timedelta(hours=1)
    meter.valuations.add(Decimal("1.25"), Decimal("0"), "operator-cli", clock.now)
    with operator_purpose():
        assert PURPOSE.get() is Purpose.OPERATOR and meter.begin("b", "selftest")
    assert PURPOSE.get() is Purpose.CUSTOMER
    for attempt in ("a", "b"):
        meter.settle(attempt, 0.01)
    assert [(item.points, item.begun.purpose) for item in meter.ledger.attempts()] == [
        (Decimal(10), Purpose.CUSTOMER), (Decimal(8), Purpose.OPERATOR)]


def test_valuation_revisions_are_append_only_and_checked(tmp_path):
    valuations = Valuations(tmp_path)
    first = valuations.add(Decimal("1.25"), Decimal("25"), "operator-cli", START)
    with pytest.raises(ValuationError, match="nach dem letzten"):
        valuations.add(Decimal("1.1"), Decimal("0"), "operator-cli", START)
    with pytest.raises(ValuationError, match="positiv"):
        valuations.add(Decimal("0"), Decimal("0"), "operator-cli", START + timedelta(seconds=1))
    second = valuations.add(Decimal("1.1"), Decimal("10"), "operator-cli", START + timedelta(days=1))
    assert Valuations(tmp_path).revisions() == [first, second] and second.revision == 2
    assert valuations.revisions() == [first, second]  # unchanged file: served from the cache


def test_an_unreadable_valuation_file_stops_recording_loudly(tmp_path):
    (tmp_path / "valuations.json").write_text("{", encoding="utf-8")
    with pytest.raises(ValuationError, match="nicht lesbar"):
        Valuations(tmp_path).revisions()
    valuations = Valuations(tmp_path)
    (tmp_path / "valuations.json").unlink()
    assert valuations.revisions() == []
