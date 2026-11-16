"""The Telegram client: API validation, callbacks, start chats and documents."""
from __future__ import annotations

import httpx
import pytest

from mailhelp.llm.adapter import PermanentError, UncertainWriteError
from mailhelp.persistence.storage import JsonStore
from mailhelp.telegram import (
    Decision,
    DecisionAction,
    TelegramChatNotFoundError,
    TelegramClient,
    TelegramDialogController,
)
from tests.fakes.log_fakes import RecordingLogger as Logger
from tests.fakes.shared_telegram_dialog import (
    OperationallyFailingRevisionService as OperationallyFailingRevisionService,
)
from tests.fakes.shared_telegram_dialog import (
    callback,
    message,
    proposal,
)


def test_telegram_client_validation_and_callback():
    requests=[]
    def handler(request):
        requests.append(request)
        data={"ok":True,"result":[]} if request.url.path.endswith("getUpdates") else {"ok":True,"result":True}
        return httpx.Response(200,json=data,request=request)
    client=TelegramClient("secret",1,httpx.MockTransport(handler))
    assert client.poll(0)==[]
    client.send(2,"x",{"inline_keyboard":[]})
    client.answer_callback("c","ok")
    client.remove_inline_keyboard(2, 7)
    client.close()
    assert len(requests)==4
    assert requests[-1].url.path.endswith("editMessageReplyMarkup")
    assert requests[-1].read() == b'{"chat_id":2,"message_id":7,"reply_markup":{"inline_keyboard":[]}}'
    assert requests[0].url.params["allowed_updates"] == '["message","callback_query"]'
    invalid=TelegramClient("secret",1,httpx.MockTransport(lambda r:httpx.Response(200,json={"ok":True,"result":{}},request=r)))
    with pytest.raises(ValueError): invalid.poll(0)
    invalid.close()


def test_expired_callback_acknowledgement_does_not_block_update_checkpoint(tmp_path):
    item = proposal()
    decision = Decision(mail_id=item.source_mail_id, proposal_id=item.id, version=1,
                        action=DecisionAction.REJECT)
    events = Logger()

    def handler(request):
        if request.url.path.endswith("getUpdates"):
            return httpx.Response(200, json={"ok": True, "result": [
                callback(7, decision.encode())
            ]}, request=request)
        if request.url.path.endswith("editMessageReplyMarkup") or request.url.path.endswith("sendMessage"):
            return httpx.Response(200, json={"ok": True, "result": True}, request=request)
        return httpx.Response(400, json={
            "ok": False,
            "error_code": 400,
            "description": (
                "Bad Request: query is too old and response timeout expired "
                "or query ID is invalid"
            ),
        }, request=request)

    client = TelegramClient("secret", 1, httpx.MockTransport(handler), logger=events)
    with JsonStore(tmp_path) as store:
        dialog = TelegramDialogController(store, client, 1, 2, events)
        dialog.persist(item)
        dialog.poll_once()
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"] == "rejected"
        assert store.load("telegram-offset")["offset"] == 8
        assert any(entry[0][2] == "callback_acknowledgement_expired"
                   for entry in events.events)
    client.close()


def test_only_exact_expired_callback_error_is_ignored():
    def rejected(request):
        return httpx.Response(400, json={
            "ok": False, "error_code": 400,
            "description": "Bad Request: query ID is invalid",
        }, request=request)

    client = TelegramClient("secret", 1, httpx.MockTransport(rejected))
    with pytest.raises(PermanentError, match="query ID is invalid"):
        client.answer_callback("c", "ok")
    client.close()


def test_started_chats_ignores_unrelated_update_kind():
    payload = {"ok": True, "result": [
        {"update_id": 1, "my_chat_member": {"status": "member"}},
        message(2, "/start", user=1, chat=7),
    ]}
    client = TelegramClient("secret", 1, httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload, request=request)))
    assert client.started_chats(1) == [7]
    client.close()


def test_telegram_client_preserves_documented_api_error_description():
    def rejected(request):
        return httpx.Response(400,json={"ok":False,"error_code":400,"description":"Bad Request: chat not found"},request=request)
    client=TelegramClient("top-secret",1,httpx.MockTransport(rejected))
    with pytest.raises(PermanentError) as error:
        client.send(2,"x")
    assert str(error.value) == (
        "Permanente Adapterantwort: Telegram sendMessage: Chat nicht erreichbar. "
        "Bitte den Bot im Zielchat zuerst mit /start starten, die numerische "
        "telegram.chat_id prüfen und bei Gruppen sicherstellen, dass der Bot Mitglied ist"
    )
    assert "top-secret" not in str(error.value)
    client.close()


def test_telegram_client_finds_only_configured_users_start_chats():
    payload = {"ok": True, "result": [
        {"update_id": 1, "message": {"message_id": 1, "from": {"id": 42},
         "chat": {"id": 42}, "text": "/start"}},
        {"update_id": 2, "message": {"message_id": 2, "from": {"id": 42},
         "chat": {"id": -100}, "text": "/start@mailhelp_bot"}},
        {"update_id": 3, "message": {"message_id": 3, "from": {"id": 7},
         "chat": {"id": 7}, "text": "/start"}},
        {"update_id": 4, "message": {"message_id": 4, "from": {"id": 42},
         "chat": {"id": 42}, "text": "hello"}},
    ]}
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=payload, request=request)
    client = TelegramClient("secret", 1, httpx.MockTransport(handler))

    assert client.started_chats(42) == [-100, 42]
    assert seen[0].url.params["timeout"] == "0"
    assert seen[0].url.params["allowed_updates"] == '["message"]'
    client.close()


def test_telegram_started_chat_diagnostic_validates_api_response():
    for status, payload, error in (
        (200, {"wrong": True}, ValueError),
        (200, {"ok": False, "result": []}, ValueError),
        (400, {"ok": False, "description": "Bad Request: chat not found"},
         TelegramChatNotFoundError),
    ):
        client = TelegramClient(
            "secret", 1,
            httpx.MockTransport(lambda request, s=status, p=payload:
                                httpx.Response(s, json=p, request=request)),
        )
        with pytest.raises(error):
            client.started_chats(42)
        client.close()


def test_telegram_client_preserves_retryable_and_http_success_api_errors():
    responses=iter([
        (500,{"ok":False,"description":"Internal Server Error: try later"}),
        (200,{"ok":False,"error_code":400,"description":"Bad Request: message is too long"}),
        (200,{"ok":False,"error_code":400,"description":"Bad Request: chat not found"}),
    ])
    def rejected(request):
        status_code,payload=next(responses)
        return httpx.Response(status_code,json=payload,request=request)
    client=TelegramClient("secret",1,httpx.MockTransport(rejected))
    with pytest.raises(UncertainWriteError,match="Telegram sendMessage: Internal Server Error: try later"):
        client.send(2,"x")
    with pytest.raises(PermanentError,match="Telegram sendMessage: Bad Request: message is too long"):
        client.send(2,"x")
    with pytest.raises(PermanentError, match="Chat nicht erreichbar"):
        client.send(2,"x")
    client.close()


def test_telegram_error_description_boundary_rejects_unusable_fields():
    request=httpx.Request("POST","https://example.test")
    invalid_json=httpx.Response(400,content=b"not-json",request=request)
    list_json=httpx.Response(400,json=["description"],request=request)
    wrong_description=httpx.Response(400,json={"ok":False,"description":42},request=request)
    assert TelegramClient._description(invalid_json) is None
    assert TelegramClient._description(list_json) is None
    assert TelegramClient._description(wrong_description) is None
    with pytest.raises(httpx.HTTPStatusError) as error:
        TelegramClient._raise_for_status(wrong_description,"sendMessage")
    assert not hasattr(error.value,"safe_detail")
    TelegramClient._raise_api_error(invalid_json,"sendMessage")
    TelegramClient._raise_api_error(list_json,"sendMessage")
    TelegramClient._raise_api_error(wrong_description,"sendMessage")


def test_telegram_client_sends_calendar_document_and_validates_filename():
    requests=[]
    def handler(request):
        requests.append(request)
        return httpx.Response(200,json={"ok":True,"result":{"message_id":7}},request=request)
    client=TelegramClient("secret",1,httpx.MockTransport(handler))
    client.send_document(2,"termin.ics",b"BEGIN:VCALENDAR\r\n",caption="Import")
    client.send_document(2,"termin-ohne-text.ics",b"BEGIN:VCALENDAR\r\n")
    assert requests[0].url.path.endswith("/sendDocument")
    assert b'text/calendar' in requests[0].content and b'termin.ics' in requests[0].content
    with pytest.raises(ValueError,match="Dateiname"):
        client.send_document(2,"../termin.ics",b"x")
    with pytest.raises(ValueError,match="Dateiname"):
        client.send_document(2,"",b"x")
    client.close()
