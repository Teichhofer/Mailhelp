from __future__ import annotations
import errno, imaplib, json, os, signal, subprocess, sys
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage
from pathlib import Path
import httpx, pytest
from pydantic import ValidationError

from mailhelp import __version__
from mailhelp.analysis import Analyzer
from mailhelp.cli import main
from mailhelp.config import IrrelevantTopicsConfig, LlmRoute, PromptConfig, PromptStep, Topic, TopicsConfig, _deep_merge, _dotenv, _yaml, load_all
from mailhelp.imap import FetchedMail, ImapReader, UIDValidityChanged, account_id
from mailhelp.integrations import HttpWriter, execute_confirmed
from mailhelp.logging import JsonlLogger, redact
from mailhelp.mime import prepare
from mailhelp.models import (Actions, ProcessingErrorCode, Proposal, ProposalKind,
                             ProposalStatus, Relevance, Summary)
from mailhelp.openrouter import OpenRouterClient, RateLimitExceeded
from mailhelp.orchestrator import Orchestrator
from mailhelp.storage import AlreadyRunning, CorruptState, JsonStore
from mailhelp.telegram import Decision, TelegramClient, apply_decision, split_message


def prompt_config(model="model"):
    return PromptConfig(defaults={"model": model, "parameters": {"temperature": .2}}, prompts={x: PromptStep(system_prompt=x, parameters={"max_tokens": 200}) for x in ("relevance", "summary", "action_router", "task_extraction", "event_extraction", "proposal_revision", "learning_classification", "learning_abstraction")})


def test_strict_ordered_llm_route_configuration():
    primary = LlmRoute(provider="openrouter", model="primary", parameters={"temperature": .1},
                       provider_preferences={"order": ["provider-a"]})
    fallback = LlmRoute(provider="openrouter", model="fallback")
    cfg = prompt_config()
    cfg.prompts["summary"] = PromptStep(system_prompt="summary", routes=[primary, fallback])
    routes, prompt, retries = cfg.resolved_routes("summary")
    assert ([route.model for route in routes], prompt, retries) == (["primary", "fallback"], "summary", 1)
    for routes in ([], [primary, primary]):
        with pytest.raises(ValidationError):
            PromptStep(system_prompt="x", routes=routes)
    for route in (
        {"provider": "unknown", "model": "m"},
        {"provider": "openrouter", "model": ""},
        {"provider": "openrouter", "model": "m", "parameters": {"messages": []}},
        {"provider": "openrouter", "model": "m", "provider_preferences": {"free_form": True}},
        {"provider": "openrouter", "model": "m", "provider_preferences": {"order": ["x", "x"]}},
        {"provider": "openrouter", "model": "<anbieter/modell>"},
    ):
        with pytest.raises(ValidationError):
            LlmRoute.model_validate(route)


def proposal(**kw):
    base = dict(id="p1", version=1, kind="task", responsibility="user", certainty="certain", classification="new", title="Tun", evidence="Mail sagt es", source_mail_id="a"*24, target="inbox")
    if "status" not in kw and (kw.get("open_questions") or kw.get("responsibility") not in {None, "user"}
                               or kw.get("certainty") not in {None, "certain"}
                               or kw.get("classification") not in {None, "new"}):
        base["status"] = "needs_clarification"
    base.update(kw); return Proposal.model_validate(base)


def test_models_and_config(tmp_path, monkeypatch, capsys):
    assert __version__ == "0.1.0"
    assert {ProcessingErrorCode.PROVIDER_RESPONSE_INVALID.value,
            ProcessingErrorCode.INVALID_JSON.value,
            ProcessingErrorCode.SCHEMA_VALIDATION_FAILED.value} == {
                "provider_response_invalid", "invalid_json", "schema_validation_failed"}
    assert Relevance(decision="relevant", reason="x").topic_ids == []
    assert len(Summary(sentences=["a"]).sentences) == 1
    assert len(Summary(sentences=["a", "b"]).sentences) == 2
    with pytest.raises(ValidationError):
        Summary(sentences=["a", "b", "c"])
    assert Actions().proposals == []
    with pytest.raises(ValidationError): Relevance(decision="irrelevant", reason="x", topic_ids=["x"])
    with pytest.raises(ValidationError): Relevance(decision="relevant", reason="x", topic_ids=["x", "x"])
    start = datetime.now(timezone.utc)
    proposal(id="e", kind="event", start=start, end=start + timedelta(hours=1))
    with pytest.raises(ValidationError): proposal(kind="event")
    with pytest.raises(ValidationError): Proposal(id="e", version=1, kind="event", title="x", evidence="y")
    with pytest.raises(ValidationError): proposal(kind="event", start=start, end=start)
    with pytest.raises(ValidationError): proposal(start=start)
    with pytest.raises(ValidationError, match="externes Ergebnis"):
        proposal(status="simulated", external_id="invented")
    with pytest.raises(ValidationError, match="gemeldet"):
        proposal(simulation_notified=True)
    assert proposal(status="simulated", simulation_notified=True).external_id is None
    assert _deep_merge({"x": {"a": 1}, "z": 1}, {"x": {"b": 2}, "z": 2}) == {"x": {"a": 1, "b": 2}, "z": 2}
    cfg = prompt_config(); model, params, prompt = cfg.resolved("summary")
    assert (model, prompt, params) == ("model", "summary", {"temperature": .2, "max_tokens": 200})
    bad = prompt_config("<placeholder>")
    with pytest.raises(ValueError, match="nicht eingerichtet"): bad.resolved("summary")
    bad.defaults["parameters"]["model"] = "evil"
    bad.defaults["model"] = "ok"
    with pytest.raises(ValueError, match="Reservierte"): bad.resolved("summary")
    with pytest.raises(ValidationError): PromptConfig(defaults={}, prompts={"summary": PromptStep(system_prompt="x")})
    names = ("relevance", "summary", "action_router", "task_extraction",
             "event_extraction", "proposal_revision", "learning_classification", "learning_abstraction")
    with pytest.raises(ValidationError, match="Primärmodell"):
        PromptConfig(defaults={}, prompts={name: PromptStep(system_prompt=name) for name in names})
    invalid_parameters = prompt_config()
    invalid_parameters.defaults["parameters"]["nested"] = {"unsupported": True}
    with pytest.raises(ValueError, match="Unbekannte"):
        invalid_parameters.resolved_routes("summary")
    (tmp_path / "bad.yaml").write_text("- x", encoding="utf8")
    with pytest.raises(ValueError): _yaml(tmp_path / "bad.yaml")
    assert _dotenv(tmp_path / "missing.env") == {}
    env_file = tmp_path / ".env"
    env_file.write_text("# comment\n\nIMAP_USERNAME='file-user'\nIMAP_PASSWORD=file-pass\n", encoding="utf8")
    assert _dotenv(env_file)["IMAP_USERNAME"] == "file-user"
    env_file.write_text("BROKEN\n", encoding="utf8")
    with pytest.raises(ValueError, match="Zeile 1"): _dotenv(env_file)
    env_file.write_text("bad-key=x\n", encoding="utf8")
    with pytest.raises(ValueError, match="Schlüssel"): _dotenv(env_file)
    env_file.unlink()
    for name in ("config.yaml", "prompts.yaml", "topics.yaml", "irrelevant_topics.yaml"):
        (tmp_path / name).write_text((Path(name)).read_text(encoding="utf8"), encoding="utf8")
    env = {x: "secret" for x in ["IMAP_USERNAME", "IMAP_PASSWORD", "OPENROUTER_API_KEY", "TELEGRAM_BOT_TOKEN", "TODOIST_TOKEN", "TODOIST_CLIENT_ID", "TODOIST_CLIENT_SECRET", "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN"]}
    settings, secrets, topics, irrelevant_topics, prompts, fingerprint = load_all(tmp_path, env)
    assert settings.test_mode and secrets.imap_password.get_secret_value() == "secret" and topics[0].enabled and len(fingerprint) == 64
    assert irrelevant_topics
    assert len({topic.id for topic in irrelevant_topics}) == len(irrelevant_topics)
    assert settings.logging.llm.include_requests is True
    assert settings.logging.llm.include_responses is True
    with pytest.raises(ValueError, match="Fehlende"): load_all(tmp_path, {})
    (tmp_path / ".env").write_text("\n".join(f"{key}=from-file" for key in env), encoding="utf8")
    assert load_all(tmp_path, {"IMAP_USERNAME": "runtime"})[1].imap_username == "runtime"
    (tmp_path / ".env").unlink()
    (tmp_path / "topics.yaml").write_text("topics: []", encoding="utf8")
    with pytest.raises(ValueError, match="topics"): load_all(tmp_path, env)
    with pytest.raises(ValidationError, match="Themen-IDs"):
        TopicsConfig(topics=[
            Topic(id="doppelt", name="A", enabled=True, description="A"),
            Topic(id="doppelt", name="B", enabled=False, description="B"),
        ])
    with pytest.raises(ValidationError, match="aktiviert"):
        TopicsConfig(topics=[Topic(id="aus", name="Aus", enabled=False, description="Aus")])
    IrrelevantTopicsConfig(topics=[])
    with pytest.raises(ValidationError, match="Themen-IDs"):
        IrrelevantTopicsConfig(topics=[
            Topic(id="doppelt", name="A", enabled=True, description="A"),
            Topic(id="doppelt", name="B", enabled=False, description="B"),
        ])
    (tmp_path / "topics.yaml").write_text(
        "topics:\n  - {id: thema, name: Thema, enabled: true, description: Test}\nunbekannt: true\n",
        encoding="utf8",
    )
    with pytest.raises(ValueError, match="unbekannt"): load_all(tmp_path, env)
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--config-directory", str(Path.cwd()), "--check"]); monkeypatch.setattr(os, "environ", env)
    monkeypatch.setattr("mailhelp.cli.build_logger", lambda *_args, **_kwargs: type("Logger", (), {"event": lambda *_args, **_kwargs: None})())
    assert main() == 0; assert "gültig" in capsys.readouterr().out
    class App:
        def __init__(self): self.stopped=False
        def stop(self): self.stopped=True
        def run(self, max_mails=None):
            assert max_mails is None
            signal_handlers[signal.SIGINT](signal.SIGINT, None)
            signal_handlers[signal.SIGTERM](signal.SIGTERM, None)
    app=App(); signal_handlers={}
    @contextmanager
    def builder(*args, **kwargs): yield app
    monkeypatch.setattr("mailhelp.cli.build_application", builder)
    monkeypatch.setattr("mailhelp.cli.signal.signal", lambda signum, handler: signal_handlers.__setitem__(signum, handler))
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--config-directory", str(Path.cwd())]); assert main() == 0 and app.stopped


def test_load_all_restores_only_missing_distributed_topic_files(tmp_path, monkeypatch):
    for name in ("config.yaml", "prompts.yaml"):
        (tmp_path / name).write_text(Path(name).read_text(encoding="utf-8"), encoding="utf-8")
    custom_irrelevant = "topics:\n- id: custom\n  name: Custom\n  enabled: false\n  description: Custom\n"
    (tmp_path / "irrelevant_topics.yaml").write_text(custom_irrelevant, encoding="utf-8")
    env = {name: "secret" for name in (
        "IMAP_USERNAME", "IMAP_PASSWORD", "OPENROUTER_API_KEY", "TELEGRAM_BOT_TOKEN",
        "TODOIST_TOKEN", "TODOIST_CLIENT_ID", "TODOIST_CLIENT_SECRET",
        "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN",
    )}

    _, _, topics, irrelevant_topics, _, _ = load_all(tmp_path, env)

    assert topics
    assert irrelevant_topics[0].id == "custom"
    assert (tmp_path / "irrelevant_topics.yaml").read_text(encoding="utf-8") == custom_irrelevant

    # Exercise the harmless race where another process creates the missing file
    # after the existence check but before exclusive creation.
    (tmp_path / "topics.yaml").unlink()
    original_open = Path.open

    def racing_open(path, mode="r", *args, **kwargs):
        if path == tmp_path / "topics.yaml" and mode == "x":
            path.write_text(Path("topics.yaml").read_text(encoding="utf-8"), encoding="utf-8")
        return original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", racing_open)

    assert load_all(tmp_path, env)[2]


def test_mime():
    msg = EmailMessage(); msg["From"]="A <a@example.test>"; msg["Subject"]="Hallo"; msg["Message-ID"]="<1>"; msg.set_content("Inhalt\n-- \nSignatur"); msg.add_alternative("<b>HTML</b>", subtype="html"); msg.add_attachment(b"x", maintype="application", subtype="octet-stream", filename="x.bin")
    value = prepare(msg.as_bytes(), 10000); assert value["text"] == "Inhalt" and value["metadata"]["attachments_omitted"] == 1
    html = EmailMessage(); html.set_content("<p>Nur <b>HTML</b></p>", subtype="html"); assert prepare(html.as_bytes(), 1000)["text"] == "Nur HTML"
    with pytest.raises(ValueError): prepare(b"x" * 5, 2)


class FakeImap:
    def __init__(self, *args, **kwargs): self.mode="ok"; self.logged=False
    def login(self, *args): self.logged=True
    def select(self, folder, readonly): return (("NO", []) if folder == "bad" else ("OK", []))
    def response(self, key): return ((None, []) if self.mode == "validity" else ("UIDVALIDITY", [b"7"]))
    def uid(self, action, *args):
        if self.mode == "search": return "NO", []
        if action == "search": return "OK", [b"4"]
        if self.mode == "fetch": return "NO", []
        return "OK", [(b'4 (INTERNALDATE "17-Sep-2026 10:11:12 +0200")', b"raw")]
    def logout(self): self.logged=False


def test_imap():
    reader=ImapReader("h", 1, "u", "p", factory=FakeImap); assert reader.fetch_since("INBOX")[0].raw == b"raw"
    assert reader.fetch_since("INBOX", 3, 7)[0].uid == 4
    assert reader.fetch_uid("INBOX",4,7).raw == b"raw"
    with pytest.raises(RuntimeError): reader.fetch_uid("bad",4,7)
    reader.connection.mode="validity"
    with pytest.raises(RuntimeError): reader.fetch_uid("INBOX",4,7)
    reader.connection.mode="ok"
    with pytest.raises(RuntimeError,match="UIDVALIDITY"): reader.fetch_uid("INBOX",4,8)
    reader.connection.mode="fetch"
    with pytest.raises(RuntimeError): reader.fetch_uid("INBOX",4,7)
    reader.connection.mode="ok"
    with pytest.raises(RuntimeError): reader.fetch_since("bad")
    reader.connection.mode="validity"
    with pytest.raises(RuntimeError): reader.fetch_since("INBOX")
    reader.connection.mode="search"
    with pytest.raises(RuntimeError): reader.fetch_since("INBOX")
    reader.connection.mode="fetch"
    with pytest.raises(RuntimeError): reader.fetch_since("INBOX")
    reader.close(); assert not reader.connection.logged

    class BadLogin(FakeImap):
        def login(self, *args): raise RuntimeError("login")
    failed=BadLogin()
    with pytest.raises(RuntimeError, match="login"): ImapReader("h",1,"u","p",factory=lambda *a,**k: failed)
    assert not failed.logged

    class RejectedLogin(BadLogin):
        def login(self, *args):
            self.credentials = args
            raise imaplib.IMAP4.error(b"authentication failed")
    rejected = RejectedLogin()
    with pytest.raises(RuntimeError, match="Punkte und Bindestriche") as error:
        ImapReader("h", 1, "S.H.-Teichhof@example.test", "secret",
                   factory=lambda *a, **k: rejected)
    assert rejected.credentials == ("S.H.-Teichhof@example.test", "secret")
    assert not rejected.logged
    assert error.value.__suppress_context__
    assert isinstance(error.value.__context__, imaplib.IMAP4.error)


def test_imap_fetch_is_batched_and_reports_progress():
    class ManyImap(FakeImap):
        def uid(self, action, *args):
            if action == "search":
                return "OK", [b"4 5 6"]
            uid = args[0]
            return "OK", [(uid + b' (INTERNALDATE "17-Sep-2026 10:11:12 +0200")', b"raw")]

    class Logger:
        def __init__(self): self.events=[]
        def event(self, level, module, event, **fields): self.events.append((level,module,event,fields))

    logger=Logger()
    reader=ImapReader("h",1,"u","p",factory=ManyImap,logger=logger,batch_size=2)
    assert [mail.uid for mail in reader.fetch_since("INBOX")] == [6,5]
    progress=[event for event in logger.events if event[2] in {"messages_discovered","message_fetched"}]
    assert progress[0] == ("INFO","imap","messages_discovered",{"folder":"INBOX","available_count":3,"batch_count":2})
    assert progress[1][2:] == ("message_fetched",{"folder":"INBOX","uid":6,"batch_index":1,"batch_count":2})
    assert progress[2][2:] == ("message_fetched",{"folder":"INBOX","uid":5,"batch_index":2,"batch_count":2})

    assert [mail.uid for mail in reader.fetch_since("INBOX", max_count=1)] == [6]
    limited=[event for event in logger.events if event[2] == "messages_discovered"][-1]
    assert limited[3] == {"folder":"INBOX","available_count":3,"batch_count":1}

    reader.connection.uid=lambda *_args: ("OK", [])
    assert reader.fetch_since("INBOX") == []


def test_imap_newest_first_skips_completed_ranges_and_resets_on_uidvalidity():
    class BacklogImap(FakeImap):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs); self.commands=[]
        def uid(self, action, *args):
            self.commands.append((action,args))
            if action == "search": return "OK", [b"4 5 6"]
            uid=args[0]
            return "OK", [(uid+b' (INTERNALDATE "17-Sep-2026 10:11:12 +0200")',b"raw")]
    reader=ImapReader("h",1,"u","p",factory=BacklogImap,batch_size=3)
    assert [m.uid for m in reader.fetch_since("INBOX",3,7,completed_uid_ranges=((5,6),))]==[4]
    command_count=len(reader.connection.commands)
    with pytest.raises(UIDValidityChanged) as changed:
        reader.fetch_since("INBOX",3,8,completed_uid_ranges=((4,6),))
    assert (changed.value.previous, changed.value.current)==(8,7)
    assert len(reader.connection.commands)==command_count


def test_imap_connection_and_exact_historical_boundary():
    class BoundaryImap(FakeImap):
        def __init__(self, dates=(b'2',)):
            super().__init__(); self.dates=dates; self.tls=False; self.commands=[]
        def starttls(self): self.tls=True; return "OK", []
        def uid(self, action, *args):
            self.commands.append((action,args))
            if action=="search" and args[-1]=="ALL": return "OK", [b"1 2 9"]
            if action=="search": return "OK", [b" ".join(self.dates)]
            if args[-1]=="(INTERNALDATE)":
                stamp=(b'01-Jan-2025 22:59:00 -0500' if args[0]==b"2" else
                       b'02-Jan-2025 04:00:00 +0000' if args[0]==b"4" else
                       b'02-Jan-2025 04:01:00 +0000')
                return "OK", [(b'2 (INTERNALDATE "'+stamp+b'")', b"")]
            return super().uid(action,*args)
    connection=BoundaryImap((b"2",b"3"))
    reader=ImapReader(" Example.COM. ",143," User ","p",factory=lambda *a,**k: connection,starttls=True)
    assert connection.tls and reader.determine_start_uid("INBOX",datetime(2025,1,2,4,0,tzinfo=timezone.utc))==2
    assert account_id("example.com",143,"user")==reader.account_id
    assert all(command[1][-1] != "(BODY[])" for command in connection.commands)

    exact=BoundaryImap((b"4",))
    assert ImapReader("h",143,"u","p",factory=lambda *a,**k:exact).determine_start_uid(
        "INBOX",datetime(2025,1,2,4,0,tzinfo=timezone.utc))==3

    no_match=BoundaryImap(())
    other=ImapReader("h",143,"u","p",factory=lambda *a,**k:no_match)
    assert other.determine_start_uid("INBOX",datetime(2025,1,2,tzinfo=timezone.utc))==9
    no_match.uid=lambda *args: ("NO",[])
    with pytest.raises(RuntimeError): other.determine_start_uid("INBOX",datetime.now(timezone.utc))

    bad_tls=BoundaryImap(); bad_tls.starttls=lambda: ("NO",[])
    with pytest.raises(RuntimeError,match="STARTTLS"): ImapReader("h",143,"u","p",factory=lambda *a,**k:bad_tls,starttls=True)

    broken=BoundaryImap()
    broken.select=lambda *_a,**_k: ("NO",[])
    with pytest.raises(RuntimeError,match="nicht lesbar"): ImapReader("h",143,"u","p",factory=lambda *a,**k:broken).determine_start_uid("bad",datetime.now(timezone.utc))
    no_validity=BoundaryImap(); no_validity.mode="validity"
    with pytest.raises(RuntimeError,match="UIDVALIDITY"): ImapReader("h",143,"u","p",factory=lambda *a,**k:no_validity).determine_start_uid("INBOX",datetime.now(timezone.utc))

    valid_responses = (
        [b'2 (INTERNALDATE "02-Jan-2025 04:01:00 +0000")'],
        [(b'2 (INTERNALDATE "02-Jan-2025 04:01:00 +0000")', b"")],
        [b")", (), (7, b"ignored"),
         (b'2 (internaldate "02-Jan-2025 04:01:00 +0000")', b""), b")"],
    )
    for response in valid_responses:
        direct=BoundaryImap()
        original=direct.uid
        direct.uid=lambda action,*args,response=response: ("OK",response) if action=="fetch" else original(action,*args)
        assert ImapReader("h",143,"u","p",factory=lambda *a,**k:direct).determine_start_uid("INBOX",datetime(2025,1,2,4,0,tzinfo=timezone.utc)) == 1

    for rejected_status in ("NO", "BAD"):
        rejected=BoundaryImap()
        original=rejected.uid
        rejected.uid=lambda action,*args,status=rejected_status: (status,[]) if action=="fetch" else original(action,*args)
        with pytest.raises(RuntimeError,match=f"abgelehnt: {rejected_status}"):
            ImapReader("h",143,"u","p",factory=lambda *a,**k:rejected).determine_start_uid("INBOX",datetime.now(timezone.utc))

    for response in (None, [], [b")"], [b"bad"], [(b"bad",b"")]):
        malformed=BoundaryImap()
        original=malformed.uid
        malformed.uid=lambda action,*args,response=response: ("OK",response) if action=="fetch" else original(action,*args)
        with pytest.raises(RuntimeError,match="leer oder strukturell unbrauchbar"):
            ImapReader("h",143,"u","p",factory=lambda *a,**k:malformed).determine_start_uid("INBOX",datetime.now(timezone.utc))

    invalid=BoundaryImap()
    original=invalid.uid
    invalid.uid=lambda action,*args: ("OK",[(b'2 (INTERNALDATE "bad")',b"")]) if action=="fetch" else original(action,*args)
    with pytest.raises(RuntimeError,match="ungültigen INTERNALDATE-Datumswert"):
        ImapReader("h",143,"u","p",factory=lambda *a,**k:invalid).determine_start_uid("INBOX",datetime.now(timezone.utc))

    empty=BoundaryImap(())
    empty.uid=lambda action,*args: ("OK",[b""])
    assert ImapReader("h",143,"u","p",factory=lambda *a,**k:empty).determine_start_uid("INBOX",datetime.now(timezone.utc))==0
    all_failure=BoundaryImap(())
    all_failure.uid=lambda action,*args: ("NO",[]) if args[-1]=="ALL" else ("OK",[b""])
    with pytest.raises(RuntimeError,match="IMAP-Suche fehlgeschlagen"):
        ImapReader("h",143,"u","p",factory=lambda *a,**k:all_failure).determine_start_uid("INBOX",datetime.now(timezone.utc))


def test_storage_and_logging(tmp_path):
    store=JsonStore(tmp_path/"data")
    with store:
        store.save("x", {"umlaut":"ä"}); assert store.load("x") == {"umlaut":"ä"}; assert store.load("missing", 4)==4
        with pytest.raises(ValueError): store.load("../outside")
        with pytest.raises(ValueError): store.save("bad/name", {})
        with pytest.raises(AlreadyRunning): JsonStore(tmp_path/"data").__enter__()
    assert (tmp_path/"data/.lock").exists()
    (tmp_path/"data/x.json").write_text("{", encoding="utf8")
    with pytest.raises(CorruptState): store.load("x")
    assert redact({"token":"abc", "nested":["Bearer xyz", 2]}) == {"token":"***", "nested":["Bearer ***", 2]}
    logger=JsonlLogger(tmp_path/"logs"); logger.event("INFO","test","ok", password="bad"); logger.llm_event("request", request={"mail":"private"}, response="private")
    logger2=JsonlLogger(tmp_path/"logs2", True, True); logger2.llm_event("response", request="a", response="b")
    assert "bad" not in logger.app.read_text() and "private" not in logger.llm.read_text() and '"response": "b"' in logger2.llm.read_text()


def test_storage_windows_directory_sync(tmp_path, monkeypatch):
    store = JsonStore(tmp_path)
    monkeypatch.setattr("mailhelp.storage.os.name", "nt")
    store.save("windows", {"ok": True})


def test_storage_stale_file_process_exit_and_mode_isolation(tmp_path):
    stale = tmp_path / "stale"
    stale.mkdir()
    (stale / ".lock").write_text('{"pid": 1}', encoding="ascii")
    with JsonStore(stale):
        assert json.loads((stale / ".lock").read_text(encoding="ascii"))["pid"] == os.getpid()

    root = tmp_path / "modes"
    with JsonStore(root / "test"):
        with JsonStore(root / "production"):
            with pytest.raises(AlreadyRunning):
                JsonStore(root / "test").__enter__()

    crashed = tmp_path / "crashed"
    code = (
        "import sys,time\n"
        "from pathlib import Path\n"
        "from mailhelp.storage import JsonStore\n"
        "JsonStore(Path(sys.argv[1])).__enter__()\n"
        "print('locked', flush=True)\n"
        "time.sleep(60)\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(crashed)],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None and process.stdout.readline().strip() == "locked"
    with pytest.raises(AlreadyRunning):
        JsonStore(crashed).__enter__()
    process.kill()
    process.wait(timeout=10)
    with JsonStore(crashed):
        pass


def test_storage_lock_platform_and_failure_paths(tmp_path, monkeypatch):
    import types

    platform_name = os.name
    descriptor = os.open(tmp_path / "windows-lock", os.O_CREAT | os.O_RDWR, 0o600)
    calls = []
    fake_msvcrt = types.SimpleNamespace(LK_NBLCK=7, locking=lambda *args: calls.append(args))
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    monkeypatch.setattr("mailhelp.storage.os.name", "nt")
    JsonStore._acquire_lock(descriptor)
    JsonStore._acquire_lock(descriptor)
    os.close(descriptor)
    assert calls == [(descriptor, 7, 1), (descriptor, 7, 1)]

    monkeypatch.setattr("mailhelp.storage.os.name", platform_name)
    store = JsonStore(tmp_path / "failure")
    monkeypatch.setattr(store, "_acquire_lock", lambda _descriptor: (_ for _ in ()).throw(OSError(errno.EIO, "disk")))
    with pytest.raises(OSError, match="disk"):
        store.__enter__()

    metadata_store = JsonStore(tmp_path / "metadata-failure")
    monkeypatch.setattr(metadata_store, "_acquire_lock", JsonStore._acquire_lock)
    monkeypatch.setattr("mailhelp.storage.os.fsync", lambda _descriptor: (_ for _ in ()).throw(OSError("sync")))
    with pytest.raises(OSError, match="sync"):
        metadata_store.__enter__()
    assert metadata_store.lock is None
    metadata_store.__exit__()
