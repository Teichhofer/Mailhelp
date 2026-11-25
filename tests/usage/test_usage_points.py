"""8.7 §5: points from reported provider costs (Abnahme 8, 10 and 11); synthetic values only."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from mailhelp.usage.points import CostStatus, Valuation, current, display, points, reported_cost, total

START = datetime(2026, 12, 1, tzinfo=UTC)


def valuation(rate: str = "1.25", markup: str = "25", revision: int = 1, valid_from: datetime = START) -> Valuation:
    return Valuation(revision=revision, usd_per_eur=Decimal(rate), markup_percent=Decimal(markup),
                     valid_from=valid_from, actor="operator-cli")


def test_acceptance_8_one_cent_is_ten_points_with_markup_and_eight_without():
    assert points(Decimal("0.01"), valuation()) == Decimal(10)
    assert points(Decimal("0.01"), valuation(markup="0")) == Decimal(8)


def test_acceptance_10_many_tiny_amounts_sum_precisely_and_only_the_display_rounds():
    tiny = points(Decimal("0.0000001"), valuation(markup="0"))  # 0.00008 points each
    assert tiny == Decimal("0.00008") and display(tiny) == "< 0,01 Punkte"
    assert total([tiny] * 125_000) == Decimal(10)
    assert display(Decimal("0.015")) == "0,02 Punkte" and display(Decimal("0.005")) == "< 0,01 Punkte"
    assert display(Decimal("0.01")) == "0,01 Punkte"
    assert display(Decimal("1234.565")) == "1.234,57 Punkte"
    assert display(Decimal("1234.565"), english=True) == "1,234.57 points"
    assert display(Decimal("0.001"), english=True) == "< 0.01 points"
    assert display(Decimal(0)) == "0,00 Punkte"


def test_a_third_of_a_cent_keeps_its_precision():
    value = points(Decimal("0.01"), valuation(rate="3", markup="0"))
    assert str(value).startswith("3.333333333333333333333333333") and display(value) == "3,33 Punkte"


@pytest.mark.parametrize(("raw", "expected"), [
    (0, (CostStatus.REPORTED, Decimal(0))),
    ("0", (CostStatus.REPORTED, Decimal(0))),
    (0.1, (CostStatus.REPORTED, Decimal("0.1"))),
    (" 0.002 ", (CostStatus.REPORTED, Decimal("0.002"))),
    (3, (CostStatus.REPORTED, Decimal(3))),
    (None, (CostStatus.MISSING, None)),
    (-0.01, (CostStatus.INVALID, None)),
    (float("nan"), (CostStatus.INVALID, None)),
    (float("inf"), (CostStatus.INVALID, None)),
    ("Infinity", (CostStatus.INVALID, None)),
    ("abc", (CostStatus.INVALID, None)),
    (True, (CostStatus.INVALID, None)),
    ({"cost": 1}, (CostStatus.INVALID, None)),
])
def test_acceptance_11_zero_stays_zero_and_doubtful_values_are_never_free(raw, expected):
    assert reported_cost(raw) == expected


def test_a_float_cost_is_read_as_its_decimal_text_not_its_binary_value():
    assert reported_cost(0.1)[1] == Decimal("0.1") != Decimal(0.1)


@pytest.mark.parametrize("changes", [{"usd_per_eur": Decimal(0)}, {"usd_per_eur": Decimal("NaN")},
                                     {"markup_percent": Decimal(-1)}, {"markup_percent": Decimal("Infinity")},
                                     {"valid_from": datetime(2026, 12, 1)}, {"revision": 0}])
def test_an_invalid_valuation_is_refused(changes):
    values = valuation().model_dump() | changes
    with pytest.raises(ValidationError):
        Valuation.model_validate(values)


def test_the_valuation_valid_at_a_moment_is_the_newest_that_began():
    first, second = valuation(), valuation(rate="1.1", revision=2, valid_from=START + timedelta(days=1))
    assert current([], START) is None and current([second], START) is None
    assert current([first, second], START + timedelta(hours=1)) is first
    assert current([second, first], START + timedelta(days=2)) is second
