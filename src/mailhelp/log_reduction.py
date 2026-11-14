"""Bounded in-process aggregation without raw mail content or credentials."""
import hashlib
import json
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any


class LogReduction:
    def __init__(self) -> None:
        self.seen: OrderedDict[str, tuple[float, int, str]] = OrderedDict()

    def select(self, level: str, module: str, event: str, context: Mapping[str, Any],
               now: float, verbose: bool) -> tuple[str, dict[str, Any]] | None:
        if verbose:
            return event, dict(context)
        if event == "poll_started":
            return None
        if event == "request" and int(context.get("status", 0)) < 400 and context.get("duration_ms", 0) <= 1000:
            return None
        discovery = event == "messages_discovered"
        error = level in {"ERROR", "CRITICAL"} or "stacktrace" in context
        if not discovery and not error:
            return event, dict(context)
        identity = ([module, event, context.get("account_id"), context.get("folder")] if discovery else
                    [module, event, context.get("mail_id"), context.get("state_name"), context.get("stage"),
                     context.get("error"), context.get("stacktrace")])
        key = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()
        value = json.dumps(context, sort_keys=True, default=str) if discovery else ""
        previous = self.seen.pop(key, None)
        stamp, count, old_value = previous or (now, 0, value)
        count += 1
        emit = previous is None or now - stamp >= (3600 if discovery else 900) or value != old_value
        self.seen[key] = (now if emit else stamp, count, value)
        if len(self.seen) > 4096:
            self.seen.popitem(last=False)
        if not emit:
            return None
        if not discovery and previous is not None:
            return "repeated", {"original_event": event, "fingerprint": key, "count": count,
                                "mail_id": context.get("mail_id"), "stage": context.get("stage")}
        return event, dict(context)
