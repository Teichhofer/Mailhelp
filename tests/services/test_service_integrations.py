"""Telegram splitting, Todoist and calendar payloads and calendar files."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime

import httpx
import pytest
from pydantic import ValidationError

from mailhelp.domain.proposal import (
    Proposal,
    ProposalStatus,
)
from mailhelp.proposals.integrations import CalendarFileWriter, HttpWriter, calendar_file, execute_confirmed
from mailhelp.telegram import Decision, DecisionAction, TelegramClient, apply_decision, split_message
from tests.fakes.shared_core import proposal
from tests.fakes.shared_services import (
    Writer,
    mock_response,
)


def test_telegram():
    p=proposal()
    assert apply_decision(p,Decision(mail_id="a"*24,proposal_id="p1",version=1,action=DecisionAction.CONFIRM),1,2,1,2).status == ProposalStatus.CONFIRMED
    assert apply_decision(p,Decision(mail_id="a"*24,proposal_id="p1",version=1,action=DecisionAction.REJECT),1,2,1,2).status == ProposalStatus.REJECTED
    assert apply_decision(p,Decision(mail_id="a"*24,proposal_id="p1",version=1,action=DecisionAction.EDIT),1,2,1,2).status == ProposalStatus.NEEDS_CLARIFICATION
    with pytest.raises(PermissionError): apply_decision(p,Decision(mail_id="a"*24,proposal_id="p1",version=1,action=DecisionAction.CONFIRM),9,2,1,2)
    with pytest.raises(ValueError, match="Veraltete"): apply_decision(p,Decision(mail_id="a"*24,proposal_id="p1",version=2,action=DecisionAction.CONFIRM),1,2,1,2)
    with pytest.raises(ValidationError, match="vollständige neue"): Proposal.model_validate({
        **proposal().model_dump(mode="json"), "open_questions": ["wann?"]})
    with pytest.raises(ValueError): Decision(mail_id="a"*24,proposal_id="p1",version=1,action="xx")
    assert apply_decision(proposal(status="created"),Decision(mail_id="a"*24,proposal_id="p1",version=1,action=DecisionAction.CONFIRM),1,2,1,2).status == ProposalStatus.CREATED
    assert split_message("abc",2)==["ab","c"] and split_message("")==[""]
    with pytest.raises(ValueError): split_message("x",0)
    requests=[]
    def handler(req):
        requests.append(req)
        data={"ok":True,"result":[{"update_id":1,"message":{"message_id":1,"from":{"id":1,"is_bot":False,"first_name":"Ada"},"chat":{"id":2,"type":"private"},"date":1_789_000_000,"text":"x","forward_origin":{"type":"user"}},"unused":True}]} if req.url.path.endswith("getUpdates") else {"ok":True,"result":{"message_id":1,"from":{"id":99,"is_bot":True,"first_name":"Mailhelp"},"chat":{"id":2,"type":"private"},"date":1_789_000_001,"text":"x","unused":True}}
        return httpx.Response(200,json=data,request=req)
    c=TelegramClient("secret",1,httpx.MockTransport(handler))
    assert c.poll(1)[0]["update_id"]==1
    c.send(2,"x"*4001)
    assert len(requests)==3
    c.close()




def test_integrations():
    p=proposal(status="confirmed")
    saved=[]
    with pytest.raises(ValueError): execute_confirmed(proposal(),Writer(),saved.append)
    assert execute_confirmed(p,Writer(),saved.append,True)[1]["simulation"]
    assert saved[-1].status == ProposalStatus.SIMULATED
    assert execute_confirmed(saved[-1], Writer(), saved.append, True)[0] == saved[-1]
    assert execute_confirmed(p,Writer({"id":"old"}),saved.append)[1]["id"]=="old"
    assert execute_confirmed(p,Writer(),saved.append)[0].status == ProposalStatus.CREATED
    assert execute_confirmed(p,Writer(error=httpx.ReadTimeout("x")),saved.append)[0].status == ProposalStatus.UNCERTAIN
    writing=proposal(status="writing")
    interrupted_writer=Writer()
    assert execute_confirmed(writing,interrupted_writer,saved.append)[0].status == ProposalStatus.UNCERTAIN
    assert interrupted_writer.created == 0
    assert execute_confirmed(writing,Writer({"id":"late","htmlLink":"https://event"}),saved.append)[0].external_link == "https://event"
    uncertain=proposal(status="uncertain")
    uncertain_writer=Writer()
    assert execute_confirmed(uncertain,uncertain_writer,saved.append)[0].status == ProposalStatus.UNCERTAIN
    assert uncertain_writer.created == 0
    assert execute_confirmed(uncertain,Writer({"id":"late"}),saved.append)[0].status == ProposalStatus.CREATED
    response=httpx.Response(400, request=httpx.Request("POST", "https://example.test"))
    assert execute_confirmed(p,Writer(error=httpx.HTTPStatusError("bad", request=response.request, response=response)),saved.append)[0].status == ProposalStatus.FAILED
    assert ProposalStatus.WRITING in [item.status for item in saved]
    with pytest.raises(ValueError): HttpWriter("bad","x","x")
    seen=[]
    def handler(req):
        seen.append(req)
        return httpx.Response(200,json=({"id":"x"} if req.method=="POST" else {"results":[],"next_cursor":None}),request=req)
    todo=HttpWriter("todoist","x","p",transport=httpx.MockTransport(handler))
    assert todo.reconcile("x") is None
    todo.create(proposal(target="p", status="confirmed", due=datetime.now(UTC)),"key")
    todo.close()
    found=HttpWriter("todoist","x","p",transport=httpx.MockTransport(mock_response(data={"results":[{"description":"[key]", "id":"old"}],"next_cursor":None})))
    assert found.reconcile("key")["id"]=="old"
    now=datetime.now(UTC)
    with pytest.raises(ValueError): HttpWriter("todoist","x","p",transport=httpx.MockTransport(handler)).create(proposal(target="p",kind="event",start=now,end=now.replace(year=now.year+1)),"k")
    event=proposal(target="primary",kind="event",start=now,end=now.replace(year=now.year+1),status="confirmed")
    def cal_handler(req): return httpx.Response(200,json=({"id":"x"} if req.method=="POST" else {"items":[]}),request=req)
    cal=HttpWriter("google_calendar","x","primary",transport=httpx.MockTransport(cal_handler),calendar_timezone="UTC")
    assert cal.reconcile("k") is None
    cal.create(event,"k")
    cal.close()
    foundcal=HttpWriter("google_calendar","x","p",transport=httpx.MockTransport(mock_response(data={"items":[{"id":"e"}]})),calendar_timezone="UTC")
    assert foundcal.reconcile("k")["id"]=="e"
    with pytest.raises(ValueError): HttpWriter("google_calendar","x","inbox",transport=httpx.MockTransport(handler),calendar_timezone="UTC").create(p,"k")


def test_todoist_uses_distinct_date_and_datetime_deadlines():
    payloads=[]
    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200,json={"id":"task"},request=request)
    writer=HttpWriter("todoist","x","p",transport=httpx.MockTransport(handler))
    writer.create(proposal(target='p', status="confirmed", due="2026-10-01"), "date")
    writer.create(proposal(target='p', status="confirmed", due="2026-10-01T17:00:00+02:00"), "instant")
    assert payloads[0]["due_date"] == "2026-10-01" and "due_datetime" not in payloads[0]
    assert payloads[1]["due_datetime"] == "2026-10-01T17:00:00+02:00" and "due_date" not in payloads[1]
    writer.close()


def test_todoist_reconciliation_follows_v1_cursors():
    requests=[]
    def handler(request):
        requests.append(request)
        data = ({"results": [{"id": "unrelated", "description": "other"}], "next_cursor": "next-page"}
                if "cursor" not in request.url.params else
                {"results": [{"id": "existing", "description": "contains [stable-key]"}], "next_cursor": None})
        return httpx.Response(200, json=data, request=request)
    writer=HttpWriter("todoist","x","project",transport=httpx.MockTransport(handler))
    assert writer.reconcile("stable-key")["id"] == "existing"
    assert dict(requests[0].url.params) == {"project_id":"project"}
    assert dict(requests[1].url.params) == {"project_id":"project","cursor":"next-page"}
    writer.close()


def test_calendar_payloads_separate_timed_and_all_day_intervals():
    payloads=[]
    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200,json={"id":"event"},request=request)
    writer=HttpWriter("google_calendar","x","primary",transport=httpx.MockTransport(handler),calendar_timezone="Europe/Berlin")
    writer.create(proposal(target='primary', kind="event",status="confirmed",start="2026-05-10T10:00:00+02:00",end="2026-05-10T11:00:00+02:00",
                           description="Agenda",location="Raum 1",video_link="https://video.example.test/meeting/42"),"timed")
    writer.create(proposal(target='primary', kind="event",status="confirmed",all_day=True,start=date(2026,5,10),end=date(2026,5,11)),"all-day")
    assert payloads[0] == {
        "summary":"Tun", "description":"Agenda\n\n[Mailhelp-Videolink]\nhttps://video.example.test/meeting/42",
        "start":{"dateTime":"2026-05-10T10:00:00+02:00"},
        "end":{"dateTime":"2026-05-10T11:00:00+02:00"},
        "location":"Raum 1", "extendedProperties":{"private":{"mailhelp_key":"timed"}},
        "reminders":{"useDefault":False,"overrides":[{"method":"popup","minutes":5}]},
    }
    assert "reminders" not in payloads[1]
    assert payloads[1]["start"] == {"date":"2026-05-10"}
    assert payloads[1]["end"] == {"date":"2026-05-11"}  # exclusive
    assert payloads[1]["description"] == "" and "location" not in payloads[1]
    assert "conferenceData" not in payloads[0]
    assert "date" not in payloads[0]["start"] and "dateTime" not in payloads[1]["start"]
    writer.close()


def test_calendar_payload_maps_video_link_with_empty_description():
    payloads=[]
    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200,json={"id":"event"},request=request)
    writer=HttpWriter("google_calendar","x","primary",transport=httpx.MockTransport(handler),calendar_timezone="UTC")
    writer.create(proposal(target='primary', kind="event",status="confirmed",start="2026-05-10T10:00:00+00:00",
                           end="2026-05-10T11:00:00+00:00",video_link="http://video.example.test/room"),"key")
    assert payloads[0]["description"] == "[Mailhelp-Videolink]\nhttp://video.example.test/room"
    writer.close()


def test_calendar_timed_payload_keeps_explicit_offset_without_calendar_zone_reinterpretation():
    payloads=[]
    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200,json={"id":"event"},request=request)
    writer=HttpWriter("google_calendar","x","primary",transport=httpx.MockTransport(handler),
                      calendar_timezone="America/New_York")
    writer.create(proposal(target='primary', kind="event",status="confirmed",
                           start="2026-09-23T09:00:00+01:00",
                           end="2026-09-23T10:00:00+01:00"), "offset")
    assert payloads[0]["start"] == {"dateTime":"2026-09-23T09:00:00+01:00"}
    assert payloads[0]["end"] == {"dateTime":"2026-09-23T10:00:00+01:00"}
    writer.close()


def test_calendar_file_writer_sends_ios_importable_attachment():
    class Sender:
        def __init__(self): self.documents=[]
        def send_document(self, chat_id, filename, content, caption=None):
            self.documents.append((chat_id,filename,content,caption))

    sender=Sender()
    writer=CalendarFileWriter(sender,99)
    item=proposal(kind="event",status="confirmed",start="2026-05-10T10:00:00+02:00",
                  end="2026-05-10T11:00:00+02:00",title="Planung, München " + "ä"*40,
                  description="Zeile 1\nZeile 2; Abstimmung",location="Raum 1",
                  video_link="https://video.example.test/meeting")
    assert writer.check_access() is None and writer.reconcile("stable-key") is None
    result=writer.create(item,"stable-key")
    chat,filename,content,caption=sender.documents[0]
    decoded=content.decode("utf-8")
    assert chat == 99 and filename.startswith("termin-") and filename.endswith(".ics")
    assert result["id"].startswith("calendar-file:") and "antippen" in caption
    assert decoded.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n")
    assert "DTSTART:20260510T080000Z" in decoded and "DTEND:20260510T090000Z" in decoded
    unfolded=decoded.replace("\r\n ", "")
    assert "DESCRIPTION:Zeile 1\\nZeile 2\\; Abstimmung\\n\\nVideolink: https://" in unfolded
    assert "LOCATION:Raum 1" in decoded and "\r\n " in decoded
    assert all(len(line.encode("utf-8")) <= 75 for line in decoded.split("\r\n") if line)
    with pytest.raises(ValueError,match="anlegbare Termine"):
        writer.create(proposal(status="confirmed"),"task")
    with pytest.raises(ValueError,match="anlegbare Termine"):
        writer.create(item.model_copy(update={"responsibility":"other"}),"other")


def test_all_day_calendar_file_and_validation():
    item=proposal(kind="event",status="confirmed",all_day=True,start=date(2026,5,10),end=date(2026,5,11),
                  description="",location=None)
    decoded=calendar_file(item,"all-day").decode()
    assert "DTSTART;VALUE=DATE:20260510" in decoded
    assert "DTEND;VALUE=DATE:20260511" in decoded
    assert "DESCRIPTION" not in decoded and "LOCATION" not in decoded
    with pytest.raises(ValueError,match="vollständigen Termin"):
        calendar_file(proposal(),"task")
