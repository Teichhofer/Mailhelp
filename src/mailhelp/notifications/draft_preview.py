"""Plain-text draft results; notification queues retain only their versioned references."""
from typing import Any

STATUSES = {
    "saved": "Als Entwurf im Postfach abgelegt",
    "editing": "Antwortentwurf noch nicht im Postfach abgelegt; bitte in Mailhelp prüfen",
    "uncertain": "Schreibresultat unklar; vor Wiederholung mit dem Postfach abgleichen",
    "simulated": "Entwurfsablage im Testmodus simuliert",
}


def visible(draft: dict[str, Any]) -> bool:
    return bool(draft.get("auto") and draft.get("text") and draft.get("status") in STATUSES)


def summary(draft: dict[str, Any]) -> str:
    return STATUSES[draft["status"]] + ":\n" + draft["text"]
