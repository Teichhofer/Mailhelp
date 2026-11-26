"""8.7.4: points limit ↔ USD limit of a learning run (Plan Lernen in Punkten §4.1, §5 Rechnung)."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from mailhelp.usage.budget import (
    decimal_of,
    fits,
    limit_float,
    minimum_points,
    parse_points,
    points_to_usd,
    tokens_to_points,
    tokens_to_usd,
    usd_to_points,
)
from mailhelp.usage.points import Valuation
from mailhelp.usage.valuations import SCOPE, UsageMeter, usage_scope


def valuation(rate: str = "1", markup: str = "900") -> Valuation:
    return Valuation(revision=1, usd_per_eur=Decimal(rate), markup_percent=Decimal(markup),
                     valid_from=datetime(2026, 11, 25, tzinfo=UTC), actor="operator")


def test_instance_kunde_100_points_are_one_cent_and_back():
    assert usd_to_points(Decimal("0.01"), valuation()) == 100
    assert points_to_usd(100, valuation()) == Decimal("0.01")
    assert points_to_usd(10_000, valuation()) == 1  # 1 USD = 10,000 points at factor 10


def test_the_usd_limit_is_rounded_down_and_never_worth_more_than_the_points():
    rated = valuation(rate="3", markup="0")  # 1 point = 0.003 USD, never rounded up
    assert points_to_usd(1, rated) == Decimal("0.003")
    odd = valuation(rate="1", markup="200")  # factor 3: 1 point = 0.000333… USD
    assert points_to_usd(1, odd) == Decimal("0.000333333333")
    assert usd_to_points(points_to_usd(1, odd), odd) < 1


@pytest.mark.parametrize("raw, expected", [("1", 1), (" 10000000 ", 10_000_000), ("250", 250)])
def test_points_limits_inside_the_range(raw, expected):
    assert parse_points(raw) == expected


@pytest.mark.parametrize("raw", ["0", "-1", "10000001", "NaN", "1.5", "1e3", "zehn", "", "١٢"])
def test_invalid_points_limits_are_refused(raw):
    with pytest.raises(ValueError):
        parse_points(raw)


def test_estimates_in_points_use_the_one_formula():
    assert tokens_to_usd(40_000, Decimal("0.5")) == Decimal("0.02")
    assert tokens_to_points(40_000, Decimal("0.5"), valuation()) == 200
    assert decimal_of(0.1) == Decimal("0.1")


def test_the_float_limit_never_exceeds_the_decimal_limit():
    exact = Decimal("0.1")  # float(0.1) is slightly above 0.1
    assert Decimal(limit_float(exact)) < exact
    assert limit_float(Decimal("0.5")) == 0.5
    with pytest.raises(ValueError):
        limit_float(Decimal(0))


def test_the_minimum_matches_what_the_start_accepts():
    assert minimum_points(30_000, Decimal("0.5"), valuation()) == 150
    assert fits(150, 30_000, Decimal("0.5"), valuation()) and not fits(149, 30_000, Decimal("0.5"), valuation())
    assert minimum_points(0, Decimal("0.5"), valuation()) == 1
    tiny = valuation(rate="1", markup="1000000000000000")  # a point is worth less than 10⁻¹² USD
    assert not fits(1, 1, Decimal("0.5"), tiny)


def test_one_more_point_when_rounding_down_loses_the_last_fraction():
    # float(0.02) lies above 0.02; the limit float is one step lower and misses the estimate itself.
    assert not fits(200, 40_000, Decimal("0.5"), valuation()) and fits(201, 40_000, Decimal("0.5"), valuation())
    assert minimum_points(40_000, Decimal("0.5"), valuation()) == 201


def test_a_usage_scope_prefixes_the_stage_and_ends_with_its_block(tmp_path):
    meter = UsageMeter(tmp_path)
    meter.valuations.add(Decimal(1), Decimal(900), "operator", datetime(2020, 1, 1, tzinfo=UTC))
    with usage_scope("learning"):
        assert SCOPE.get() == "learning" and meter.begin("a", "relevance")
        assert meter.begin("b", "Ungültig!")
    assert SCOPE.get() is None and meter.begin("c", "relevance")
    assert [item.begun.stage for item in meter.ledger.attempts()] == ["learning.relevance", "learning.other",
                                                                       "relevance"]
    with pytest.raises(ValueError):
        usage_scope("operator").__enter__()
