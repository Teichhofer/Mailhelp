"""Calendar lookup, duplicate matching, merge payloads and event updates."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from ..adapter import uncertain_write
from ..models import CalendarDuplicateDecision, Proposal, ProposalKind
from .contracts import CalendarEventResponse, CalendarListResponse, CalendarOverlapEvent, PreparedWrite, validation_path


def _now(configured_timezone: str | None) -> datetime:
    """Current local time for change notes; separate so tests can fix it."""
    return datetime.now(ZoneInfo(configured_timezone or "UTC"))


class CalendarOperations:
    def _reconcile_calendar(self, key: str) -> dict[str, Any] | None:
        response = self.policy.run(lambda: self._get(f"/calendars/{self.target}/events", {"privateExtendedProperty": f"mailhelp_key={key}"}))
        try: items = CalendarListResponse.model_validate(response.json()).items
        except (ValueError, ValidationError) as exc: raise ValueError(f"Google Calendar events: ungültige Antwort am Schlüsselpfad {validation_path(exc)}") from exc
        return items[0].model_dump() if items else None


    def _prepare_calendar(self, proposal: Proposal, key: str) -> PreparedWrite:
        if proposal.kind != ProposalKind.EVENT: raise ValueError("Kalender akzeptiert nur Termine")
        if proposal.target_event_id is not None:
            body = self._calendar_event_body(proposal, key)
            if proposal.is_cancellation:
                body["status"] = "cancelled"
            return PreparedWrite(lambda: self._update_calendar_event(
                proposal.target_event_id, body, key, proposal, proposal.time_changes))
        duplicate = (None if proposal.explicit_duplicate_create_confirmed_version == proposal.version
                     else self._matching_calendar_event(proposal))
        if duplicate is not None:
            existing, decision = duplicate
            changes, interval = self._time_changes(proposal, existing)
            if decision.missing_fields or changes:
                body = self._calendar_merge_body(proposal, key, existing, decision)
                if changes:
                    # The user confirmed exactly these times; the existing
                    # event takes them over and records what changed when.
                    body.update(interval)
                    note = (f"[Mailhelp {_now(self.calendar_timezone):%d.%m.%Y %H:%M}] "
                            f"Zeit aktualisiert: {'; '.join(changes)} "
                            f"(bestätigte Vorschlagsversion {proposal.version}).")
                    base = body.get("description", existing.description)
                    body["description"] = f"{base}\n\n{note}" if base else note
                return PreparedWrite(lambda: self._update_calendar_event(
                    existing.id, body, key, proposal, changes))
            return PreparedWrite(lambda: {"id": existing.id, "htmlLink": existing.htmlLink,
                    "operation": "duplicate_skipped"}, requires_write=False)
        url, body = f"/calendars/{self.target}/events", self._calendar_event_body(proposal, key)
        return PreparedWrite(lambda: self._create_prepared(proposal, key, url, body))

    def fetch_events_in_window(
        self, start: datetime | date, end: datetime | date, *, strict: bool = False
    ) -> list[CalendarOverlapEvent]:
        """Fetch existing Google Calendar events in the given window with caching and fallback."""
        if self.service != "google_calendar":
            return []
        if isinstance(start, date) and not isinstance(start, datetime):
            time_min = datetime.combine(start, datetime.min.time(), UTC).isoformat()
        else:
            time_min = start.isoformat()
        if isinstance(end, date) and not isinstance(end, datetime):
            time_max = datetime.combine(end, datetime.min.time(), UTC).isoformat()
        else:
            time_max = end.isoformat()

        cache_key = (self.service, self.target, time_min, time_max)
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        params = {
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": "true",
            "maxResults": "50",
        }
        events: list[CalendarOverlapEvent] = []
        seen_tokens: set[str] = set()
        try:
            while True:
                response = self.policy.run(lambda: self._get(
                    f"/calendars/{self.target}/events", params
                ))
                page = response.json()
                raw_items = page.get("items", [])
                if not isinstance(raw_items, list):
                    break
                items = [CalendarOverlapEvent.model_validate(item) for item in raw_items]
                events.extend(items)
                next_token = page.get("nextPageToken")
                if next_token is None or not isinstance(next_token, str) or next_token in seen_tokens:
                    break
                seen_tokens.add(next_token)
                params["pageToken"] = next_token
            self._set_cached(cache_key, events)
            return events
        except Exception as exc:
            if strict:
                raise
            self.logger.event("WARNING", self.service, "fetch_events_failed", error=str(exc))
            return []


    def _matching_calendar_event(self, proposal: Proposal) -> tuple[CalendarOverlapEvent, CalendarDuplicateDecision] | None:
        if self.service != "google_calendar" or self.calendar_matcher is None:
            return None
        assert proposal.start is not None and proposal.end is not None
        if proposal.all_day:
            time_min = datetime.combine(proposal.start, datetime.min.time(), UTC).isoformat()
            time_max = datetime.combine(proposal.end, datetime.min.time(), UTC).isoformat()
        else:
            assert isinstance(proposal.start, datetime) and isinstance(proposal.end, datetime)
            time_min, time_max = proposal.start.isoformat(), proposal.end.isoformat()
        params = {"timeMin": time_min, "timeMax": time_max, "singleEvents": "true",
                  "maxResults": "50"}
        seen_tokens: set[str] = set()
        while True:
            response = self.policy.run(lambda: self._get(
                f"/calendars/{self.target}/events", params,
            ))
            try:
                page = response.json()
                raw_items = page.get("items", [])
                if not isinstance(raw_items, list):
                    raise ValueError("items")
                items = [CalendarOverlapEvent.model_validate(item) for item in raw_items]
                next_token = page.get("nextPageToken")
                if next_token is not None:
                    if not isinstance(next_token, str) or not next_token or next_token in seen_tokens:
                        raise ValueError("nextPageToken")
                    seen_tokens.add(next_token)
            except (AttributeError, ValueError, ValidationError) as exc:
                raise ValueError(f"Google Calendar events: ungültige Antwort am Schlüsselpfad {validation_path(exc)}") from exc
            for item in items:
                safe = item.model_dump(mode="json", exclude={"htmlLink"})
                _call_id, decision = self.calendar_matcher(proposal, safe)
                if decision.same_event:
                    return item, decision
            if next_token is None:
                return None
            params["pageToken"] = next_token


    def _calendar_merge_body(self, proposal: Proposal, key: str,
                             existing: CalendarOverlapEvent,
                             decision: CalendarDuplicateDecision) -> dict[str, Any]:
        body: dict[str, Any] = {"extendedProperties": {"private": {"mailhelp_key": key}}}
        if "description" in decision.missing_fields and proposal.description:
            body["description"] = (f"{existing.description}\n\n{proposal.description}"
                                   if existing.description else proposal.description)
        if "location" in decision.missing_fields and proposal.location and not existing.location:
            body["location"] = proposal.location
        if "video_link" in decision.missing_fields and proposal.video_link is not None:
            link = str(proposal.video_link)
            addition = f"[Mailhelp-Videolink]\n{link}"
            body["description"] = (f"{body.get('description', existing.description)}\n\n{addition}"
                                   if body.get("description", existing.description) else addition)
        return body


    def _time_changes(self, proposal: Proposal,
                      existing: CalendarOverlapEvent) -> tuple[list[str], dict[str, Any]]:
        """Compare start and end deterministically; the LLM only decides identity."""
        validated = Proposal.model_validate(proposal.model_dump())
        interval = (self._all_day_interval(validated) if validated.all_day
                    else self._timed_interval(validated))
        zone = ZoneInfo(self.calendar_timezone or "UTC")

        def parse(raw: dict[str, str]) -> date | datetime | None:
            if "dateTime" in raw:
                return datetime.fromisoformat(raw["dateTime"])
            return date.fromisoformat(raw["date"]) if "date" in raw else None

        def display(value: date | datetime, end: bool) -> str:
            if isinstance(value, datetime):
                return f"{value.astimezone(zone):%d.%m.%Y %H:%M} Uhr"
            # Google stores the exclusive day after an all-day event.
            return f"{value - timedelta(days=1) if end else value:%d.%m.%Y}"

        changes = []
        for label, old_raw, new in (("Beginn", existing.start, validated.start),
                                    ("Ende", existing.end, validated.end)):
            old = parse(old_raw)
            # An unknown existing time cannot be compared and is left alone.
            if old is not None and not (type(old) is type(new) and old == new):
                changes.append(f"{label} {display(old, label == 'Ende')} → "
                               f"{display(new, label == 'Ende')}")
        return changes, interval


    def _update_calendar_event(self, existing_id: str, body: dict[str, Any], key: str,
                               proposal: Proposal,
                               time_changes: list[str] | None = None) -> dict[str, Any]:
        url = f"/calendars/{self.target}/events/{existing_id}"
        response = uncertain_write(lambda: self._patch(url, body, key))
        try:
            result = CalendarEventResponse.model_validate(response.json()).model_dump()
        except (ValueError, ValidationError) as exc:
            raise ValueError(f"google_calendar: ungültige Antwort am Schlüsselpfad {validation_path(exc)}") from exc
        self.logger.event("INFO", self.service, "duplicate_updated", call_id=key,
                          mail_id=proposal.source_mail_id, proposal_id=proposal.id,
                          existing_event_id=existing_id, time_changed=bool(time_changes))
        self._read_cache.clear()
        return {**result, "operation": "duplicate_updated", "time_changes": time_changes or []}


    def _calendar_event_body(self, proposal: Proposal, key: str) -> dict[str, Any]:
        # Revalidate at the external trust boundary; model_copy() can otherwise
        # construct an inconsistent proposal without running model validators.
        validated = Proposal.model_validate(proposal.model_dump())
        interval = self._all_day_interval(validated) if validated.all_day else self._timed_interval(validated)
        description = validated.description
        if validated.video_link is not None:
            video_section = f"[Mailhelp-Videolink]\n{validated.video_link}"
            description = f"{description}\n\n{video_section}" if description else video_section
        body = {"summary": validated.title, "description": description, **interval,
                "extendedProperties": {"private": {"mailhelp_key": key}}}
        if validated.location is not None:
            body["location"] = validated.location
        return body


    @staticmethod
    def _all_day_interval(proposal: Proposal) -> dict[str, Any]:
        # Google interprets end.date as exclusive: a one-day event therefore
        # has end equal to the calendar day after start.
        return {"start": {"date": proposal.start.isoformat()}, "end": {"date": proposal.end.isoformat()}}


    def _timed_interval(self, proposal: Proposal) -> dict[str, Any]:
        # dateTime already identifies the instant through its mandatory UTC
        # offset.  Supplying the configured calendar zone as well could make a
        # different zone appear authoritative and reinterpret the wall time.
        return {
            "start": {"dateTime": proposal.start.isoformat()},
            "end": {"dateTime": proposal.end.isoformat()},
        }

