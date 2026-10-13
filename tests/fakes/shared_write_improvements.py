"""Shared synthetic fixtures and doubles; no test-module dependencies."""








from shared_core import proposal


def event(**changes):
    changes.setdefault("target", "calendar")
    return proposal(kind="event", start="2026-05-10T10:00:00+00:00",
                    end="2026-05-10T11:00:00+00:00", **changes)
