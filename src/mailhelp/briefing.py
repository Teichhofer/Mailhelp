"""Daily briefing: read-only aggregation once per local day, restart-safe delivery.

Telegram receives the briefing text (the chat already receives mail summaries);
Web-Push channels decide themselves to show only a neutral hint on lock screens.
Each channel is attempted at most once per day: a crash during a delivery leaves
it as "uncertain" and it is not repeated, so the user never gets duplicates.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# Telegram accepts at most 4096 characters per message.
MAX_ITEMS, MAX_LENGTH = 10, 4000


def _plural(count, one, many):
    return f"{count} {one if count == 1 else many}"


def _limited(lines):
    shown = [f"• {line}" for line in lines[:MAX_ITEMS]]
    if len(lines) > MAX_ITEMS:
        shown.append(f"• … und {len(lines) - MAX_ITEMS} weitere")
    return shown


class DailyBriefingService:
    def __init__(self, store, settings, zone, calendar, tasks, views, channels,
                 clock=lambda: datetime.now(timezone.utc)):
        self.store, self.settings, self.zone = store, settings, ZoneInfo(zone)
        self.calendar, self.tasks, self.views = calendar, tasks, views
        self.channels, self.clock = channels, clock

    def _start(self, item):
        """Local start time of an event; all-day events come first."""
        if "dateTime" in item.start:
            moment = datetime.fromisoformat(item.start["dateTime"]).astimezone(self.zone)
            return moment.strftime("%H:%M"), f"{moment:%H:%M} Uhr"
        return "", "ganztägig"

    def build(self, now):
        lines = ["Guten Morgen! ☀️"]
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if self.settings.include_calendar:
            try:
                events = self.calendar.fetch_events_in_window(start, start + timedelta(days=1), strict=True)
            except Exception:
                lines.append("📅 (Kalender aktuell nicht erreichbar)")
            else:
                entries = sorted((self._start(item), item.summary or "Ohne Titel") for item in events)
                lines.append(f"📅 Heute {_plural(len(entries), 'Termin', 'Termine')}"
                             + (":" if entries else "."))
                lines.extend(_limited([f"{label}: {summary}" for (_, label), summary in entries]))
        if self.settings.include_tasks:
            try:
                due = [item.content for item in self.tasks.fetch_active_tasks()
                       if item.due and str(item.due.get("date", "9999"))[:10] <= now.date().isoformat()]
            except Exception:
                lines.append("✅ (Aufgaben aktuell nicht erreichbar)")
            else:
                lines.append(f"✅ {_plural(len(due), 'Aufgabe', 'Aufgaben')} fällig" + (":" if due else "."))
                lines.extend(_limited(due))
        if self.settings.include_open:
            overview = self.views.overview()
            count = len(overview.open) + len(overview.relevance)
            lines.append(f"✉️ {_plural(count, 'Entscheidung wartet', 'Entscheidungen warten')} auf dich.")
        text = "\n".join(lines)
        return text if len(text) <= MAX_LENGTH else text[:MAX_LENGTH - 1] + "…"

    def tick(self):
        """Called by one scheduler thread; network access happens without the store lock."""
        now = self.clock().astimezone(self.zone)
        if not self.settings.enabled or now.strftime("%H:%M") < self.settings.time:
            return
        day = now.date().isoformat()
        state = self.store.load("daily-briefing", {"day": day, "channels": {}})
        if state["day"] != day:
            state = {"day": day, "channels": {}}
        pending = [name for name in self.channels if name not in state["channels"]]
        if not pending:
            return
        text = self.build(now)
        self.store.save("briefing-latest", {"day": day, "text": text})
        for name in pending:
            state["channels"][name] = "uncertain"
            self.store.save("daily-briefing", state)
            try:
                self.channels[name](text)
            except Exception:
                continue
            state["channels"][name] = "sent"
            self.store.save("daily-briefing", state)
