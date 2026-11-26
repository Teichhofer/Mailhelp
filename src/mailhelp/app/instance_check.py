"""8.7.9 (AP5): the operator's setup check of a customer instance – at the host, before and after setup.

``mailhelp --check-instance`` lists what a customer instance still needs: customer mode, valuation,
the price assumption for learning runs, the finished first setup and an operator access. It reads
files only; it never prints keys, tokens, codes or session ids and changes nothing.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from ..i18n import tr
from ..runtime.instance_mode import FILE, InstanceModeError, load_instance_mode
from ..usage.points import current
from ..usage.valuations import USAGE_DIRECTORY, ValuationError, Valuations
from ..web.auth import SESSIONS, SessionState

OK, MISSING, NOTE = "OK", "FEHLT", "HINWEIS"


def _sessions(state_directory: Path, instance: str, now: datetime) -> tuple[int, int]:
    """Valid operator and customer sessions of this instance; unreadable state counts as none."""
    path = state_directory / f"{SESSIONS}.json"
    try:  # read directly: neither a lock, a directory nor a quarantine copy is created
        state = SessionState.model_validate(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None
    except (OSError, ValueError):
        state = None
    sessions = [item for item in (state.sessions if state else []) if item.expires_at > now
                and item.instance == instance]
    return (sum(item.role == "operator" for item in sessions), sum(item.role == "customer" for item in sessions))


def check_instance(config_directory: Path, state_directory: Path, *, out: Callable[[str], None] = print,
                   clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> int:
    """0 when the instance is ready for customers, 1 when a step is missing, 2 for an invalid operator.yaml."""
    try:
        mode = load_instance_mode(config_directory)
    except InstanceModeError as exc:
        out(tr("{status}: {error}", status=MISSING, error=exc))
        return 2
    if not mode.customer_mode:
        out(tr("{status}: selbst betriebene Instanz ohne Kundenmodus ({file} fehlt oder customer_mode: false); "
               "nichts weiter zu prüfen.", status=NOTE, file=FILE))
        return 0
    now = clock()
    rows: list[tuple[str, str]] = [(OK, tr("Kundenmodus aktiv, Instanz {instance}", instance=mode.instance))]
    try:
        valuation = current(Valuations(state_directory / USAGE_DIRECTORY).revisions(), now)
    except ValuationError:
        valuation = None
    rows.append((OK, tr("Bewertungsstand {revision}: {rate} USD je EUR, Aufschlag {markup} %",
                        revision=valuation.revision, rate=valuation.usd_per_eur, markup=valuation.markup_percent))
                if valuation else
                (MISSING, tr("Bewertungsstand fehlt: mailhelp --set-valuation USD_JE_EUR AUFSCHLAG_PROZENT")))
    price = mode.learning_usd_per_million_tokens
    rows.append((OK, tr("Preisannahme für Lernläufe: {price} USD je Million Tokens", price=price)) if price else
                (MISSING, tr("Preisannahme für Lernläufe fehlt: learning_usd_per_million_tokens in {file}",
                             file=FILE)))
    configured = (config_directory / "config.yaml").exists()
    rows.append((OK, tr("Ersteinrichtung abgeschlossen")) if configured else
                (MISSING, tr("Ersteinrichtung offen: Code aus dem Protokoll des Dienstes im Browser eingeben")))
    operators, customers = _sessions(state_directory, mode.instance, now)
    rows.append((OK, tr("{count} gültige Betreibersitzung(en)", count=operators)) if operators else
                (MISSING, tr("Kein Betreiberzugang: mailhelp --pair --operator am Host")))
    rows.append((NOTE, tr("{count} gültige Kundensitzung(en); Kundenzugang mit mailhelp --pair", count=customers)))
    for status, text in rows:
        out(f"{status}: {text}")
    missing = sum(status == MISSING for status, _text in rows)
    out(tr("Bereit für die Abnahme.") if not missing else tr("{count} Schritt(e) offen.", count=missing))
    return 1 if missing else 0


__all__ = ["check_instance"]
