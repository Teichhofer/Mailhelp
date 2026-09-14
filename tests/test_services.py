from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
import httpx, pytest
from mailhelp.analysis import Analyzer
from mailhelp.config import Topic
from mailhelp.imap import FetchedMail
from mailhelp.integrations import HttpWriter, execute_confirmed
from mailhelp.models import ProposalStatus
from mailhelp.openrouter import OpenRouterClient, RateLimitExceeded
from mailhelp.orchestrator import Orchestrator
from mailhelp.storage import JsonStore
from mailhelp.telegram import Decision, TelegramClient, apply_decision, split_message
from test_core import prompt_config, proposal


def mock_response(status=200, data=None):
    return lambda request: httpx.Response(status, json={} if data is None else data, request=request)


def test_openrouter(monkeypatch):
    data={"choices":[{"message":{"content":json.dumps({"decision":"irrelevant","reason":"x"})}}]}
    client=OpenRouterClient("secret", 1, 0, 1, httpx.MockTransport(mock_response(data=data)))
    call, result=client.complete("m", {}, "s", {"x":1}); assert call and result["decision"] == "irrelevant"
    with pytest.raises(RateLimitExceeded): client.complete("m", {}, "s", {})
    client.calls[0] -= 61; client.complete("m", {}, "s", {}); client.close()
    attempts=[]
    def flaky(request):
        attempts.append(1)
        if len(attempts) == 1: raise httpx.ConnectError("x", request=request)
        return httpx.Response(500, request=request)
    client=OpenRouterClient("x",1,1,10,httpx.MockTransport(flaky), sleep=lambda x: attempts.append(x))
    with pytest.raises(httpx.HTTPStatusError): client.complete("m", {}, "s", {})


class FakeCompleter:
    def __init__(self, values): self.values=iter(values); self.calls=0
    def complete(self, *args): self.calls+=1; return str(self.calls), next(self.values)


def test_analyzer():
    client=FakeCompleter([{}, {"decision":"relevant","topic_ids":["x"],"reason":"yes"}, {"sentences":["a","b"]}, {"proposals":[]}])
    analyzer=Analyzer(client,prompt_config(),1); topic=Topic(id="x",name="X",enabled=True,description="D")
    assert analyzer.relevance({},[topic])[1].decision == "relevant"; assert analyzer.summary({})[1].sentences == ["a","b"]; assert analyzer.actions({})[1].proposals == []
    with pytest.raises(ValueError): Analyzer(FakeCompleter([{},{}]),prompt_config(),1).summary({})


def test_telegram():
    p=proposal(); assert apply_decision(p,Decision("p1",1,"confirm"),1,2,1,2).status == ProposalStatus.CONFIRMED
    assert apply_decision(p,Decision("p1",1,"reject"),1,2,1,2).status == ProposalStatus.REJECTED
    assert apply_decision(p,Decision("p1",1,"edit"),1,2,1,2).status == ProposalStatus.NEEDS_CLARIFICATION
    with pytest.raises(PermissionError): apply_decision(p,Decision("p1",1,"confirm"),9,2,1,2)
    with pytest.raises(ValueError, match="Veraltete"): apply_decision(p,Decision("p1",2,"confirm"),1,2,1,2)
    with pytest.raises(ValueError, match="Offene"): apply_decision(proposal(open_questions=["wann?"]),Decision("p1",1,"confirm"),1,2,1,2)
    with pytest.raises(ValueError, match="Unbekannte"): apply_decision(p,Decision("p1",1,"xx"),1,2,1,2)
    assert apply_decision(proposal(status="created"),Decision("p1",1,"confirm"),1,2,1,2).status == ProposalStatus.CREATED
    assert split_message("abc",2)==["ab","c"] and split_message("")==[""]
    with pytest.raises(ValueError): split_message("x",0)
    requests=[]
    def handler(req): requests.append(req); return httpx.Response(200,json={"result":[{"update_id":1}]},request=req)
    c=TelegramClient("secret",1,httpx.MockTransport(handler)); assert c.poll(1)[0]["update_id"]==1; c.send(2,"x"*4001); assert len(requests)==3; c.close()


class Writer:
    def __init__(self, found=None, error=None): self.found=found; self.error=error; self.created=0
    def reconcile(self,key): return self.found
    def create(self,p,key):
        self.created += 1
        if self.error: raise self.error
        return {"id":"1"}


def test_integrations():
    p=proposal(status="confirmed")
    with pytest.raises(ValueError): execute_confirmed(proposal(),Writer())
    assert execute_confirmed(p,Writer(),True)[1]["simulation"]
    assert execute_confirmed(p,Writer({"id":"old"}))[1]["id"]=="old"
    assert execute_confirmed(p,Writer())[0].status == ProposalStatus.CREATED
    assert execute_confirmed(p,Writer(error=httpx.ReadTimeout("x")))[0].status == ProposalStatus.UNCERTAIN
    with pytest.raises(ValueError): HttpWriter("bad","x","x")
    seen=[]
    def handler(req): seen.append(req); return httpx.Response(200,json=({"id":"x"} if req.method=="POST" else []),request=req)
    todo=HttpWriter("todoist","x","p",transport=httpx.MockTransport(handler)); assert todo.reconcile("x") is None; todo.create(proposal(status="confirmed", due=datetime.now(timezone.utc)),"key"); todo.close()
    found=HttpWriter("todoist","x","p",transport=httpx.MockTransport(mock_response(data=[{"description":"key", "id":"old"}]))); assert found.reconcile("key")["id"]=="old"
    now=datetime.now(timezone.utc)
    with pytest.raises(ValueError): HttpWriter("todoist","x","p",transport=httpx.MockTransport(handler)).create(proposal(kind="event",start=now,end=now.replace(year=now.year+1)),"k")
    event=proposal(kind="event",start=now,end=now.replace(year=now.year+1),status="confirmed")
    def cal_handler(req): return httpx.Response(200,json=({"id":"x"} if req.method=="POST" else {"items":[]}),request=req)
    cal=HttpWriter("google_calendar","x","primary",transport=httpx.MockTransport(cal_handler)); assert cal.reconcile("k") is None; cal.create(event,"k"); cal.close()
    foundcal=HttpWriter("google_calendar","x","p",transport=httpx.MockTransport(mock_response(data={"items":[{"id":"e"}]}))); assert foundcal.reconcile("k")["id"]=="e"
    with pytest.raises(ValueError): HttpWriter("google_calendar","x","p",transport=httpx.MockTransport(handler)).create(p,"k")


class AnalyzerStub:
    def __init__(self, decision): self.decision=decision
    def relevance(self,m,t):
        from mailhelp.models import Relevance
        return "r",Relevance(decision=self.decision,reason="why")
    def summary(self,m):
        from mailhelp.models import Summary
        return "s",Summary(sentences=["eins","zwei"])
    def actions(self,m):
        from mailhelp.models import Actions
        return "a",Actions()
class Notify:
    def __init__(self): self.messages=[]
    def send(self,c,t): self.messages.append(t)


def test_orchestrator(tmp_path):
    raw=b"Subject: Test\n\nBody"; mail=FetchedMail("INBOX",1,2,raw); topic=Topic(id="x",name="x",enabled=True,description="x")
    with JsonStore(tmp_path/"a") as store:
        n=Notify(); o=Orchestrator(AnalyzerStub("relevant"),store,n,1,[topic],1000); state=o.process(mail); assert state["completed"] and n.messages; assert o.process(mail)==state
    with JsonStore(tmp_path/"b") as store: assert Orchestrator(AnalyzerStub("irrelevant"),store,Notify(),1,[topic],1000).process(mail)["completed"]
    with JsonStore(tmp_path/"c") as store: assert Orchestrator(AnalyzerStub("unclear"),store,Notify(),1,[topic],1000).process(mail)["awaiting_relevance"]
    with JsonStore(tmp_path/"d") as store: assert "error" in Orchestrator(AnalyzerStub("relevant"),store,Notify(),1,[topic],1).process(mail)
    with JsonStore(tmp_path/"e") as store:
        o=Orchestrator(AnalyzerStub("irrelevant"),store,Notify(),1,[topic],1000); count=[]
        def poll(): count.append(1); o.stop(); return [mail]
        o.run(poll,0,lambda _:None); assert count==[1]
    with JsonStore(tmp_path/"f") as store:
        o=Orchestrator(AnalyzerStub("irrelevant"),store,Notify(),1,[topic],1000); waits=[]
        def wait(x): waits.append(x); o.stop()
        o.run(lambda: [mail],2,wait); assert waits==[2]
