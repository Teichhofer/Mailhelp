"""Synthetic series and version-bound review commands shared by all channels."""
from datetime import date, datetime

from mailhelp.models import KnownTemporalFacts
from mailhelp.review.series import members
from tests.fakes.shared_review import EVENT, command
from tests.fakes.shared_telegram_dialog import proposal


def series(count=3, complete=False):
    return [proposal(id=f"p{i}", title="Sitzung", location="Sitzungssaal", **({**EVENT,
        "start": datetime.fromisoformat(f"2027-{i+1:02d}-23T19:00:00+01:00"),
        "end": datetime.fromisoformat(f"2027-{i+1:02d}-23T22:00:00+01:00")} if complete else {
        "kind": "event", "start": None, "end": None, "target": "calendar",
        "status": "needs_clarification", "open_questions": ["Wann beginnt der Termin?", "Wann endet der Termin?"],
        "known_temporal_facts": KnownTemporalFacts(date=date(2027, i+1, 23)), "meeting_mode": "in_person"}))
            for i in range(count)]

def batch(kind, items, **extra):
    return command(kind, proposal_id=items[0].id, version=items[0].version, members=members(items), **extra)
