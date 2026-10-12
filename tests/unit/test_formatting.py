from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from mailhelp.formatting import format_datetime_local


def test_format_datetime_local_with_str_and_zoneinfo():
    dt = datetime(2026, 10, 12, 14, 30, tzinfo=UTC)
    # Zone as str
    result_str = format_datetime_local(dt, "Europe/Berlin")
    assert result_str == "12.10.2026, 16:30 Uhr"

    # Zone as ZoneInfo
    result_zone = format_datetime_local(dt, ZoneInfo("Europe/Berlin"))
    assert result_zone == "12.10.2026, 16:30 Uhr"

