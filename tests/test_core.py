from __future__ import annotations
import errno, json, os, signal, subprocess, sys
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage
from pathlib import Path
import httpx, pytest
from pydantic import ValidationError

from mailhelp import __version__
from mailhelp.analysis import Analyzer
from mailhelp.cli import main
from mailhelp.config import PromptConfig, PromptStep, Topic, TopicsConfig, _deep_merge, _dotenv, _yaml, load_all
from mailhelp.imap import FetchedMail, ImapReader, account_id
from mailhelp.integrations import HttpWriter, execute_confirmed
from mailhelp.logging import JsonlLogger, redact
from mailhelp.mime import prepare
from mailhelp.models import Actions, Proposal, ProposalKind, ProposalStatus, Relevance, Summary
from mailhelp.openrouter import OpenRouterClient, RateLimitExceeded
from mailhelp.orchestrator import Orchestrator
from mailhelp.storage import AlreadyRunning, CorruptState, JsonStore
from mailhelp.telegram import Decision, TelegramClient, apply_decision, split_message


def prompt_config(model="model"):
    return PromptConfig(defaults={"model": model, "parameters": {"nested": {"a": 1}, "temperature": .2}}, prompts={x: PromptStep(system_prompt=x, parameters={"nested": {"b": 2}}) for x in ("relevance", "summary", "actions", "proposal_revision")})


def proposal(**kw):
    base = dict(id="p1", version=1, kind="task", responsibility="user", certainty="certain", classification="new", title="Tun", evidence="Mail sagt es", source_mail_id="a"*24, target="inbox")
    base.update(kw); return Proposal.model_validate(base)


def test_models_and_config(tmp_path, monkeypatch, capsys):
    assert __version__ == "0.1.0"
    assert Relevance(decision="relevant", reason="x").topic_ids == []
    assert len(Summary(sentences=["a", "b"]).sentences) == 2
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
    assert (model, prompt, params["nested"]) == ("model", "summary", {"a": 1, "b": 2})
    bad = prompt_config("<placeholder>")
    with pytest.raises(ValueError, match="nicht eingerichtet"): bad.resolved("summary")
    bad.defaults["parameters"]["model"] = "evil"
    bad.defaults["model"] = "ok"
    with pytest.raises(ValueError, match="Reservierte"): bad.resolved("summary")
    with pytest.raises(ValidationError): PromptConfig(defaults={}, prompts={"summary": PromptStep(system_prompt="x")})
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
    for name in ("config.yaml", "prompts.yaml", "topics.yaml"):
        (tmp_path / name).write_text((Path(name)).read_text(encoding="utf8"), encoding="utf8")
    env = {x: "secret" for x in ["IMAP_USERNAME", "IMAP_PASSWORD", "OPENROUTER_API_KEY", "TELEGRAM_BOT_TOKEN", "TODOIST_TOKEN", "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN"]}
    settings, secrets, topics, prompts, fingerprint = load_all(tmp_path, env)
    assert settings.test_mode and secrets.imap_password.get_secret_value() == "secret" and topics[0].enabled and len(fingerprint) == 64
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
    (tmp_path / "topics.yaml").write_text(
        "topics:\n  - {id: thema, name: Thema, enabled: true, description: Test}\nunbekannt: true\n",
        encoding="utf8",
    )
    with pytest.raises(ValueError, match="unbekannt"): load_all(tmp_path, env)
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--config-directory", str(Path.cwd()), "--check"]); monkeypatch.setattr(os, "environ", env)
    assert main() == 0; assert "gültig" in capsys.readouterr().out
    class App:
        def __init__(self): self.stopped=False
        def stop(self): self.stopped=True
        def run(self):
            signal_handlers[signal.SIGINT](signal.SIGINT, None)
            signal_handlers[signal.SIGTERM](signal.SIGTERM, None)
    app=App(); signal_handlers={}
    @contextmanager
    def builder(*args): yield app
    monkeypatch.setattr("mailhelp.cli.build_application", builder)
    monkeypatch.setattr("mailhelp.cli.signal.signal", lambda signum, handler: signal_handlers.__setitem__(signum, handler))
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--config-directory", str(Path.cwd())]); assert main() == 0 and app.stopped


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
                stamp=b'01-Jan-2025 22:59:00 -0500' if args[0]==b"2" else b'02-Jan-2025 04:01:00 +0000'
                return "OK", [(b'2 (INTERNALDATE "'+stamp+b'")', b"")]
            return super().uid(action,*args)
    connection=BoundaryImap((b"2",b"3"))
    reader=ImapReader(" Example.COM. ",143," User ","p",factory=lambda *a,**k: connection,starttls=True)
    assert connection.tls and reader.determine_start_uid("INBOX",datetime(2025,1,2,4,0,tzinfo=timezone.utc))==2
    assert account_id("example.com",143,"user")==reader.account_id
    assert all(command[1][-1] != "(BODY[])" for command in connection.commands)

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

    for response in (("NO",[]), ("OK",[b"bad"]), ("OK",[(b"bad",b"")]), ("OK",[(b'2 (INTERNALDATE "bad")',b"")])):
        malformed=BoundaryImap()
        original=malformed.uid
        malformed.uid=lambda action,*args,response=response: response if action=="fetch" else original(action,*args)
        with pytest.raises(RuntimeError,match="INTERNALDATE"): ImapReader("h",143,"u","p",factory=lambda *a,**k:malformed).determine_start_uid("INBOX",datetime.now(timezone.utc))

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
