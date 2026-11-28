"""8.9.5: a booking's arrival and departure form one all-day range.

Regression of the after run of 28.11.2026 (control case K11): the extraction returned date_text
"14.05.2027, Abreise 17.05.2027"; Mailhelp did not recognize the range and asked for the date. Synthetic data only.
"""
from datetime import date

import pytest

from mailhelp.domain.extraction import ExtractedEvent
from mailhelp.proposals.action_normalization import MailDateContext, NormalizationReason, normalize_event

CONTEXT = MailDateContext(date_context_status="valid", date_header_parsed="2027-02-15T09:00:00+01:00",
                          imap_received_at="2027-02-15T09:01:00+01:00", user_timezone="Europe/Berlin")


def booking(date_text):
    return ExtractedEvent.model_validate({
        "title": "Stellplatzbuchung", "description": None, "evidence": "Buchung", "date_text": date_text,
        "time_text": None, "end_time_text": None, "location": "Stellplatz 7", "video_link": None,
        "responsibility": "user", "certainty": "certain", "classification": "new", "time_requirement": "all_day"})


@pytest.mark.parametrize("text", ["14.05.2027, Abreise 17.05.2027", "Anreise 14.05.2027, Abreise 17.05.2027",
                                  "Anreise: 14.05.2027\nAbreise: 17.05.2027", "14.05.2027 bis 17.05.2027"])
def test_regression_arrival_and_departure_are_one_all_day_range(text):
    result = normalize_event(booking(text), CONTEXT)
    assert result.resolved and result.value.all_day
    assert (result.value.start, result.value.end) == (date(2027, 5, 14), date(2027, 5, 18))


def test_a_departure_before_the_arrival_or_an_impossible_day_is_no_range():
    assert normalize_event(booking("17.05.2027, Abreise 14.05.2027"), CONTEXT).reason is not None
    assert normalize_event(booking("31.02.2027, Abreise 03.03.2027"), CONTEXT).reason == (
        NormalizationReason.UNSUPPORTED_DATE)
