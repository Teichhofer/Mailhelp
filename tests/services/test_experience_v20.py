"""Synthetic 2.0 contracts: authorization, replay, restart and untrusted input."""
import base64
import imaplib
import json
from contextlib import nullcontext
from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser
from types import SimpleNamespace as NS

import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from PIL import Image
from pydantic import ValidationError
from pywebpush import WebPushException
from shared_vision import image_bytes, mail
from shared_web_actions import MAIL1
from shared_web_details import with_mail
from web_scenario import mail_id, populate

from mailhelp.adapter import RetryableError
from mailhelp.attachments import AttachmentCache
from mailhelp.briefing import DailyBriefingService
from mailhelp.config import DailyBriefingSettings, Settings
from mailhelp.drafts import DraftService, ReplyDraft, message
from mailhelp.models import MailState
from mailhelp.standalone import DisabledTelegram
from mailhelp.storage import JsonStore
from mailhelp.webpush import NoRedirectSession, PushService, b64, subscription

# Since 2.3 the writers are built in mailhelp.external.providers.
MOVED_WRITERS = ("HttpWriter", "GoogleOAuthTokenProvider")

NEWLINE = chr(10)


def test_raster_cache_validation_restart_and_removal(tmp_path):
    store = JsonStore(tmp_path)
    cache = AttachmentCache(store)
    raw = mail(("image.png", "image", "png", image_bytes(Image.new("RGB", (2000, 500)))))
    entries = [{}]
    cache.prepare(MAIL1, raw, entries)
    assert entries[0]["preview"]["index"] == 0
    data = AttachmentCache(store).read(MAIL1, 0)
    import io
    assert Image.open(io.BytesIO(data)).size == (1600, 400)
    assert cache.read(MAIL1, -1) is None and cache.read(MAIL1, "0") is None
    assert cache.read(MAIL1, 1) is None
    cache.prepare(MAIL1, raw, [])
    for kind, value in (("svg+xml", b"<svg onload='bad'/>"), ("png", b"invalid"), ("png", b"x" * 10_485_761)):
        cache.prepare(MAIL1, mail(("file", "image", kind, value)), [{}])
    with pytest.raises(ValueError):
        cache.directory("../secret")
    cache.remove(MAIL1)
    cache.remove(MAIL1)
    assert not cache.directory(MAIL1).exists()


def test_raster_cache_matches_image_by_filename_extension(tmp_path):
    store = JsonStore(tmp_path)
    cache = AttachmentCache(store)
    raw = mail(("photo.jpg", "application", "octet-stream", image_bytes(Image.new("RGB", (300, 300)))))
    entries = [{}]
    cache.prepare(MAIL1, raw, entries)
    assert "preview" in entries[0]
    assert entries[0]["preview"]["index"] == 0
    assert cache.read(MAIL1, 0) is not None


def test_preview_session_metadata_and_headers(web):
    raw = mail(("image.png", "image", "png", image_bytes(Image.new("RGB", (200, 300)))))
    entries = [{"filename": "<img onerror=bad>", "text": "<script>bad</script>"}]
    AttachmentCache(web.store).prepare(MAIL1, raw, entries)
    with_mail(web.store, 1, extracted_attachments=entries)
    path = f"/mail/{MAIL1}/anhang/0"
    response = web.browser.request("GET", path)
    assert response.status == 200 and response.content_type == "image/jpeg"
    headers = dict(response.all_headers())
    assert headers["Content-Security-Policy"] == "default-src 'none'"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert len([key for key, _ in response.all_headers() if key == "Content-Security-Policy"]) == 1
    page = web.browser.request("GET", f"/mail/{MAIL1}").body.decode()
    assert 'data-lightbox' in page and "&lt;script&gt;" in page
    assert web.browser.request("GET", path[:-1] + "4").status == 404
    AttachmentCache(web.store).remove(MAIL1)
    assert web.browser.request("GET", path).status == 404
    assert web.browser.request("GET", f"/mail/{'f'*24}/anhang/0").status == 404
    assert web.browser.request("GET", f"/mail/{mail_id(2)}/anhang/0").status == 404
    web.auth.revoke_all()
    assert web.browser.request("GET", path).status == 303


class Connection:
    selected = searched = appended = "OK"
    matches = [b""]
    def __init__(self): self.writes = []
    def select(self, folder, readonly):
        assert readonly
        self.folder = folder
        return self.selected, []
    def uid(self, *args):
        self.search = args
        return self.searched, self.matches
    def append(self, *args):
        self.writes.append(args)
        if isinstance(self.appended, Exception): raise self.appended
        return self.appended, []


class Writer:
    """Simulated draft_reply step; records each paid call with its intent."""
    def __init__(self, text="Vielen Dank."):
        self.text, self.calls, self.profiles = text, [], []
    def draft_reply(self, mail, intent, personal_info):
        self.calls.append(intent)
        self.profiles.append(personal_info)
        return "call-" + intent, ReplyDraft(text=self.text)


@pytest.fixture
def draft(tmp_path):
    store = JsonStore(tmp_path)
    populate(store)
    conn = Connection()
    writer = Writer()
    service = DraftService(store, lambda actor: actor == "valid", lambda: nullcontext(conn), "me@example.test",
                           "Entwürfe", analyzer=writer)
    source = store.load_model(f"mail-{MAIL1}", MailState)
    source.mail["headers"].update(message_id="<source@example.test>", reply_to="reply@example.test", references="<older@example.test>")
    store.save(f"mail-{MAIL1}", source.model_dump(mode="json"))
    service.generate("valid", MAIL1, 0, "gen-0001", "accept")
    return service, conn, source, writer


def test_draft_mime_headers_and_input_rejection():
    from mailhelp.domain.prepared import MailHeaders
    H = MailHeaders.model_validate
    data = message(H({"from": "Them <from@example.test>", "reply_to": "reply@example.test", "subject": "Test",
                      "message_id": "<parent@test>", "references": "<older@test> <parent@test>"}),
                   "me@test", "Höfliche Antwort", "<new@test>")
    parsed = BytesParser(policy=policy.default).parsebytes(data)
    assert str(parsed["To"]) == "reply@example.test"
    assert parsed["In-Reply-To"] == "<parent@test>" and parsed["References"] == "<older@test> <parent@test>"
    assert parsed["Subject"] == "Re: Test" and parsed.get_content().strip() == "Höfliche Antwort"
    assert "Bcc" not in parsed and "Cc" not in parsed
    parsed = BytesParser(policy=policy.default).parsebytes(
        message(H({"from": "a@test", "subject": "Re: Test"}), "me@test", "Text", "<new@test>"))
    assert parsed["Subject"] == "Re: Test" and "In-Reply-To" not in parsed
    for headers, sender in (({}, "a@test"), ({"from": "bad"}, "a@test"), ({"from": "a@test"}, "a@test\r\nBcc:evil@test"),
                            ({"from": "a@test", "subject": "Test\r\nBcc:evil@test"}, "me@test")):
        with pytest.raises(ValueError): message(H(headers), sender, "Text", "<new@test>")


def test_draft_generate_edit_save_replay_and_restart(draft):
    service, conn, source, writer = draft
    first = service.get(MAIL1)
    assert (first["version"], first["intent"], first["status"], first["call_id"]) == (1, "accept", "editing", "call-accept")
    # A replayed click (double tap, reload) never pays for a second call.
    assert service.generate("valid", MAIL1, 0, "gen-0001", "accept") == first and writer.calls == ["accept"]
    # Edited text is saved directly; the click on save confirms exactly this text and version.
    result = service.act("valid", MAIL1, 1, "save-0001", "Neue Antwort")
    assert result["status"] == "saved" and result["text"] == "Neue Antwort" and len(conn.writes) == 1
    assert writer.profiles == [""]  # Without a configured value the model gets an empty text.
    assert conn.folder == b'"Entw&APw-rfe"'
    assert conn.writes[0][1] == "(\\Draft \\Seen)"
    assert b"In-Reply-To: <source@example.test>" in conn.writes[0][3] and b"Neue Antwort" in conn.writes[0][3]
    restarted = DraftService(service.store, service.authorize, service.connection, service.sender, analyzer=writer)
    assert restarted.act("valid", MAIL1, 1, "save-0001", "Neue Antwort")["status"] == "saved"
    assert restarted.act("valid", MAIL1, 1, "save-0002", "Neue Antwort")["status"] == "saved"
    assert len(conn.writes) == 1
    with pytest.raises(ValueError, match="bereits im Postfach"): restarted.act("valid", MAIL1, 1, "save-0003", "Andere")
    # A new intent starts the next version; its Message-ID differs from the saved one.
    result = restarted.generate("valid", MAIL1, 1, "gen-0002", "decline")
    assert (result["version"], result["intent"], result["status"]) == (2, "decline", "editing")
    assert writer.calls == ["accept", "decline"]
    restarted.act("valid", MAIL1, 2, "save-0004", "Vielen Dank.")
    assert conn.search[-1] == "<mailhelp-" + MAIL1 + "-v2@draft.local>" and len(conn.writes) == 2


def test_draft_guards_cancel_and_simulation(draft):
    service, conn, source, writer = draft
    for args in (("bad", MAIL1, 1, "key-0001", "Vielen Dank."), ("valid", "../bad", 1, "key-0001", "Text"),
                 ("valid", MAIL1, 1, "bad", "Text"), ("valid", MAIL1, 0, "key-0001", "Text"),
                 ("valid", MAIL1, 1, "key-0001", " ")):
        with pytest.raises((ValueError, PermissionError)): service.act(*args)
    with pytest.raises(ValidationError): service.act("valid", MAIL1, 1, "key-0001", "x" * 8001)
    with pytest.raises(ValueError, match="Antwortart"): service.generate("valid", MAIL1, 1, "gen-0002", "send")
    with pytest.raises(PermissionError): service.generate("bad", MAIL1, 1, "gen-0002", "decline")
    with pytest.raises(ValueError, match="Veraltete"): service.generate("valid", MAIL1, 0, "gen-0002", "decline")
    with pytest.raises(ValueError, match="Idempotenz"): service.generate("valid", MAIL1, 0, "gen-0001", "decline")
    assert writer.calls == ["accept"]
    # Cancel discards the text locally; replays are harmless, everything else is refused.
    result = service.cancel("valid", MAIL1, 1, "cancel-001")
    assert (result["version"], result["status"], result["text"]) == (2, "discarded", "")
    assert service.cancel("valid", MAIL1, 1, "cancel-001") == result
    with pytest.raises(ValueError, match="offener Entwurf"): service.cancel("valid", MAIL1, 2, "cancel-002")
    with pytest.raises(ValueError, match="verworfen"): service.act("valid", MAIL1, 2, "key-0002", "Text")
    assert conn.writes == []
    service.generate("valid", MAIL1, 2, "gen-0003", "question")
    service.test_mode = True
    result = service.act("valid", MAIL1, 3, "key-0003", "Wann genau?")
    assert (result["status"], result["text"]) == ("simulated", "Wann genau?") and not conn.writes
    assert service.act("valid", MAIL1, 3, "key-0004", "Wann genau?")["status"] == "simulated"
    # Mails without stored text (unknown or removed by retention) offer no reply.
    assert service.available(MAIL1) and not service.available("f" * 24)
    with pytest.raises(ValueError): service.generate("valid", "f" * 24, 0, "key-0005", "accept")
    source.mail = None
    service.store.save(f"mail-{MAIL1}", source.model_dump(mode="json"))
    assert not service.available(MAIL1)
    with pytest.raises(ValueError): service.generate("valid", MAIL1, 3, "key-0005", "accept")
    with pytest.raises(ValueError): service.act("valid", mail_id(2), 1, "key-0005", "text")
    assert writer.calls == ["accept", "question"]


def test_session_expiring_during_the_llm_call_stores_nothing(draft):
    service, _, _, writer = draft
    answers = iter([True, False])
    service.authorize = lambda actor: next(answers)
    with pytest.raises(PermissionError): service.generate("valid", MAIL1, 1, "gen-0002", "decline")
    assert writer.calls == ["accept", "decline"]
    assert (service.get(MAIL1)["version"], service.get(MAIL1)["intent"]) == (1, "accept")


def test_operation_log_of_a_draft_is_bounded(draft, monkeypatch):
    service, _, _, _ = draft
    monkeypatch.setattr("mailhelp.drafts.MAX_OPERATIONS", 2)
    service.generate("valid", MAIL1, 1, "gen-0002", "decline")
    service.generate("valid", MAIL1, 2, "gen-0003", "question")
    assert list(service.get(MAIL1)["operations"]) == ["gen-0002", "gen-0003"]


@pytest.mark.parametrize("failure", [OSError("lost"), EOFError("lost"), imaplib.IMAP4.abort("lost")])
def test_uncertain_append_is_reconciled_and_never_duplicated_after_restart(draft, failure):
    service, conn, _, writer = draft
    conn.appended = failure
    assert service.act("valid", MAIL1, 1, "save-0001", "Geändert.")["status"] == "uncertain"
    restarted = DraftService(service.store, service.authorize, service.connection, service.sender, analyzer=writer)
    # The possibly written text is locked and no new draft may hide the unclear result.
    with pytest.raises(ValueError, match="unverändert"): restarted.act("valid", MAIL1, 1, "save-0002", "Anders.")
    with pytest.raises(ValueError, match="unklar"): restarted.generate("valid", MAIL1, 1, "gen-0002", "decline")
    with pytest.raises(ValueError): restarted.cancel("valid", MAIL1, 1, "cancel-001")
    conn.matches = [b"12"]  # The lost append did reach the server.
    assert restarted.act("valid", MAIL1, 1, "save-0001", "Geändert.")["status"] == "saved"
    assert restarted.act("valid", MAIL1, 1, "save-0002", "Geändert.")["status"] == "saved"
    assert len(conn.writes) == 1 and writer.calls == ["accept"]


def test_uncertain_append_proven_missing_is_appended_exactly_once_more(draft):
    """Regression: an unclear result blocked the draft forever although it was provably missing."""
    service, conn, _, _ = draft
    conn.appended = OSError("lost")
    assert service.act("valid", MAIL1, 1, "save-0001", "Vielen Dank.")["status"] == "uncertain"
    conn.appended, conn.search = "OK", None
    restarted = DraftService(service.store, service.authorize, service.connection, service.sender)
    assert restarted.act("valid", MAIL1, 1, "save-0001", "Vielen Dank.")["status"] == "saved"
    assert conn.search[-1] == "<mailhelp-" + MAIL1 + "-v1@draft.local>" and len(conn.writes) == 2
    assert restarted.act("valid", MAIL1, 1, "save-0002", "Vielen Dank.")["status"] == "saved"
    assert len(conn.writes) == 2


@pytest.mark.parametrize("refusal", ["NO", imaplib.IMAP4.error("BAD command")])
def test_definite_refusal_releases_the_draft_for_correction(draft, refusal):
    """Regression: a definite NO was treated as unclear and could never be retried."""
    service, conn, _, _ = draft
    conn.appended = refusal
    result = service.act("valid", MAIL1, 1, "save-0001", "Vielen Dank.")
    assert result["status"] == "editing" and "abgelehnt" in result["error"]
    assert service.act("valid", MAIL1, 1, "save-0001", "Vielen Dank.")["status"] == "editing"
    assert len(conn.writes) == 1
    conn.appended = "OK"
    result = service.act("valid", MAIL1, 1, "save-0002", "Korrigiert.")
    assert result["status"] == "saved" and result["error"] is None and len(conn.writes) == 2
    assert b"Korrigiert." in conn.writes[1][3]


def test_retention_during_an_append_never_restores_the_text(draft):
    service, conn, source, _ = draft
    def scrub(*args):
        conn.writes.append(args)
        source.mail = None
        service.store.save(f"mail-{MAIL1}", source.model_dump(mode="json"))
        return "OK", []
    conn.append = scrub
    result = service.act("valid", MAIL1, 1, "save-0001", "Vielen Dank.")
    assert result["status"] == "saved" and service.get(MAIL1)["text"] == ""


def test_retention_during_the_llm_call_never_restores_the_text(draft):
    service, _, source, writer = draft
    def scrub(mail, intent, personal_info):
        source.mail = None
        service.store.save(f"mail-{MAIL1}", source.model_dump(mode="json"))
        return "call", ReplyDraft(text="Privat")
    writer.draft_reply = scrub
    assert service.generate("valid", MAIL1, 1, "gen-0002", "decline")["text"] == ""
    assert service.get(MAIL1)["text"] == ""


def test_draft_lookup_failures_keep_edits_and_reauthorize_before_append(draft):
    service, conn, _, _ = draft
    conn.selected = "NO"
    with pytest.raises(ValueError): service.act("valid", MAIL1, 1, "save-0001", "Bearbeitet.")
    # A failed mailbox access never loses what the user typed.
    assert service.get(MAIL1)["text"] == "Bearbeitet." and service.get(MAIL1)["status"] == "editing"
    conn.selected, conn.searched = "OK", "NO"
    with pytest.raises(ValueError): service.act("valid", MAIL1, 1, "save-0001", "Bearbeitet.")
    conn.searched = "OK"
    answers = iter([True, False])
    service.authorize = lambda actor: next(answers)
    with pytest.raises(PermissionError): service.act("valid", MAIL1, 1, "save-0001", "Bearbeitet.")
    assert conn.writes == []


def sub():
    key = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"endpoint": "https://fcm.googleapis.com/fcm/send/synthetic", "keys": {"p256dh": b64(key), "auth": b64(b"x" * 16)}}


def test_subscription_validation_and_no_redirects(monkeypatch):
    good = sub()
    assert subscription(good) == good
    for endpoint in ("http://fcm.googleapis.com/x", "https://127.0.0.1/x", "https://fcm.googleapis.com.evil/x",
                     "https://fcm.googleapis.com:444/x", "https://user@fcm.googleapis.com/x",
                     "https://user:pass@fcm.googleapis.com/x", "https://fcm.googleapis.com/x#frag",
                     "https://fcm.googleapis.com/" + "x" * 4096):
        with pytest.raises(ValueError): subscription({**good, "endpoint": endpoint})
    assert subscription({**good, "endpoint": "https://abc.notify.windows.com/x"})
    for name, value in (("auth", "!!!"), ("auth", b64(b"bad")), ("p256dh", b64(b"x" * 65))):
        with pytest.raises(ValueError): subscription({**good, "keys": {**good["keys"], name: value}})
    seen = []
    monkeypatch.setattr(requests.Session, "request", lambda self, method, url, **kw: seen.append(kw))
    NoRedirectSession().request("POST", good["endpoint"], allow_redirects=True)
    assert seen == [{"allow_redirects": False}]


def test_push_device_ownership_replay_cleanup_and_neutral_payload(tmp_path):
    store = JsonStore(tmp_path)
    active = {"first", "second"}
    auth = NS(active=lambda actor: actor in active)
    sent = []
    push = PushService(store, auth, "mailto:me@example.test", sender=lambda **kw: sent.append(kw))
    assert len(base64.urlsafe_b64decode(push.public_key + "=")) == 65
    assert PushService(store, auth, "mailto:me@example.test").public_key == push.public_key
    good = sub()
    push.change("first", "key-0001", good)
    push.change("first", "key-0001", good)
    with pytest.raises(ValueError): push.change("first", "key-0001", None)
    with pytest.raises(ValueError): push.change("first", "short", good)
    with pytest.raises(PermissionError): push.change("invalid", "key-0001", good)
    push.change("second", "key-0001", sub())
    active.remove("second")
    push.notify()
    assert len(sent) == 1 and json.loads(sent[0]["data"])["url"] == "/offen"
    assert set(store.load("push-subscriptions")["devices"]) == {"first"}
    push.change("first", "key-0002")
    assert store.load("push-subscriptions")["devices"] == {}
    push.notify()


@pytest.mark.parametrize("code,removed", [(404, True), (410, True), (500, False), (None, False), ("network", False)])
def test_push_failures_do_not_leak_or_stop_other_devices(tmp_path, code, removed):
    store = JsonStore(tmp_path)
    response = requests.Response()
    response.status_code = code if isinstance(code, int) else 500
    def fail(**kw):
        if code == "network": raise requests.ConnectionError("secret endpoint")
        raise WebPushException("secret endpoint", response=response if code is not None else None)
    service = PushService(store, NS(active=lambda _: True), "mailto:me@test", fail)
    service.change("device", "key-0001", sub())
    service.notify()
    assert ("device" not in store.load("push-subscriptions")["devices"]) == removed


def test_briefing_clock_partial_failure_restart_and_formatting(tmp_path):
    store = JsonStore(tmp_path)
    now = [datetime(2026, 10, 25, 5, 29, tzinfo=UTC)]
    windows, sent = [], []
    def events(start, end, strict):
        windows.append((start, end, strict))
        return [NS(start={"dateTime": "2026-10-25T15:30:00+01:00"}, summary="Zahnarzt Dr. Weber"),
                NS(start={"dateTime": "2026-10-25T09:00:00Z"}, summary="Jour fixe"),
                NS(start={"date": "2026-10-25"}, summary=None)]
    calendar = NS(fetch_events_in_window=events)
    tasks = NS(fetch_active_tasks=lambda: [NS(due=None), NS(due={"date": "2026-10-26"}, content="future"),
        NS(due={"date": "2026-10-20"}, content="Steuerunterlagen abschicken")])
    def fail(_): raise OSError("offline")
    channels = {"telegram": sent.append, "offline": fail}
    svc = DailyBriefingService(store, DailyBriefingSettings(enabled=True), "Europe/Berlin", calendar, tasks,
        NS(overview=lambda: NS(open=[1], relevance=[])), channels, lambda: now[0])
    svc.tick()
    assert not sent
    now[0] = datetime(2026, 10, 25, 6, 30, tzinfo=UTC)
    svc.tick()
    assert sent == [store.load("briefing-latest")["text"]] == [NEWLINE.join([
        "Guten Morgen! ☀️", "📅 Heute 3 Termine:", "• ganztägig: Ohne Titel", "• 10:00 Uhr: Jour fixe",
        "• 15:30 Uhr: Zahnarzt Dr. Weber", "✅ 1 Aufgabe fällig:", "• Steuerunterlagen abschicken",
        "✉️ 1 Entscheidung wartet auf dich."])]
    assert windows[0][0].utcoffset() != windows[0][1].utcoffset()  # DST transition day
    assert store.load("daily-briefing")["channels"] == {"telegram": "sent", "offline": "uncertain"}
    svc.tick()
    restarted = DailyBriefingService(store, svc.settings, "Europe/Berlin", calendar, tasks, svc.views, channels, lambda: now[0])
    restarted.tick()
    assert len(sent) == 1
    now[0] = datetime(2026, 10, 26, 7, 30, tzinfo=UTC)
    restarted.tick()
    assert len(sent) == 2
    calendar.fetch_events_in_window = lambda *a, **kw: (_ for _ in ()).throw(OSError())
    tasks.fetch_active_tasks = lambda: (_ for _ in ()).throw(OSError())
    text = svc.build(now[0])
    assert "📅 (Kalender aktuell nicht erreichbar)" in text and "✅ (Aufgaben aktuell nicht erreichbar)" in text
    svc.settings = DailyBriefingSettings(enabled=False, include_calendar=False, include_tasks=False, include_open=False)
    assert svc.build(now[0]) == "Guten Morgen! ☀️"
    svc.tick()


def test_briefing_lists_are_limited_and_fit_into_one_telegram_message(tmp_path):
    from mailhelp.briefing import MAX_LENGTH
    many = [NS(due={"date": "2026-10-01"}, content="x" * 500) for _ in range(12)]
    svc = DailyBriefingService(JsonStore(tmp_path), DailyBriefingSettings(include_open=False), "UTC",
        NS(fetch_events_in_window=lambda *a, **kw: []), NS(fetch_active_tasks=lambda: many), None, {})
    text = svc.build(datetime(2026, 10, 25, 8, tzinfo=UTC))
    assert "📅 Heute 0 Termine." in text and "✅ 12 Aufgaben fällig:" in text
    assert len(text) == MAX_LENGTH and text.endswith("…")
    svc.tasks = NS(fetch_active_tasks=lambda: many[:1] * 11)
    short = [NS(due={"date": "2026-10-01"}, content="kurz")] * 11
    svc.tasks = NS(fetch_active_tasks=lambda: short)
    text = svc.build(datetime(2026, 10, 25, 8, tzinfo=UTC))
    assert text.count("• kurz") == 10 and text.endswith("• … und 1 weitere")
    svc.tasks = NS(fetch_active_tasks=lambda: [])
    assert "✅ 0 Aufgaben fällig." in svc.build(datetime(2026, 10, 25, 8, tzinfo=UTC))


def test_disabled_telegram_never_uses_network(monkeypatch):
    client = DisabledTelegram()
    waits = []
    monkeypatch.setattr(client.stopped, "wait", waits.append)
    assert client.send(1, "text") is None and client.check_access() is None
    assert client.started_chats(1) == [] and client.answer_callback("cb", "ok") is None
    assert client.poll(0) == [] and client.poll(0, 0) == []
    assert waits == [30, 0]
    client.close()
    assert client.stopped.is_set()


def test_web_push_auth_csrf_and_error_paths(web):
    feature = web.site.experience
    form = web.form("/", kind="confirm", proposal_id="formular")
    assert web.browser.request("GET", "/api/push/public-key").status == 503
    assert web.browser.request("POST", "/api/push/subscribe", form).status == 503
    feature.push = PushService(web.store, web.auth, "mailto:me@test", sender=lambda **kw: None)
    result = json.loads(web.browser.request("GET", "/api/push/public-key").body)
    assert result["public_key"] == feature.push.public_key
    payload = {"csrf": form["csrf"], "key": "key-0001", "subscription": json.dumps(sub())}
    assert web.browser.request("POST", "/api/push/subscribe", {**payload, "csrf": "bad"}).status == 403
    assert web.browser.request("POST", "/api/push/subscribe", payload).status == 200
    assert len(web.store.load("push-subscriptions")["devices"]) == 1
    assert web.browser.request("POST", "/api/push/subscribe", {**payload, "subscription": "invalid"}).status == 400
    assert web.browser.request("POST", "/api/push/subscribe", {"csrf": form["csrf"]}).status == 400
    assert web.browser.request("POST", "/api/push/unsubscribe", {**payload, "key": "key-0002"}).status == 200
    assert not web.store.load("push-subscriptions")["devices"]
    web.auth.revoke_all()
    assert web.browser.request("GET", "/api/push/public-key", accept="application/json").status == 401
    assert web.browser.request("POST", "/api/push/subscribe", payload).status == 403


def test_web_reply_buttons_generate_edit_save_and_error_paths(web):
    feature = web.site.experience
    form = web.form("/", kind="confirm", proposal_id="formular")
    path = f"/mail/{MAIL1}/entwurf"
    page = web.browser.request("GET", f"/mail/{MAIL1}").body.decode()
    assert web.browser.request("POST", path, form).status == 503 and "Zusagen" not in page
    conn, writer = Connection(), Writer("<test>")
    feature.drafts = DraftService(web.store, web.auth.active, lambda: nullcontext(conn), "me@test", analyzer=writer)
    # The three intents are always offered, also without open decisions and on the proposal page.
    page = web.browser.request("GET", f"/mail/{MAIL1}").body.decode()
    for label in ("Zusagen", "Absagen", "Rückfrage"):
        assert f">{label}</button>" in page
    assert "draft-editor" not in page and " disabled>" not in page
    assert "Rückfrage</button>" in web.browser.request("GET", f"/vorschlag/{MAIL1}/formular").body.decode()
    generate = {"csrf": form["csrf"], "version": "0", "key": "gen-0001", "mode": "generate", "intent": "accept"}
    response = web.browser.request("POST", path, generate)
    assert response.status == 303 and dict(response.all_headers())["Location"] == f"/mail/{MAIL1}#antwort"
    assert web.browser.request("POST", path, generate).status == 303 and writer.calls == ["accept"]
    page = web.browser.request("GET", f"/mail/{MAIL1}").body.decode()
    assert "&lt;test&gt;" in page and "Entwurf: Zusage" in page and ">Abbrechen</button>" in page
    assert "Als Entwurf im Postfach speichern" in page and conn.writes == []
    save = {"csrf": form["csrf"], "version": "1", "key": "key-0001", "text": "Gerne!", "mode": "save"}
    for change in ({"mode": "invalid"}, {"version": "0"}, {"intent": "send", "mode": "generate", "key": "gen-0002"}):
        assert web.browser.request("POST", path, {**save, **change}).status == 409
    assert web.browser.request("POST", path, save).status == 303
    assert len(conn.writes) == 1 and b"Gerne!" in conn.writes[0][3]
    page = feature.editor(MAIL1, form["csrf"])
    assert "Im Postfach gespeichert" in page and "draft-editor" not in page and "Zusagen" in page
    # Cancel discards the next draft without any mailbox access.
    web.browser.request("POST", path, {**generate, "version": "1", "key": "gen-0003", "intent": "question"})
    assert "Entwurf: Rückfrage" in feature.editor(MAIL1, form["csrf"])
    cancel = {"csrf": form["csrf"], "version": "2", "key": "cancel-001", "mode": "cancel"}
    assert web.browser.request("POST", path, cancel).status == 303
    page = feature.editor(MAIL1, form["csrf"])
    assert "draft-editor" not in page and "Absagen" in page and len(conn.writes) == 1
    # Failures never leak mail content or internals.
    def offline(*a, **kw): raise OSError("private content")
    feature.drafts.act = feature.drafts.generate = offline
    response = web.browser.request("POST", path, {**save, "version": "3", "key": "key-0002"})
    assert response.status == 503 and b"Postfach" in response.body and b"private content" not in response.body
    response = web.browser.request("POST", path, {**generate, "version": "3", "key": "gen-0004"})
    assert response.status == 503 and b"nicht erstellt" in response.body and b"private" not in response.body


def test_unclear_save_locks_the_reply_and_removed_mail_hides_it(web):
    feature = web.site.experience
    csrf = web.form("/", kind="confirm", proposal_id="formular")["csrf"]
    conn = Connection()
    conn.appended = OSError("lost")
    feature.drafts = DraftService(web.store, web.auth.active, lambda: nullcontext(conn), "me@test", analyzer=Writer())
    session = web.auth.sessions()[0].id
    feature.drafts.generate(session, MAIL1, 0, "gen-0001", "decline")
    feature.drafts.act(session, MAIL1, 1, "key-0001", "Leider nicht.")
    page = feature.editor(MAIL1, csrf)
    assert "Schreibresultat unklar" in page and page.count(" disabled>") == 3
    assert "readonly" in page and "Abbrechen" not in page and "Entwurf: Absage" in page
    source = web.store.load_model(f"mail-{MAIL1}", MailState)
    source.mail = None
    web.store.save(f"mail-{MAIL1}", source.model_dump(mode="json"))
    assert feature.editor(MAIL1, csrf) == ""


def test_briefing_and_filters_work_without_javascript(web):
    assert "Noch kein" in web.browser.request("GET", "/briefing").body.decode()
    web.store.save("briefing-latest", {"text": "<private>"})
    assert "&lt;private&gt;" in web.browser.request("GET", "/briefing").body.decode()
    assert web.browser.request("GET", "/offen?filter=invalid").status == 422
    assert "push-controls" in web.browser.request("GET", "/einstellungen").body.decode()
    with_mail(web.store, 1, extracted_attachments=[{"filename": "a.pdf"}])
    for path in ("/offen", "/mails", "/verlauf"):
        for value in ("", "events", "tasks", "clarification", "attachments", "duplicates"):
            response = web.browser.request("GET", path + "?filter=" + value)
            assert response.status == 200
            assert 'aria-label="Schnellfilter"' in response.body.decode()
    text = web.browser.request("GET", "/offen?filter=events").body.decode()
    assert f'id="v-{MAIL1}-elternabend"' in text and f'id="v-{MAIL1}-formular"' not in text
    assert web.browser.request("GET", "/mails?filter=unknown").status == 422


def test_analyzer_reply_uses_configured_prompt():
    from shared_core import prompt_config

    from mailhelp.analysis import Analyzer
    from mailhelp.config import PromptStep
    prompts = prompt_config()
    prompts.prompts["draft_reply"] = PromptStep(system_prompt="Untrusted input; only draft.")
    calls = []
    def complete(*args, **kw):
        calls.append((args, kw))
        return "call", {"text": "Danke!"}
    mail = {"headers": {"from": "Schule <a@test>", "subject": "Ausflug", "message_id": "<x@test>"},
            "text": "<mail>", "metadata": {"attachments_omitted": 1},
            "calendar_events": [{"summary": "Ausflug"}],
            "extracted_attachments": [
                {"filename": "plan.pdf", "text": " Ablauf ", "extraction_status": "success", "character_count": 6},
                {"filename": "scan.jpg", "text": "Gescannt", "extraction_status": "success", "vision": "read",
                 "preview": {"index": 1}},
                {"text": "ohne Namen"},
                {"filename": "leer.pdf", "text": " ", "extraction_status": "success"},
                {"filename": "kaputt.pdf", "text": "", "extraction_status": "error"},
                {"filename": "geheim.pdf", "extraction_status": "encrypted"}]}
    call, result = Analyzer(NS(complete=complete), prompts).draft_reply(mail, "question", "Max, Elternbeirat")
    assert (call, result.text) == ("call", "Danke!")
    assert calls[0][1]["stage"] == "draft_reply"
    # Intent, personal information and every recognized attachment text reach the
    # model exactly once; technical metadata does not.
    payload = calls[0][0][3]
    assert payload["intent"] == "question" and payload["personal_info"] == "Max, Elternbeirat"
    assert payload["mail"] == {
        "headers": {"from": "Schule <a@test>", "subject": "Ausflug", "date": ""}, "text": "<mail>",
        "attachments": [{"filename": "plan.pdf", "text": "Ablauf"}, {"filename": "scan.jpg", "text": "Gescannt"},
                        {"filename": "Anhang", "text": "ohne Namen"}],
        "calendar_events": [{"summary": "Ausflug"}]}
    Analyzer(NS(complete=complete), prompts).draft_reply({"headers": {}}, "accept")
    assert calls[1][0][3]["personal_info"] == "" and calls[1][0][3]["mail"]["attachments"] == []


def test_strict_briefing_calendar_query_propagates_failure():
    import httpx

    from mailhelp.integrations import HttpWriter
    writer = HttpWriter("google_calendar", "fake", "primary",
        calendar_timezone="UTC",
        transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    with pytest.raises(RetryableError): writer.fetch_events_in_window(datetime.now(UTC), datetime.now(UTC), strict=True)
    writer.close()


@pytest.mark.parametrize("mode", ["ssl", "starttls"])
def test_runtime_composes_services_and_ticks_without_external_io(web, tmp_path, monkeypatch, mode):
    from pydantic import SecretStr
    from shared_application import Log, settings

    from mailhelp.experience import ExperienceRuntime
    cfg = settings(tmp_path)
    cfg.push.enabled = cfg.smart_reply = cfg.daily_briefing.enabled = True
    cfg.daily_briefing.time = "00:00"
    cfg.imap.connection_mode = mode
    closed, sent, connections = [], [], []
    class Reader:
        def __init__(self, *args, **kwargs):
            connections.append(kwargs)
            self.connection = Connection()
        def close(self): closed.append(True)
    monkeypatch.setattr("mailhelp.experience.ImapReader", Reader)
    app = NS(settings=cfg, store=web.store, telegram=NS(send=lambda chat, text: sent.append(text)),
        calendar=NS(fetch_events_in_window=lambda *a, **kw: []), todoist=NS(fetch_active_tasks=lambda: []),
        analyzer=NS(draft_reply=lambda mail, intent, info: ("call", ReplyDraft(text="Danke")),
                    prompts=NS(prompts={"draft_reply": object()})), logger=Log())
    runtime = ExperienceRuntime(app, NS(site=web.site, auth=web.auth), NS(imap_username="me@test", imap_password=SecretStr("fake")))
    pushes = []
    web.site.experience.push.notify = lambda *a: pushes.append(a)
    runtime.tick()
    runtime.tick()
    assert pushes == [(), ("briefing",)] and len(sent) == 1 and sent[0].startswith("Guten Morgen!")
    session = web.auth.sessions()[0]
    assert web.store.load(f"draft-{MAIL1}") is None  # Drafts are generated only on request.
    web.site.experience.drafts.generate(session.id, MAIL1, 0, "gen-0001", "accept")
    result = web.site.experience.drafts.act(session.id, MAIL1, 1, "save-0001", "Danke")
    assert result["status"] == "simulated" and not connections
    web.site.experience.drafts.test_mode = False
    draft = web.store.load(f"draft-{MAIL1}")
    draft.update(status="editing", operations={})
    web.store.save(f"draft-{MAIL1}", draft)
    web.site.experience.drafts.act(session.id, MAIL1, 1, "save-0002", "Danke")
    assert closed == [True] and connections[0]["starttls"] == (mode == "starttls")
    runtime.stop()
    assert runtime.stop_event.is_set()
    runtime.stop_event.clear()
    def tick():
        runtime.stop_event.set()
        raise ValueError("private")
    runtime.tick = tick
    runtime.start()
    runtime.stop()
    assert app.logger.events[-1][1] == {"error_class": "ValueError"}
    runtime.stop_event.clear()
    runtime.tick = runtime.stop_event.set
    runtime.start()
    runtime.stop()


def test_standalone_config_loading_and_composition(tmp_path, monkeypatch, capsys):

    import yaml
    from shared_application import settings
    from shared_core import prompt_config

    from mailhelp.application import build_application
    from mailhelp.config import Secrets, load_all
    cfg = settings(tmp_path)
    cfg.telegram.enabled = False
    with pytest.raises(ValueError): Settings.model_validate(cfg.model_dump())
    cfg.web.enabled = True
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf8")
    (tmp_path / "prompts.yaml").write_text(yaml.safe_dump(prompt_config().model_dump(mode="json")), encoding="utf8")
    (tmp_path / "topics.yaml").write_text("topics:\n- id: x\n  name: x\n  enabled: true\n  description: x\n", encoding="utf8")
    env = {name.upper(): "synthetic" for name in Secrets.model_fields if name not in {"mailhelp_web_secret", "telegram_bot_token"}}
    env["MAILHELP_WEB_SECRET"] = "s" * 40
    loaded = load_all(tmp_path, env)
    assert loaded[1].telegram_bot_token.get_secret_value() == ""
    class Resource:
        def __init__(self, *a, **kw): pass
        def close(self): pass
    for name in ("ImapReader", "OpenRouterClient", "HttpWriter", "GoogleOAuthTokenProvider"):
        monkeypatch.setattr(("mailhelp.external.providers." if name in MOVED_WRITERS else "mailhelp.composition.") + name, Resource)
    with build_application(loaded[0], loaded[1], loaded[2], loaded[4], loaded[5], tmp_path, use_jev_relevance=False) as app:
        assert isinstance(app.telegram, DisabledTelegram)
        assert "Code:" not in capsys.readouterr().out
        assert app.store.load("web-pairing") is None
        # Further devices request their code on the login page; it appears in the console.
        auth = app.experience.site.auth
        assert auth.channel == "console"
        auth.request_code("n" * 32, "iPhone")
        assert "Mailhelp-Webanmeldung für „iPhone“: Code " in capsys.readouterr().out
        app.web = NS(start=lambda: None, stop=lambda: None)
        events = []
        app.experience = NS(start=lambda: events.append("start"), stop=lambda: events.append("stop"))
        app._start_web()
        app._stop_web()
        assert events == ["start", "stop"]


def test_retention_scrubs_draft_and_preview_together(tmp_path):
    from shared_retention import NOW, Log, state

    from mailhelp.config import RetentionSettings
    from mailhelp.retention import RetentionService
    store = JsonStore(tmp_path)
    item = state(MAIL1)
    store.save(f"mail-{MAIL1}", item.model_dump(mode="json"))
    store.save(f"draft-{MAIL1}", {"text": "Private", "version": 2, "status": "saved", "operations": {}})
    directory = AttachmentCache(store).directory(MAIL1)
    directory.mkdir(parents=True)
    (directory / "0.jpg").write_bytes(b"synthetic")
    RetentionService(store, RetentionSettings(), Log(), lambda: NOW).run()
    assert not directory.exists()
    assert store.load(f"draft-{MAIL1}")["text"] == ""
    assert store.load(f"draft-{MAIL1}")["status"] == "saved"


def test_preview_rejects_resolved_path_escape(tmp_path, monkeypatch):
    from pathlib import Path
    cache = AttachmentCache(JsonStore(tmp_path))
    resolve = Path.resolve
    monkeypatch.setattr(Path, "resolve", lambda self: tmp_path / "outside" if self.name == MAIL1 else resolve(self))
    with pytest.raises(ValueError): cache.directory(MAIL1)


def test_experience_settings_preserve_16_analysis_fingerprint(tmp_path):
    from shared_application import settings
    from shared_core import prompt_config

    from mailhelp.config import PromptStep
    from mailhelp.fingerprints import _hash, analysis_prompts, config_fingerprint
    cfg, prompts = settings(tmp_path), prompt_config()
    before = config_fingerprint(cfg, prompts, [])
    cfg.push.enabled = cfg.smart_reply = cfg.daily_briefing.enabled = True
    cfg.web.enabled = True
    cfg.telegram.enabled = False
    cfg.imap.drafts_folder = "Entwürfe"
    cfg.personal_info = "Max Mustermann"
    prompts.prompts["draft_reply"] = PromptStep(system_prompt="Draft")
    assert config_fingerprint(cfg, prompts, []) == before
    legacy = cfg.model_dump(mode="json")
    for name in ("push", "smart_reply", "personal_info", "activity_report", "notifications", "daily_briefing", "vision", "web", "metrics", "retention", "logging", "learning", "poll_interval_seconds", "timeouts", "retries"):
        legacy.pop(name)
    legacy["imap"].pop("drafts_folder")
    legacy["telegram"].pop("enabled")
    # 2.3 fields did not exist in 1.6 either.
    legacy.pop("attachments")
    legacy.pop("event_defaults")
    legacy.pop("proposal_reconciliation")
    for name in ("calendar_provider", "task_provider", "caldav_calendar_url", "caldav_task_url",
                 "outlook_calendar", "microsoft_todo_list", "microsoft_tenant"):
        legacy["targets"].pop(name)
    assert before == _hash([legacy, analysis_prompts(prompts), []])


def usable_from_another_thread(store):
    """The store lock is re-entrant, so only another thread can show that it is free."""
    from threading import Event, Thread
    done = Event()
    def use():
        with store.locked():
            done.set()
    Thread(target=use, daemon=True).start()
    return done.wait(timeout=5)


def test_push_delivery_holds_no_lock_and_keeps_a_device_renewed_meanwhile(tmp_path):
    """Regression: delivery ran under the global store lock and blocked the whole application."""
    store = JsonStore(tmp_path)
    renewed, response = sub(), requests.Response()
    response.status_code = 410
    def gone(**kw):
        # Pages and other services stay usable while a push provider answers slowly.
        assert not service._lock.locked()
        assert usable_from_another_thread(store)
        service.change("device", "key-0002", renewed)
        raise WebPushException("gone", response=response)
    service = PushService(store, NS(active=lambda _: True), "mailto:me@test", gone)
    service.change("device", "key-0001", sub())
    service.notify()
    assert store.load("push-subscriptions")["devices"]["device"] == renewed


def test_push_operation_log_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr("mailhelp.webpush.MAX_OPERATIONS", 2)
    store = JsonStore(tmp_path)
    service = PushService(store, NS(active=lambda _: True), "mailto:me@test", lambda **kw: None)
    for number in range(3):
        service.change("device", f"key-000{number}", sub())
    assert list(store.load("push-subscriptions")["operations"]) == ["device:key-0001", "device:key-0002"]


def test_draft_editor_explains_refusal_and_form_errors(web):
    feature = web.site.experience
    form = web.form("/", kind="confirm", proposal_id="formular")
    conn = Connection()
    conn.appended = "NO"
    feature.drafts = DraftService(web.store, web.auth.active, lambda: nullcontext(conn), "me@test", analyzer=Writer("Danke"))
    feature.drafts.generate(web.auth.sessions()[0].id, MAIL1, 0, "gen-0001", "accept")
    path = f"/mail/{MAIL1}/entwurf"
    payload = {"csrf": form["csrf"], "version": "1", "key": "key-0001", "text": "Danke", "mode": "save"}
    assert web.browser.request("POST", path, payload).status == 303
    assert "Der Mailserver hat das Speichern abgelehnt." in feature.editor(MAIL1, form["csrf"])
    for change, text in (({"version": "x"}, "Ungültige Entwurfsversion"), ({"text": "x" * 8001}, "1 bis 8000 Zeichen"),
                         ({"key": "bad"}, "Ungültige Identität")):
        response = web.browser.request("POST", path, {**payload, **change})
        assert response.status == 409 and text in response.body.decode()
    response = web.browser.request("POST", path, {key: value for key, value in payload.items() if key != "text"})
    assert response.status == 409 and "unvollständig" in response.body.decode()


def test_inbox_zero_summarizes_today_in_the_configured_zone(web, monkeypatch):
    site = web.site
    site.clock = lambda: datetime(2026, 10, 12, 22, 30, tzinfo=UTC)  # 00:30 in Berlin
    def row(pid, status, kind, at="2026-10-12T22:10:00+00:00"):
        return {"mail_id": MAIL1, "proposal_id": pid, "status": status, "proposal_kind": kind, "at": at,
                "version": 1, "source": "web", "kind": "decision", "title": "x"}
    rows = [row("a", "pending_confirmation", "event", "2026-10-12T22:00:00+00:00"), row("a", "created", "event"),
            row("b", "simulated", "task"), row("c", "already_exists", "event"), row("d", "rejected", "task"),
            row("e", "created", "event", "2026-10-12T21:00:00+00:00"),  # yesterday in Berlin
            row("f", "failed", "task"), row("", "irrelevant", "")]
    monkeypatch.setattr(site.archive.queries, "history", lambda: rows)
    html = site.experience.inbox_zero()
    assert ("Heute 4 Vorgänge verarbeitet: 1 Termin angelegt, 1 Aufgabe angelegt, "
            "1 Duplikat vorab abgeglichen, 1 Vorschlag verworfen.") in html
    assert "Letzte verarbeitete Mail: " in html and "noch keine" not in html
    monkeypatch.setattr(site.archive.queries, "history", lambda: [row("a", "created", "event"), row("b", "created", "event")])
    assert "Heute 2 Vorgänge verarbeitet: 2 Termine angelegt." in site.experience.inbox_zero()
    monkeypatch.setattr(site.archive.queries, "history", lambda: [])
    monkeypatch.setattr(site.views, "system", lambda now: NS(last_processed=None))
    html = site.experience.inbox_zero()
    assert "Heute noch keine Vorgänge abgeschlossen." in html and "noch keine" in html


def test_detail_page_discloses_evidence_revisions_and_analysis(web, monkeypatch):
    page = web.browser.request("GET", f"/vorschlag/{MAIL1}/elternabend").body.decode()
    assert '<details class="disclosure"><summary>Quellbeleg aus E-Mail / Anhang</summary>' in page
    assert "<summary>Revisionshistorie &amp; Differenzen</summary>" in page
    assert "<summary>Technische LLM-Analyse &amp; Metriken</summary>" in page
    assert "Noch keine Revisionen erfasst." in page
    rows = [{"mail_id": MAIL1, "proposal_id": "elternabend", "version": v, "at": f"2026-10-0{v}T10:00:00+00:00",
             "status": "pending_confirmation", "source": "system"} for v in (1, 2)]
    rows.append({**rows[0], "proposal_id": "formular"})
    monkeypatch.setattr(web.site.archive.queries, "history", lambda: rows)
    page = web.browser.request("GET", f"/vorschlag/{MAIL1}/elternabend").body.decode()
    assert page.index(f"/vorschlag/{MAIL1}/elternabend/version/2") < page.index(f"/vorschlag/{MAIL1}/elternabend/version/1")
    assert "/formular/version" not in page
    # Image previews are the evidence to compare with: the section opens itself.
    raw = mail(("scan.png", "image", "png", image_bytes(Image.new("RGB", (300, 200)))))
    entries = [{"filename": "scan.png"}]
    AttachmentCache(web.store).prepare(MAIL1, raw, entries)
    assert entries[0]["preview"]["width"] == 300 and entries[0]["preview"]["height"] == 200
    with_mail(web.store, 1, extracted_attachments=entries)
    page = web.browser.request("GET", f"/vorschlag/{MAIL1}/elternabend").body.decode()
    assert '<details class="disclosure" open><summary>Quellbeleg' in page
    assert "scan.png · 300 × 200 px · " in page and "Kein erkannter Text gespeichert." in page
    # Previews cached before 2.0 metadata existed still render.
    with_mail(web.store, 1, extracted_attachments=[{"filename": "alt.png", "text": "Text",
                                                    "preview": {"index": 0, "size_bytes": 10}}])
    page = web.browser.request("GET", f"/vorschlag/{MAIL1}/elternabend").body.decode()
    assert "alt.png · 1 KB" in page and "Erkannten Text anzeigen" in page


def test_runtime_without_optional_features_only_keeps_the_local_briefing(web, tmp_path):
    from shared_application import Log, settings

    from mailhelp.experience import ExperienceRuntime
    cfg = settings(tmp_path)
    cfg.web.enabled, cfg.telegram.enabled = True, False
    cfg.daily_briefing.enabled, cfg.daily_briefing.time = True, "00:00"
    cfg.daily_briefing.include_calendar = cfg.daily_briefing.include_tasks = False
    app = NS(settings=cfg, store=web.store, logger=Log(), calendar=None, todoist=None,
             telegram=NS(send=lambda *a: pytest.fail("Telegram is switched off")))
    runtime = ExperienceRuntime(app, NS(site=web.site, auth=web.auth), None)
    assert web.site.experience.push is None and web.site.experience.drafts is None
    assert list(runtime.briefing.channels) == ["local"]
    runtime.tick()
    assert web.store.load("push-decisions") is None and web.store.names("draft-") == []
    assert "Entscheidungen warten auf dich." in web.store.load("briefing-latest")["text"]
    assert web.store.load("daily-briefing")["channels"] == {"local": "sent"}


def test_login_page_names_the_console_without_telegram():
    from mailhelp.web.pages import login_page
    first = login_page("csrf", False, channel="console")
    assert "Code in der Konsole anzeigen" in first and "Telegram" not in first
    requested = login_page("csrf", True, channel="console")
    assert "Code aus der Mailhelp-Konsole" in requested and "docker compose exec mailhelp mailhelp --pair" in requested
    assert "Telegram" not in requested and "Code per Telegram senden" in login_page("csrf", False)


def test_background_never_calls_the_model_for_drafts_and_sections_stay_isolated(web, tmp_path):
    """Drafts cost one LLM call per click only; the minute scheduler never creates one."""
    from shared_application import Log, settings

    from mailhelp.experience import ExperienceRuntime
    cfg = settings(tmp_path)
    cfg.smart_reply = cfg.daily_briefing.enabled = True
    cfg.daily_briefing.time = "00:00"
    cfg.daily_briefing.include_calendar = cfg.daily_briefing.include_tasks = False
    app = NS(settings=cfg, store=web.store, logger=Log(), calendar=None, todoist=None,
             telegram=NS(send=lambda *a: None),
             analyzer=NS(draft_reply=lambda *a: pytest.fail("no background draft"),
                         prompts=NS(prompts={"draft_reply": object()})))
    runtime = ExperienceRuntime(app, NS(site=web.site, auth=web.auth),
                                NS(imap_username="me@test", imap_password=None))
    assert web.site.experience.drafts.analyzer is app.analyzer
    # The personal information is read on every click, so a live change applies at once.
    assert web.site.experience.drafts.personal_info() == ""
    app.settings = cfg.model_copy(update={"personal_info": "Max Mustermann"})
    assert web.site.experience.drafts.personal_info() == "Max Mustermann"
    runtime.tick()
    assert web.store.names("draft-") == [] and web.store.load("briefing-latest") is not None
    # A section failure is logged and does not stop the scheduler.
    web.store.save("daily-briefing", {"day": "2000-01-01", "channels": {}})
    runtime.briefing.views = NS(overview=lambda: (_ for _ in ()).throw(OSError()))
    runtime.tick()
    assert [event[0][2] for event in app.logger.events][-1] == "briefing_failed"


def test_drafts_stay_off_without_the_prompt(web, tmp_path):
    from shared_application import Log, settings

    from mailhelp.experience import ExperienceRuntime
    cfg = settings(tmp_path)
    cfg.smart_reply = True
    app = NS(settings=cfg, store=web.store, logger=Log(), calendar=None, todoist=None,
             telegram=NS(send=lambda *a: None), analyzer=NS(prompts=NS(prompts={})))
    ExperienceRuntime(app, NS(site=web.site, auth=web.auth), None)
    assert web.site.experience.drafts is None


def test_push_section_failure_is_logged(web, tmp_path):
    from shared_application import Log, settings

    from mailhelp.experience import ExperienceRuntime
    cfg = settings(tmp_path)
    cfg.push.enabled = True
    app = NS(settings=cfg, store=web.store, logger=Log(), calendar=None, todoist=None,
             telegram=NS(send=lambda *a: None), analyzer=NS(prompts=NS(prompts={})))
    runtime = ExperienceRuntime(app, NS(site=web.site, auth=web.auth), None)
    web.site.experience.push.notify = lambda *a: (_ for _ in ()).throw(OSError("provider"))
    runtime.tick()
    assert app.logger.events[-1] == (("WARNING", "experience", "push_failed"), {"error_class": "OSError"})


def test_push_operations_are_bounded_per_device(tmp_path, monkeypatch):
    # Decision (Planung 2.1, 5.3): every device keeps its own recent keys; a busy
    # device no longer evicts another device's keys from one shared list.
    monkeypatch.setattr("mailhelp.webpush.MAX_OPERATIONS", 2)
    store = JsonStore(tmp_path)
    service = PushService(store, NS(active=lambda _: True), "mailto:me@test", lambda **kw: None)
    service.change("phone", "key-phone-0", sub())
    for number in range(3):
        service.change("laptop", f"key-lap-{number}", sub())
    operations = set(store.load("push-subscriptions")["operations"])
    assert operations == {"phone:key-phone-0", "laptop:key-lap-1", "laptop:key-lap-2"}
    # The phone's replay with other content is still recognized as a conflict.
    with pytest.raises(ValueError, match="Idempotenzkonflikt"):
        service.change("phone", "key-phone-0", None)


def test_briefing_is_still_sent_after_a_late_start(tmp_path):
    # Decision (Planung 2.1, 5.1): a start long after the configured time (07:30)
    # still sends today's overview once; there is deliberately no time window.
    store = JsonStore(tmp_path)
    sent = []
    late = datetime(2026, 10, 25, 22, 30, tzinfo=UTC)  # 23:30 in Berlin
    svc = DailyBriefingService(
        store, DailyBriefingSettings(enabled=True, include_calendar=False, include_tasks=False),
        "Europe/Berlin", None, None, NS(overview=lambda: NS(open=[], relevance=[])),
        {"telegram": sent.append}, lambda: late)
    svc.tick()
    svc.tick()
    assert len(sent) == 1 and store.load("daily-briefing")["day"] == "2026-10-25"
