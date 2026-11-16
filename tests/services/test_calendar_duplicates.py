"""Calendar duplicates and overlaps, and the HTTP writer boundary."""
from __future__ import annotations

import json
from datetime import date

import httpx
import pytest
from pydantic import ValidationError

from mailhelp.processing.analysis import (
    Analyzer,
)
from mailhelp.proposals.integrations import HttpWriter
from tests.fakes.shared_core import prompt_config, proposal
from tests.fakes.shared_services import (
    FakeCompleter,
    mock_response,
)


def test_http_writer_rejects_non_writable_proposal_before_request():
    requests = []
    transport = httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(500, request=request))
    writer = HttpWriter("todoist", "token", "project", transport=transport)
    with pytest.raises(ValueError, match="nicht extern"):
        writer.create(proposal(target='project', classification="unsupported"), "key")
    assert requests == []
    writer.close()


def test_calendar_duplicate_comparison_updates_only_missing_information():
    requests=[]
    decisions=[]
    def matcher(item, existing):
        decisions.append((item, existing))
        from mailhelp.domain.extraction import CalendarDuplicateDecision
        return "llm-call", CalendarDuplicateDecision(
            same_event=True, missing_fields=["description", "location", "video_link"],
            reason="Titel und Zeitpunkt stimmen überein",
        )
    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"items":[{
                "id":"old", "summary":"Tun", "description":"Alt", "location":None,
                "start":{"dateTime":"2026-05-10T10:00:00+00:00"},
                "end":{"dateTime":"2026-05-10T11:00:00+00:00"},
                "htmlLink":"https://calendar.test/old",
            }]}, request=request)
        assert request.method == "PATCH"
        return httpx.Response(200, json={"id":"old", "htmlLink":"https://calendar.test/old"}, request=request)
    writer=HttpWriter("google_calendar","x","primary",transport=httpx.MockTransport(handler),
                      calendar_timezone="UTC",calendar_matcher=matcher)
    item=proposal(target='primary', kind="event",status="confirmed",start="2026-05-10T10:00:00+00:00",
                  end="2026-05-10T11:00:00+00:00",description="Neue Agenda",
                  location="Raum 2",video_link="https://video.example.test/x")
    result=writer.create(item,"stable-key")
    assert result["operation"] == "duplicate_updated" and result["id"] == "old"
    assert len(decisions) == 1 and decisions[0][1]["summary"] == "Tun"
    assert dict(requests[0].url.params) == {
        "timeMin":"2026-05-10T10:00:00+00:00", "timeMax":"2026-05-10T11:00:00+00:00",
        "singleEvents":"true", "maxResults":"50"}
    body=json.loads(requests[1].content)
    assert body == {
        "description":"Alt\n\nNeue Agenda\n\n[Mailhelp-Videolink]\nhttps://video.example.test/x",
        "location":"Raum 2",
        "extendedProperties":{"private":{"mailhelp_key":"stable-key"}},
    }
    writer.close()


def test_calendar_same_event_without_missing_information_is_not_written():
    from mailhelp.domain.extraction import CalendarDuplicateDecision
    methods=[]
    def handler(request):
        methods.append(request.method)
        return httpx.Response(200,json={"items":[{
            "id":"old", "summary":"Tun", "description":"Vollständig",
            "start":{"date":"2026-05-10"}, "end":{"date":"2026-05-11"}
        }]},request=request)
    writer=HttpWriter("google_calendar","x","primary",transport=httpx.MockTransport(handler),
                      calendar_timezone="UTC",calendar_matcher=lambda _p,_e: (
                          "call",CalendarDuplicateDecision(same_event=True,reason="gleich")))
    result=writer.create(proposal(target='primary', kind="event",status="confirmed",all_day=True,
                         start=date(2026,5,10),end=date(2026,5,11)),"key")
    assert result == {"id":"old", "htmlLink":None, "operation":"duplicate_skipped"}
    assert methods == ["GET"]
    writer.close()


def test_calendar_overlap_that_is_not_same_event_is_created():
    from mailhelp.domain.extraction import CalendarDuplicateDecision
    methods=[]
    def handler(request):
        methods.append(request.method)
        data=({"items":[{"id":"other","summary":"Anderes Ereignis",
                         "start":{"dateTime":"2026-05-10T10:00:00+00:00"},
                         "end":{"dateTime":"2026-05-10T11:00:00+00:00"}}]}
              if request.method == "GET" else {"id":"new"})
        return httpx.Response(200,json=data,request=request)
    writer=HttpWriter("google_calendar","x","primary",transport=httpx.MockTransport(handler),
                      calendar_timezone="UTC",calendar_matcher=lambda _p,_e: (
                          "call",CalendarDuplicateDecision(same_event=False,reason="anderer Titel")))
    item=proposal(target='primary', kind="event",status="confirmed",start="2026-05-10T10:00:00+00:00",
                  end="2026-05-10T11:00:00+00:00")
    assert writer.create(item,"key")["id"] == "new" and methods == ["GET","POST"]
    writer.close()


def test_calendar_duplicate_model_and_analyzer_boundary():
    from mailhelp.domain.extraction import CalendarDuplicateDecision
    with pytest.raises(ValidationError, match="gleichen Termin"):
        CalendarDuplicateDecision(same_event=False,missing_fields=["location"],reason="nein")
    with pytest.raises(ValidationError, match="doppelt"):
        CalendarDuplicateDecision(same_event=True,missing_fields=["location","location"],reason="ja")
    client=FakeCompleter([{"same_event":True,"missing_fields":["location"],"reason":"gleich"}])
    analyzer=Analyzer(client,prompt_config(),0)
    item=proposal(kind="event",start="2026-05-10T10:00:00+00:00",
                  end="2026-05-10T11:00:00+00:00")
    call,result=analyzer.calendar_duplicate(item,{"id":"old","summary":"Tun"})
    assert call == "1" and result.same_event


@pytest.mark.parametrize("response", [{"items":"bad"}, [], {"items":[{"id":"missing-interval"}]}])
def test_calendar_overlap_rejects_malformed_provider_responses(response):
    writer=HttpWriter("google_calendar","x","primary",
        transport=httpx.MockTransport(mock_response(data=response)),calendar_timezone="UTC",
        calendar_matcher=lambda _p,_e: (_ for _ in ()).throw(AssertionError()))
    item=proposal(target='primary', kind="event",status="confirmed",start="2026-05-10T10:00:00+00:00",
                  end="2026-05-10T11:00:00+00:00")
    with pytest.raises(ValueError,match="ungültige Antwort"):
        writer.create(item,"key")
    writer.close()


def test_calendar_duplicate_merge_ignores_fields_without_safe_source_and_validates_patch():
    from mailhelp.domain.extraction import CalendarDuplicateDecision
    writer=HttpWriter("google_calendar","x","primary",calendar_timezone="UTC")
    item=proposal(target='primary', kind="event",status="confirmed",start="2026-05-10T10:00:00+00:00",
                  end="2026-05-10T11:00:00+00:00",description="")
    existing=__import__('mailhelp.proposals.integrations',fromlist=['CalendarOverlapEvent']).CalendarOverlapEvent(
        id="old",summary="x",description="",location="belegt",
        start={"dateTime":"x"},end={"dateTime":"y"})
    decision=CalendarDuplicateDecision(same_event=True,
        missing_fields=["description","location"],reason="gleich")
    assert writer._calendar_merge_body(item,"key",existing,decision) == {
        "extendedProperties":{"private":{"mailhelp_key":"key"}}}
    writer.close()

    bad=HttpWriter("google_calendar","x","primary",calendar_timezone="UTC",
        transport=httpx.MockTransport(mock_response(data={})))
    with pytest.raises(ValueError,match="ungültige Antwort"):
        bad._update_calendar_event("old",{},"key",item)
    bad.close()
