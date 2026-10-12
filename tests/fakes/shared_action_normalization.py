"""Shared synthetic fixtures and doubles; no test-module dependencies."""



from mailhelp.action_normalization import (
    MailDateContext,
)
from mailhelp.models import ExtractedEvent, ExtractedTask


def context(**changes):
    values = {
        "date_context_status": "valid",
        "date_header_parsed": "2026-09-18T12:00:00+02:00",
        "imap_received_at": "2026-09-18T10:01:00+00:00",
        "user_timezone": "Europe/Berlin",
    }
    values.update(changes)
    return MailDateContext(**values)

def event(**changes):
    values = {
        "title": "Sitzung", "description": None, "evidence": "synthetischer Beleg",
        "date_text": "22.09.2026", "time_text": None, "end_time_text": None,
        "timezone_offset_text": None,
        "time_requirement": "all_day",
        "location": None, "video_link": None, "responsibility": "user",
        "certainty": "certain", "classification": "new",
    }
    values.update(changes)
    return ExtractedEvent(**values)

def task(**changes):
    values = {"title": "Aufgabe", "description": "", "evidence": "Beleg",
              "responsibility": "user", "certainty": "certain", "classification": "new",
              "due_text": "2026-09-22"}
    values.update(changes)
    return ExtractedTask(**values)

def reminder(day, start, end, offset):
    return event(date_text=day, time_text=start, end_time_text=end,
                 timezone_offset_text=offset, time_requirement="timed",
                 evidence=f"Erinnerung: Austausch am {day}, {start} Uhr - {end} Uhr ({offset})")
