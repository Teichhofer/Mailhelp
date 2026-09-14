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
from mailhelp.adapter import RetryableError
from mailhelp.orchestrator import MailState, Orchestrator
from mailhelp.storage import JsonStore
from mailhelp.telegram import Decision, DecisionAction, TelegramClient, apply_decision, split_message
from test_core import prompt_config, proposal


def mock_response(status=200, data=None):
    return lambda request: httpx.Response(status, json={} if data is None else data, request=request)


def test_openrouter(monkeypatch):
    data={"id":"completion-1","choices":[{"message":{"content":json.dumps({"decision":"irrelevant","reason":"x"})}}]}
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
    with pytest.raises(RetryableError): client.complete("m", {}, "s", {})


class FakeCompleter:
    def __init__(self, values): self.values=iter(values); self.calls=0
    def complete(self, *args): self.calls+=1; return str(self.calls), next(self.values)


def test_analyzer():
    client=FakeCompleter([{}, {"decision":"relevant","topic_ids":["x"],"reason":"yes"}, {"sentences":["a","b"]}, {"proposals":[]}])
    analyzer=Analyzer(client,prompt_config(),1); topic=Topic(id="x",name="X",enabled=True,description="D")
    assert analyzer.relevance({},[topic])[1].decision == "relevant"; assert analyzer.summary({})[1].sentences == ["a","b"]; assert analyzer.actions({})[1].proposals == []
    with pytest.raises(ValueError): Analyzer(FakeCompleter([{},{}]),prompt_config(),1).summary({})
    with pytest.raises(ValueError, match="unbekannte"): Analyzer(FakeCompleter([{"decision":"relevant","topic_ids":["bad"],"reason":"x"}]),prompt_config()).relevance({}, [topic])
    with pytest.raises(ValueError, match="mindestens"): Analyzer(FakeCompleter([{"decision":"relevant","topic_ids":[],"reason":"x"}]),prompt_config()).relevance({}, [topic])


def test_telegram():
    p=proposal(); assert apply_decision(p,Decision(proposal_id="p1",version=1,action=DecisionAction.CONFIRM),1,2,1,2).status == ProposalStatus.CONFIRMED
    assert apply_decision(p,Decision(proposal_id="p1",version=1,action=DecisionAction.REJECT),1,2,1,2).status == ProposalStatus.REJECTED
    assert apply_decision(p,Decision(proposal_id="p1",version=1,action=DecisionAction.EDIT),1,2,1,2).status == ProposalStatus.NEEDS_CLARIFICATION
    with pytest.raises(PermissionError): apply_decision(p,Decision(proposal_id="p1",version=1,action=DecisionAction.CONFIRM),9,2,1,2)
    with pytest.raises(ValueError, match="Veraltete"): apply_decision(p,Decision(proposal_id="p1",version=2,action=DecisionAction.CONFIRM),1,2,1,2)
    with pytest.raises(ValueError, match="Offene"): apply_decision(proposal(open_questions=["wann?"]),Decision(proposal_id="p1",version=1,action=DecisionAction.CONFIRM),1,2,1,2)
    with pytest.raises(ValueError): Decision(proposal_id="p1",version=1,action="xx")
    assert apply_decision(proposal(status="created"),Decision(proposal_id="p1",version=1,action=DecisionAction.CONFIRM),1,2,1,2).status == ProposalStatus.CREATED
    assert split_message("abc",2)==["ab","c"] and split_message("")==[""]
    with pytest.raises(ValueError): split_message("x",0)
    requests=[]
    def handler(req):
        requests.append(req)
        data={"ok":True,"result":[{"update_id":1,"message":{"message_id":1,"from":{"id":1},"chat":{"id":2},"text":"x"}}]} if req.url.path.endswith("getUpdates") else {"ok":True,"result":{"message_id":1}}
        return httpx.Response(200,json=data,request=req)
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
    saved=[]
    with pytest.raises(ValueError): execute_confirmed(proposal(),Writer(),saved.append)
    assert execute_confirmed(p,Writer(),saved.append,True)[1]["simulation"]
    assert saved[-1].status == ProposalStatus.CONFIRMED
    assert execute_confirmed(p,Writer({"id":"old"}),saved.append)[1]["id"]=="old"
    assert execute_confirmed(p,Writer(),saved.append)[0].status == ProposalStatus.CREATED
    assert execute_confirmed(p,Writer(error=httpx.ReadTimeout("x")),saved.append)[0].status == ProposalStatus.UNCERTAIN
    writing=proposal(status="writing")
    assert execute_confirmed(writing,Writer(),saved.append)[0].status == ProposalStatus.UNCERTAIN
    assert execute_confirmed(writing,Writer({"id":"late","htmlLink":"https://event"}),saved.append)[0].external_link == "https://event"
    uncertain=proposal(status="uncertain")
    assert execute_confirmed(uncertain,Writer(),saved.append)[0].status == ProposalStatus.CREATED
    response=httpx.Response(400, request=httpx.Request("POST", "https://example.test"))
    assert execute_confirmed(p,Writer(error=httpx.HTTPStatusError("bad", request=response.request, response=response)),saved.append)[0].status == ProposalStatus.FAILED
    assert ProposalStatus.WRITING in [item.status for item in saved]
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
    def send_proposal(self,p): self.messages.append(p.id)


def test_orchestrator(tmp_path):
    raw=b"Subject: Test\n\nBody"; mail=FetchedMail("INBOX",1,2,raw); topic=Topic(id="x",name="x",enabled=True,description="x")
    with JsonStore(tmp_path/"a") as store:
        class PlainNotify:
            def __init__(self): self.messages=[]
            def send(self,c,t): self.messages.append(t)
        n=PlainNotify(); o=Orchestrator(AnalyzerStub("relevant"),store,n,1,[topic],1000); state=o.process(mail); assert state["steps"]["completion"]=="completed" and n.messages; assert o.process(mail)==state
    with JsonStore(tmp_path/"b") as store:
        state=Orchestrator(AnalyzerStub("irrelevant"),store,Notify(),1,[topic],1000).process(mail)
        assert state["steps"]=={"preparation":"completed","relevance":"completed","summary":"skipped","action_detection":"skipped","notification":"skipped","completion":"completed"}
    with JsonStore(tmp_path/"c") as store:
        o=Orchestrator(AnalyzerStub("unclear"),store,Notify(),1,[topic],1000)
        state=o.process(mail); assert state["awaiting_relevance"] and state["steps"]["completion"]=="pending"
        assert o.process(mail)==state
    with JsonStore(tmp_path/"d") as store: assert "error" in Orchestrator(AnalyzerStub("relevant"),store,Notify(),1,[topic],1).process(mail)
    with JsonStore(tmp_path/"e") as store:
        o=Orchestrator(AnalyzerStub("irrelevant"),store,Notify(),1,[topic],1000); count=[]
        def poll(): count.append(1); o.stop(); return [mail]
        o.run(poll,0,lambda _:None); assert count==[1]
    with JsonStore(tmp_path/"f") as store:
        o=Orchestrator(AnalyzerStub("irrelevant"),store,Notify(),1,[topic],1000); waits=[]
        def wait(x): waits.append(x); o.stop()
        o.run(lambda: [mail],2,wait); assert waits==[2]

    class ProposalAnalyzer(AnalyzerStub):
        def actions(self,m):
            from mailhelp.models import Actions
            return "a",Actions(proposals=[proposal()])
    with JsonStore(tmp_path/"g") as store:
        notify=Notify(); Orchestrator(ProposalAnalyzer("relevant"),store,notify,1,[topic],1000).process(mail)
        assert "p1" in notify.messages
    with JsonStore(tmp_path/"multiple") as store:
        analyzer=AnalyzerStub("irrelevant"); orchestrator=Orchestrator(analyzer,store,Notify(),1,[topic],1000)
        first=orchestrator.process(mail)
        second=orchestrator.process(FetchedMail("INBOX",1,3,b"Subject: Other\n\nBody"))
        assert first["id"] != second["id"] and all(item["steps"]["completion"]=="completed" for item in (first,second))


def test_orchestrator_resumes_each_persisted_analysis_step(tmp_path):
    raw=b"Subject: Restart\n\nBody"; mail=FetchedMail("INBOX",1,9,raw); topic=Topic(id="x",name="x",enabled=True,description="x")
    class CountingAnalyzer(AnalyzerStub):
        def __init__(self): super().__init__("relevant"); self.calls=[]
        def relevance(self,m,t): self.calls.append("relevance"); return super().relevance(m,t)
        def summary(self,m): self.calls.append("summary"); return super().summary(m)
        def actions(self,m): self.calls.append("actions"); return super().actions(m)
    class InterruptingStore:
        def __init__(self, delegate, fail_at): self.delegate=delegate; self.fail_at=fail_at; self.count=0
        def load(self,*args): return self.delegate.load(*args)
        def save(self,*args):
            self.count += 1
            if self.count >= self.fail_at: raise RuntimeError("power loss")
            self.delegate.save(*args)
    for fail_at, repeated in ((2,"relevance"),(3,"summary"),(4,"actions"),(5,None),(6,None)):
        with JsonStore(tmp_path/str(fail_at)) as disk:
            first=CountingAnalyzer()
            with pytest.raises(RuntimeError,match="power loss"):
                Orchestrator(first,InterruptingStore(disk,fail_at),Notify(),1,[topic],1000).process(mail)
            second=CountingAnalyzer(); result=Orchestrator(second,disk,Notify(),1,[topic],1000).process(mail)
            assert result["steps"]["completion"]=="completed"
            assert second.calls == ([repeated] + [x for x in ("summary","actions") if (repeated=="relevance" or repeated=="summary" and x=="actions")] if repeated else [])

    with JsonStore(tmp_path/"invalid") as store:
        store.save("mail-"+"a"*24,{"schema_version":2,"id":"bad","imap":{},"steps":{}})
        with pytest.raises(Exception): MailState.model_validate(store.load("mail-"+"a"*24))

def test_orchestrator_defers_rate_limit_and_reports(tmp_path):
    class Limited:
        def relevance(self, mail, topics):
            raise RateLimitExceeded(120.0)
    class Log:
        def __init__(self): self.events=[]
        def event(self,*args,**kwargs): self.events.append((args,kwargs))
    with JsonStore(tmp_path/"limited") as store:
        notify=Notify(); log=Log()
        topic=Topic(id="x",name="x",enabled=True,description="x")
        mail=FetchedMail("INBOX",1,20,b"Subject: Limit\n\nBody")
        state=Orchestrator(Limited(),store,notify,1,[topic],1000,log).process(mail)
        assert state["deferred_until"].startswith("1970-01-01T00:02:00")
        assert "LLM-Limit" in notify.messages[0] and any(item[0][2] == "llm_rate_limited" for item in log.events)
        second=Orchestrator(Limited(),store,notify,1,[topic],1000,log,lambda:100)
        assert second.process(mail)["deferred_until"] == state["deferred_until"]
    with JsonStore(tmp_path/"limited-no-log") as store:
        Orchestrator(Limited(),store,Notify(),1,[topic],1000).process(mail)
