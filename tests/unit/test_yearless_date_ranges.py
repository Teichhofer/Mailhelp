"""Regression 7.4: yearless ranges use the existing mail-context year policy."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from mailhelp.proposals.action_normalization import normalize_event
from tests.fakes.shared_action_normalization import context, event


@pytest.mark.parametrize('raw', ['07. bis 08. Januar', '7./8. Januar', '07./08.01.',
                                '28. Januar bis 2. Februar', '28.12. bis 02.01.', '07./08.01'])
def test_yearless_ranges_use_the_next_start_after_the_mail(raw):
    result = normalize_event(event(date_text=raw), context())
    assert result.value is not None
    expected = date(2026, 12, 28) if '12.' in raw else date(2027, 1, 28 if '28.' in raw else 7)
    assert result.value.start == expected
    assert result.temporal_fact.year_source == 'mail_context'


def test_yearless_timed_range_preserves_the_end_day():
    result = normalize_event(event(date_text='07. bis 08. Januar', time_requirement='timed',
                                   time_text='11:30', end_time_text='12:30'), context())
    assert result.value.start == datetime(2027, 1, 7, 11, 30, tzinfo=ZoneInfo('Europe/Berlin'))
    assert result.value.end == datetime(2027, 1, 8, 12, 30, tzinfo=ZoneInfo('Europe/Berlin'))


@pytest.mark.parametrize('status', ['invalid', 'conflicting'])
def test_yearless_ranges_refuse_untrusted_context(status):
    result = normalize_event(event(date_text='07. bis 08. Januar'), context(date_context_status=status))
    assert result.value is None and 'Mail-Datumskontext' in result.question


def test_yearless_ranges_respect_explicit_evidence_and_reject_conflicts():
    result = normalize_event(event(date_text='07. bis 08. Januar', evidence='Tagung im Jahr 2028'), context())
    assert result.value.start == date(2028, 1, 7)
    assert result.temporal_fact.year_source == 'explicit_mail'
    conflict = normalize_event(event(date_text='07. bis 08. Januar', evidence='2027 oder 2028'), context())
    assert conflict.value is None and 'Jahreszahlen' in conflict.question


def test_yearless_range_weekdays_are_checked_after_the_year_is_resolved():
    result = normalize_event(event(date_text='Donnerstag 07. bis Freitag 08. Januar'), context())
    assert result.value.start == date(2027, 1, 7)
    wrong = normalize_event(event(date_text='Freitag 07. bis Samstag 08. Januar'), context())
    assert wrong.value is None and 'Wochentag' in wrong.question


@pytest.mark.parametrize('raw', ['28. bis 29. Februar', '8. bis 7. Januar'])
def test_an_invalid_or_backwards_resolved_range_is_refused(raw):
    result = normalize_event(event(date_text=raw), context())
    assert result.value is None


def test_extra_text_does_not_silently_become_a_complete_date_field():
    result = normalize_event(event(date_text='Unklar: 7. bis 8. Januar'), context())
    assert result.value is None
