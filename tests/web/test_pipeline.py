"""5.9.10: computing time per step with German names and the pipeline plan in processing order."""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from mailhelp.domain.processing import ProcessingStage
from mailhelp.web.pipeline import pipeline_plan, ranking, stage_times

NOW = datetime(2026, 11, 12, 12, tzinfo=UTC)


def call(stage, seconds, mail=None):
    return {"started_at": (NOW - timedelta(hours=1)).isoformat(), "status": "success", "cost_usd": None,
            "duration_ms": seconds * 1000, "stage": stage, "model": "x/m", "mail_id": mail}


def mail(number):
    return f"{number:024x}"


def test_regression_the_ranking_names_steps_in_german_with_share_and_duration():
    """Regression 5.9.10: the ranking showed raw keys such as "event_extraction" in seconds only."""
    records = [call("event_extraction", 5220, mail(1)), call("event_extraction", 60, mail(1)),
               call("event_extraction", 100, mail(2)), call("relevance", 5400), call("diagnostic_test", 20)]
    html = ranking(stage_times(records))
    assert "Rechenzeit je Verarbeitungsschritt" in html and "event_extraction" not in html
    # 5380 s of 10800 s: 49,8 % · 1 Std. 30 Min.; the median per mail of 5280 s and 100 s.
    assert ">49,8 % · 1 Std. 30 Min.</text>" in html
    assert "<tr><td>Terminerkennung</td><td>49,8 %</td><td>1 Std. 30 Min.</td><td>3</td><td>44 Min. 50 s</td></tr>" in html
    # Calls without a mail (comparison runs) count in sum and share only.
    assert "<tr><td>Relevanzprüfung</td><td>50,0 %</td><td>1 Std. 30 Min.</td><td>1</td><td>—</td></tr>" in html
    assert "<td>diagnostic_test</td>" in html  # unknown keys stay unchanged
    assert "Gerundete Anteile ergeben nicht immer genau 100 %." in html


def test_the_plan_follows_the_processing_order_and_marks_local_steps():
    records = [call("relevance", 10, mail(1)), call("summary", 30, mail(1)), call("event_extraction", 50, mail(1)),
               call("vision", 5, mail(1)), call("auto_draft", 5)]
    html = pipeline_plan(records)
    names = re.findall(r'<span class="pipeline-name">(\d+)\. ([^<]+)</span>', html)
    assert [name for _, name in names[:4]] == ["Aufbereitung", "Relevanzprüfung", "Zusammenfassung",
                                               "Telegram-Zusammenfassung"]
    # Event and task extraction share one numbered node: one or both run, depending on the action.
    assert ("7", "Terminerkennung") in names and ("7", "Aufgabenerkennung") in names
    assert html.count("je nach Aktion") == 1
    assert ("10", "Duplikatprüfung") in names and ("11", "Telegram-Vorschlag") in names
    assert html.count("lokal · nicht gemessen") == len(ProcessingStage) - 3  # the task extraction included
    # Keys outside the pipeline are listed at the end, never silently left out.
    assert ("13", "Weitere KI-Aufrufe") in names and "<li>vision: 5,0 % · 5,0 s</li>" in html
    assert "<td>13</td><td>Weitere KI-Aufrufe: auto_draft</td>" in html
    # The bottleneck is named in text, not only by colour; bars use width classes (no inline styles).
    bottleneck = re.search(r'<li class="pipeline-step is-bottleneck[^"]*">(.*?)</li>', html).group(1)
    assert "Terminerkennung" in bottleneck and "⏱ größte Wartezeit" in bottleneck
    assert "pipeline-bar share-50" in html and "pipeline-bar share-10" in html and "style=" not in html
    assert '<ol class="pipeline">' in html and "<td>1</td><td>Aufbereitung</td><td>lokal, nicht gemessen</td>" in html
    assert "<td>2</td><td>Relevanzprüfung</td><td>gemessen</td><td>10,0 %</td><td>10,0 s</td><td>10,0 s</td>" in html


def test_equal_shares_pick_one_bottleneck_and_an_empty_period_shows_no_plan():
    html = pipeline_plan([call("relevance", 10), call("summary", 10)])
    assert html.count("⏱ größte Wartezeit") == 1 and html.count("is-bottleneck") == 1
    assert pipeline_plan([]) == "" and "Weitere KI-Aufrufe" not in html
    # A step measured later appears with its time without a code change.
    measured = pipeline_plan([call("normalization", 1, mail(3))])
    assert "8. Normalisierung</span><span class=\"pipeline-mark\">" in measured
    other = pipeline_plan([call("relevance", 1), call("vision", 9)])
    bottleneck = re.search(r'<li class="pipeline-step is-measured is-other is-bottleneck">(.*?)</li>', other).group(1)
    assert "Weitere KI-Aufrufe" in bottleneck and "⏱ größte Wartezeit" in bottleneck


def test_a_zero_duration_has_a_share_of_zero():
    times = stage_times([call("relevance", 0)])
    assert times["relevance"].share(0) == 0.0 and ">0,0 % · 0,0 s</text>" in ranking(times)
