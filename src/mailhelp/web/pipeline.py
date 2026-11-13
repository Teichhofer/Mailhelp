"""Computing time per processing step and the pipeline plan of the evaluation page (5.9.10).

Only AI calls are measured. Local steps appear in the plan as "lokal · nicht gemessen": they are
fast and cause no relevant waiting time. A step shows its time as soon as metric rows with its
stage key exist, without a code change. The plan is an ordered HTML list, not SVG, so its text
stays readable at every width and needs neither inline styles nor JavaScript.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..domain.processing import ProcessingStage
from ..formatting import duration_text
from ..review.views import STAGE_LABELS
from .charts import _median, _number, bar_list
from .pages import e

# Event and task extraction run side by side, depending on the detected action.
BRANCH = (ProcessingStage.EVENT_EXTRACTION.value, ProcessingStage.TASK_EXTRACTION.value)


@dataclass(frozen=True)
class StageTime:
    key: str
    label: str
    seconds: float
    calls: int
    # Median of the summed duration per mail; None without calls that name a mail.
    per_mail: float | None

    def share(self, total: float) -> float:
        return self.seconds / total * 100 if total else 0.0


def label(key: str) -> str:
    """German name of a step; unknown keys appear unchanged."""
    return STAGE_LABELS.get(key, key)


def percent(value: float) -> str:
    return _number(value, 1) + " %"


def stage_times(records: list[dict[str, Any]]) -> dict[str, StageTime]:
    """Summed duration, calls and the median per mail of every measured step."""
    seconds: dict[str, float] = {}
    calls: dict[str, int] = {}
    per_mail: dict[str, dict[str, float]] = {}
    for record in records:
        key, value = record["stage"], record["duration_ms"] / 1000
        seconds[key] = seconds.get(key, 0.0) + value
        calls[key] = calls.get(key, 0) + 1
        # Calls without a mail (comparison runs) count in sum and share only.
        if record.get("mail_id"):
            mails = per_mail.setdefault(key, {})
            mails[record["mail_id"]] = mails.get(record["mail_id"], 0.0) + value
    return {key: StageTime(key, label(key), value, calls[key],
                           _median(list(per_mail[key].values())) if key in per_mail else None)
            for key, value in seconds.items()}


def ranking(times: dict[str, StageTime]) -> str:
    """Largest share first, each bar labelled with share and duration."""
    total = sum(item.seconds for item in times.values())
    ordered = sorted(times.values(), key=lambda item: (-item.seconds, item.label))
    rows = [[item.label, percent(item.share(total)), duration_text(item.seconds), _number(item.calls, 0),
             duration_text(item.per_mail) if item.per_mail is not None else "—"] for item in ordered]
    rows.append(["Hinweis", "Gerundete Anteile ergeben nicht immer genau 100 %.", "", "", ""])
    return bar_list("chart-stages", "Rechenzeit je Verarbeitungsschritt",
                    "Summierte Dauer der KI-Aufrufe, größter Anteil zuerst; parallele Aufrufe werden addiert.",
                    [(item.label, item.seconds) for item in ordered],
                    lambda value: f"{percent(value / total * 100 if total else 0)} · {duration_text(value)}",
                    table=(["Schritt", "Anteil", "Summe", "Aufrufe", "Median je Mail"], rows))


def _share_class(share: float) -> str:
    """Width in 5 % steps through classes: the content security policy forbids inline styles."""
    return f"share-{min(100, max(0, round(share / 5) * 5))}"


def _measured(number: int, item: StageTime, total: float, bottleneck: bool) -> str:
    share = item.share(total)
    median = f'<span class="meta">Median je Mail {e(duration_text(item.per_mail))}</span>' \
        if item.per_mail is not None else ""
    mark = '<span class="pipeline-mark">⏱ größte Wartezeit</span>' if bottleneck else ""
    return (f'<div class="pipeline-part"><span class="pipeline-name">{number}. {e(item.label)}</span>{mark}'
            f'<span class="pipeline-time">{e(percent(share))} · {e(duration_text(item.seconds))}</span>{median}'
            f'<span class="pipeline-bar {_share_class(share)}" aria-hidden="true"></span></div>')


def _local(number: int, key: str) -> str:
    return (f'<div class="pipeline-part"><span class="pipeline-name">{number}. {e(label(key))}</span>'
            '<span class="meta">lokal · nicht gemessen</span></div>')


def pipeline_plan(records: list[dict[str, Any]]) -> str:
    """The processing chain in the order of ProcessingStage; nothing when nothing was measured."""
    times = stage_times(records)
    if not times:
        return ""
    total = sum(item.seconds for item in times.values())
    bottleneck = max(times.values(), key=lambda item: (item.seconds, item.label)).key
    order = [stage.value for stage in ProcessingStage]
    steps: list[list[str]] = []
    for key in order:
        if key == BRANCH[1]:
            continue  # shown together with the event extraction
        steps.append(list(BRANCH) if key == BRANCH[0] else [key])
    others = sorted((key for key in times if key not in order), key=lambda key: (-times[key].seconds, key))
    nodes, rows = [], []
    for number, keys in enumerate(steps, start=1):
        parts = [(_measured(number, times[key], total, key == bottleneck) if key in times else _local(number, key))
                 for key in keys]
        classes = "pipeline-step" + (" is-bottleneck" if bottleneck in keys else "") \
            + (" is-measured" if any(key in times for key in keys) else " is-local")
        branch = '<p class="meta pipeline-branch">je nach Aktion</p>' if len(keys) > 1 else ""
        nodes.append(f'<li class="{classes}">{branch}{"".join(parts)}</li>')
        for key in keys:
            item = times.get(key)
            rows.append([str(number), label(key), "gemessen" if item else "lokal, nicht gemessen",
                         percent(item.share(total)) if item else "—", duration_text(item.seconds) if item else "—",
                         duration_text(item.per_mail) if item and item.per_mail is not None else "—"])
    if others:
        number = len(steps) + 1
        listed = "".join(f'<li>{e(times[key].label)}: {e(percent(times[key].share(total)))} · '
                         f'{e(duration_text(times[key].seconds))}</li>' for key in others)
        extra = "pipeline-step is-measured is-other" + (" is-bottleneck" if bottleneck in others else "")
        mark = '<span class="pipeline-mark">⏱ größte Wartezeit</span>' if bottleneck in others else ""
        nodes.append(f'<li class="{extra}"><div class="pipeline-part"><span class="pipeline-name">{number}. '
                     f'Weitere KI-Aufrufe</span>{mark}<ul class="pipeline-others">{listed}</ul></div></li>')
        for key in others:
            item = times[key]
            rows.append([str(number), f"Weitere KI-Aufrufe: {item.label}", "gemessen", percent(item.share(total)),
                         duration_text(item.seconds),
                         duration_text(item.per_mail) if item.per_mail is not None else "—"])
    table = ('<details><summary>Werte als Tabelle</summary><div class="table-scroll" tabindex="0" role="region" '
             'aria-label="Wertetabelle: Ablauf der Mailverarbeitung"><table><thead><tr>'
             + "".join(f"<th>{name}</th>" for name in ("Nr.", "Schritt", "Art", "Anteil", "Summe", "Median je Mail"))
             + "</tr></thead><tbody>"
             + "".join("<tr>" + "".join(f"<td>{e(cell)}</td>" for cell in row) + "</tr>" for row in rows)
             + "</tbody></table></div></details>")
    return ('<figure class="chart pipeline-figure" aria-labelledby="pipeline-title"><figcaption>'
            '<span id="pipeline-title">Ablauf der Mailverarbeitung</span></figcaption>'
            '<p class="meta">Gemessen werden nur KI-Aufrufe; lokale Schritte erzeugen keine relevante Wartezeit.</p>'
            f'<ol class="pipeline">{"".join(nodes)}</ol>{table}</figure>')


__all__ = ["pipeline_plan", "ranking", "stage_times"]
