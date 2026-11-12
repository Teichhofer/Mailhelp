import math
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from mailhelp.formatting import duration_text, format_datetime_local


def test_format_datetime_local_with_str_and_zoneinfo():
    dt = datetime(2026, 10, 12, 14, 30, tzinfo=UTC)
    # Zone as str
    result_str = format_datetime_local(dt, "Europe/Berlin")
    assert result_str == "12.10.2026, 16:30 Uhr"

    # Zone as ZoneInfo
    result_zone = format_datetime_local(dt, ZoneInfo("Europe/Berlin"))
    assert result_zone == "12.10.2026, 16:30 Uhr"



@pytest.mark.parametrize(("seconds", "precise", "text"), [
    (0, False, "0,0 s"), (0.85, True, "0,85 s"), (42.34, False, "42,3 s"), (59.94, False, "59,9 s"),
    (59.96, False, "1 Min."), (59.996, True, "1 Min."), (59.994, True, "59,99 s"), (60, False, "1 Min."),
    (252, False, "4 Min. 12 s"), (300.4, False, "5 Min."), (3599.4, False, "59 Min. 59 s"),
    (3599.6, False, "1 Std."), (8100, False, "2 Std. 15 Min."), (75_240, False, "20 Std. 54 Min."),
    (86_369, False, "23 Std. 59 Min."), (86_371, False, "1 Tag"), (86_400, False, "1 Tag"),
    (100_800, False, "1 Tag 4 Std."), (273_600, False, "3 Tage 4 Std."), (259_200, False, "3 Tage"),
    (1_000_000, False, "11 Tage 14 Std."),
])
def test_durations_use_the_largest_fitting_unit_after_rounding(seconds, precise, text):
    assert duration_text(seconds, precise=precise) == text


@pytest.mark.parametrize("value", [-0.1, math.inf, math.nan])
def test_negative_or_infinite_durations_are_rejected(value):
    with pytest.raises(ValueError):
        duration_text(value)
