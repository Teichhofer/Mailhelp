"""6.1.8: the slowest runs of one processing step (or of whole mails) – read only, like the call list."""
from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from ..domain.processing import ProcessingStage
from ..formatting import duration_text, format_datetime_local
from ..review.views import STAGE_LABELS
from ..runtime.stage_metrics import TOTAL
from .calls_page import PAGE_SIZE, describe, filters
from .pages import e, page_head

STAGES = {stage.value for stage in ProcessingStage} | {TOTAL}
SORTS = {"duration": "Dauer", "time": "Zeit"}
OUTCOMES = {"completed": "abgeschlossen", "deferred": "zurückgestellt", "failed": "fehlgeschlagen"}


def title(stage: str) -> str:
    return "Durchlaufzeit je Mail" if stage == TOTAL else f"Schritt „{STAGE_LABELS.get(stage, stage)}“"


def _link(params: dict[str, Any], **extra: str) -> str:
    return "/auswertung/schritte?" + urlencode({**filters(params), **extra})


def _row(row: dict[str, Any], zone: str, subject: Callable[[str], str | None], total: bool) -> str:
    mail = "—"
    if row.get("mail_id"):
        name = subject(row["mail_id"])
        mail = (f'<a href="/mail/{e(row["mail_id"])}">{e(name)}</a>' if name is not None
                else "Mail nicht mehr gespeichert")
    cells = [e(format_datetime_local(datetime.fromisoformat(row["started_at"]), zone)),
             e(duration_text(row["duration_ms"] / 1000, precise=True)),
             e(duration_text(row["llm_ms"] / 1000, precise=True))]
    if total:
        cells.append(e(duration_text(row["waiting_ms"] / 1000)))
    else:
        cells.append(e(OUTCOMES[row["outcome"]] + (" · fortgesetzt" if row["resumed"] else "")))
    cells.append(mail)
    return "<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"


def stage_page(stage: str, params: dict[str, Any], sort: str, page: int, steps: dict[str, Any], zone: str,
               subject: Callable[[str], str | None], labels: dict[str, str]) -> str:
    total = stage == TOTAL
    rows = [row for row in (steps["totals"] if total else steps["records"]) if row["stage"] == stage]
    rows.sort(key=(lambda row: (-row["duration_ms"], row["started_at"])) if sort == "duration"
              else (lambda row: row["started_at"]), reverse=sort == "time")
    back = "/auswertung" + ("?" + urlencode(filters(params)) if filters(params) else "")
    explanation = ("Zeit vom ersten bis zum letzten Schritt einer Mail ohne die Wartezeit auf Entscheidungen; "
                   "die Wartezeit steht daneben." if total else
                   "Dauer dieses Schritts je Mail; „davon KI“ ist die Zeit der KI-Aufrufe in diesem Schritt.")
    body = (page_head(title(stage), "Auswertung", back=(back, "Zurück zur Auswertung"))
            + f'<p class="meta">{e(describe(params, labels))}</p>'
            f'<section class="card calls-explanation"><p>{e(explanation)}</p></section>'
            '<p class="calls-pages">Sortierung: ' + " · ".join(
                (f"<strong>{label}</strong>" if key == sort else f'<a href="{e(_link(params, stage=stage, sort=key))}">'
                 f"{label}</a>") for key, label in SORTS.items()) + "</p>")
    if not rows:
        return body + '<p class="empty">Für diese Auswahl gibt es keine gemessenen Durchläufe.</p>'
    count = max(1, math.ceil(len(rows) / PAGE_SIZE))
    page = min(page, count)
    navigation = [f"{len(rows)} Durchläufe · Seite {page} von {count}"]
    if page > 1:
        navigation.append(f'<a href="{e(_link(params, stage=stage, sort=sort, page=str(page - 1)))}">'
                          "‹ Vorherige Seite</a>")
    if page < count:
        navigation.append(f'<a href="{e(_link(params, stage=stage, sort=sort, page=str(page + 1)))}">'
                          "Nächste Seite ›</a>")
    pages = f'<p class="calls-pages">{" · ".join(navigation)}</p>'
    header = ("Beginn", "Dauer", "davon KI", "Wartezeit" if total else "Ergebnis", "Mail")
    shown = rows[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    table = ('<div class="table-scroll" tabindex="0" role="region" aria-label="Durchläufe"><table class="calls-table">'
             "<thead><tr>" + "".join(f'<th scope="col">{name}</th>' for name in header) + "</tr></thead><tbody>"
             + "".join(_row(row, zone, subject, total) for row in shown) + "</tbody></table></div>")
    return body + pages + table + pages


__all__ = ["SORTS", "STAGES", "stage_page", "title"]
