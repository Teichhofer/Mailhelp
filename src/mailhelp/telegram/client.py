"""Telegram HTTP transport and API error handling."""

from __future__ import annotations

import time
import traceback
import uuid
from typing import Any, Protocol

import httpx
from pydantic import ValidationError

from ..adapter import PermanentError, RetryPolicy, uncertain_write
from ..logging import NullLogger

from .formatting import split_message
from .callbacks import validate_callback_markup
from .models import (
    TelegramBotResponse,
    TelegramUpdate,
    TelegramUpdatesResponse,
    TelegramWriteResponse,
)


class TelegramChatNotFoundError(PermanentError):
    """The configured Telegram chat cannot be addressed by this bot."""


class TelegramClient:
    _CHAT_NOT_FOUND_HELP = (
        "Telegram {operation}: Chat nicht erreichbar. Bitte den Bot im Zielchat "
        "zuerst mit /start starten, die numerische telegram.chat_id prüfen und "
        "bei Gruppen sicherstellen, dass der Bot Mitglied ist"
    )
    _EXPIRED_CALLBACK_DESCRIPTION = "bad request: query is too old and response timeout expired or query id is invalid"

    def __init__(
        self,
        token: str,
        timeout: float,
        transport: httpx.BaseTransport | None = None,
        poll_timeout: int = 30,
        policy: RetryPolicy | None = None,
        logger: EventLogger | None = None,
    ):
        self.poll_timeout = poll_timeout
        self.client = httpx.Client(
            base_url=f"https://api.telegram.org/bot{token}",
            timeout=timeout,
            transport=transport,
        )
        self.policy = policy or RetryPolicy(0, 0, 0, lambda _delay: False)
        self.logger = logger or NullLogger()

    def _log_message(self, direction: str, **context: Any) -> None:
        """Keep third-party logger implementations backward compatible."""
        record = getattr(self.logger, "telegram_event", None)
        if record is not None:
            record(direction, **context)

    def check_access(self) -> None:
        """Validate the bot token without reading updates."""
        response = self.policy.run(lambda: self.client.get("/getMe"))
        self._raise_for_status(response, "getMe")
        self._raise_api_error(response, "getMe")
        try:
            TelegramBotResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise ValueError(
                f"Telegram getMe: ungültige Antwort am Schlüsselpfad {_validation_path(exc)}"
            ) from exc

    def started_chats(self, user_id: int) -> list[int]:
        """Return chats in which the configured user most recently sent /start.

        This is used only after an access check failed.  Filtering locally by the
        configured user prevents diagnostics from disclosing unrelated bot users.
        """
        response = self.policy.run(
            lambda: self.client.get(
                "/getUpdates",
                params={"timeout": 0, "allowed_updates": '["message"]'},
            )
        )
        self._raise_for_status(response, "getUpdates")
        self._raise_api_error(response, "getUpdates")
        try:
            parsed = TelegramUpdatesResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise ValueError(
                f"Telegram getUpdates: ungültige Antwort am Schlüsselpfad {_validation_path(exc)}"
            ) from exc
        chats = set()
        for item in parsed.result:
            if not isinstance(item, TelegramUpdate):
                continue
            if (
                item.message is not None
                and item.message.sender.id == user_id
                and item.message.text.partition("@")[0] == "/start"
            ):
                chats.add(item.message.chat.id)
        return sorted(chats)

    def poll(self, offset: int, timeout: int | None = None) -> list[dict[str, Any]]:
        call_id, started = str(uuid.uuid4()), time.perf_counter()
        self.logger.event(
            "INFO", "telegram", "poll_started", call_id=call_id, offset=offset
        )

        def request() -> httpx.Response:
            response = self.client.get(
                "/getUpdates",
                params={
                    "offset": offset,
                    "timeout": self.poll_timeout if timeout is None else timeout,
                    "allowed_updates": '["message","callback_query"]',
                },
            )
            self._raise_for_status(response, "getUpdates")
            return response

        try:
            response = self.policy.run(
                request,
                lambda attempt: self.logger.event(
                    "DEBUG",
                    "telegram",
                    "poll_attempt",
                    call_id=call_id,
                    attempt=attempt,
                ),
                lambda attempt, exc: self.logger.event(
                    "WARNING",
                    "telegram",
                    "poll_retry",
                    call_id=call_id,
                    attempt=attempt,
                    error=exc,
                ),
            )
        except Exception as exc:
            self.logger.event(
                "ERROR",
                "telegram",
                "poll_failed",
                call_id=call_id,
                error=exc,
                stacktrace=traceback.format_exc(),
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )
            raise
        self._raise_api_error(response, "getUpdates")
        try:
            parsed = TelegramUpdatesResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise ValueError(
                f"Telegram getUpdates: ungültige Antwort am Schlüsselpfad {_validation_path(exc)}"
            ) from exc
        result = [
            item.model_dump(by_alias=True) if isinstance(item, TelegramUpdate) else item
            for item in parsed.result
        ]
        for item in parsed.result:
            if not isinstance(item, TelegramUpdate):
                continue
            if item.message is not None:
                self._log_message(
                    "received",
                    update_id=item.update_id,
                    message_id=item.message.message_id,
                    user_id=item.message.sender.id,
                    chat_id=item.message.chat.id,
                    text=item.message.text,
                )
            else:
                callback = item.callback_query
                assert callback is not None
                self._log_message(
                    "received",
                    update_id=item.update_id,
                    message_id=callback.message.message_id,
                    user_id=callback.sender.id,
                    chat_id=callback.message.chat.id,
                    callback_data=callback.data,
                )
        self.logger.event(
            "INFO",
            "telegram",
            "poll_completed",
            call_id=call_id,
            count=len(result),
            status=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        return result

    def send(
        self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None
    ) -> None:
        validate_callback_markup(reply_markup)
        call_id = str(uuid.uuid4())
        self.logger.event("INFO", "telegram", "send_started", call_id=call_id)
        parts = split_message(text)
        for index, part in enumerate(parts):
            payload: dict[str, Any] = {"chat_id": chat_id, "text": part}
            if reply_markup is not None and index == len(parts) - 1:
                payload["reply_markup"] = reply_markup

            def request() -> httpx.Response:
                response = self.client.post("/sendMessage", json=payload)
                self._raise_for_status(response, "sendMessage")
                return response

            response = uncertain_write(request)
            self._validate_write(response, "sendMessage")
            self._log_message(
                "sent",
                chat_id=chat_id,
                text=part,
                reply_markup=payload.get("reply_markup"),
            )
        self.logger.event(
            "INFO", "telegram", "send_completed", call_id=call_id, parts=len(parts)
        )

    def send_document(
        self, chat_id: int, filename: str, content: bytes, caption: str | None = None
    ) -> None:
        """Send a generated file without ever placing its contents in a log."""
        if not filename or any(
            character in filename for character in ("/", "\\", "\x00")
        ):
            raise ValueError("Telegram-Dateiname ist ungültig")
        call_id = str(uuid.uuid4())
        self.logger.event(
            "INFO",
            "telegram",
            "document_send_started",
            call_id=call_id,
            filename=filename,
            size=len(content),
        )

        def request() -> httpx.Response:
            data: dict[str, Any] = {"chat_id": str(chat_id)}
            if caption is not None:
                data["caption"] = caption
            response = self.client.post(
                "/sendDocument",
                data=data,
                files={"document": (filename, content, "text/calendar; charset=utf-8")},
            )
            self._raise_for_status(response, "sendDocument")
            return response

        response = uncertain_write(request)
        self._validate_write(response, "sendDocument")
        self._log_message(
            "sent",
            chat_id=chat_id,
            message_type="document",
            filename=filename,
            caption=caption,
        )
        self.logger.event(
            "INFO",
            "telegram",
            "document_send_completed",
            call_id=call_id,
            filename=filename,
            size=len(content),
        )

    def answer_callback(self, callback_id: str, text: str) -> None:
        def request() -> httpx.Response:
            response = self.client.post(
                "/answerCallbackQuery",
                json={"callback_query_id": callback_id, "text": text},
            )
            if not self._is_expired_callback(response):
                self._raise_for_status(response, "answerCallbackQuery")
            return response

        response = uncertain_write(request)
        if self._is_expired_callback(response):
            # Telegram callback acknowledgements have a short lifetime.  The
            # update itself is still final and must be checkpointed; otherwise
            # this obsolete query is returned forever and blocks newer input.
            self.logger.event("WARNING", "telegram", "callback_acknowledgement_expired")
            return
        self._validate_write(response, "answerCallbackQuery")
        self._log_message(
            "sent",
            message_type="callback_answer",
            callback_id=callback_id,
            text=text,
        )

    def remove_inline_keyboard(self, chat_id: int, message_id: int) -> None:
        """Remove every inline button from an already-sent message."""
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": {"inline_keyboard": []},
        }

        def request() -> httpx.Response:
            response = self.client.post("/editMessageReplyMarkup", json=payload)
            self._raise_for_status(response, "editMessageReplyMarkup")
            return response

        response = uncertain_write(request)
        self._validate_write(response, "editMessageReplyMarkup")

    @staticmethod
    def _is_expired_callback(response: httpx.Response) -> bool:
        description = TelegramClient._description(response)
        return (
            response.status_code == 400
            and description is not None
            and description.casefold() == TelegramClient._EXPIRED_CALLBACK_DESCRIPTION
        )

    @staticmethod
    def _validate_write(response: httpx.Response, operation: str) -> None:
        TelegramClient._raise_api_error(response, operation)
        try:
            TelegramWriteResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise ValueError(
                f"Telegram {operation}: ungültige Antwort am Schlüsselpfad {_validation_path(exc)}"
            ) from exc

    @staticmethod
    def _description(response: httpx.Response) -> str | None:
        """Read only Telegram's documented human-readable error field."""
        try:
            payload = response.json()
        except ValueError:
            return None
        if not isinstance(payload, dict):
            return None
        description = payload.get("description")
        return description if isinstance(description, str) and description else None

    @staticmethod
    def _error_detail(response: httpx.Response, operation: str) -> str | None:
        """Turn Telegram's safe description into an actionable diagnostic."""
        description = TelegramClient._description(response)
        if description is None:
            return None
        if description.casefold() == "bad request: chat not found":
            return TelegramClient._CHAT_NOT_FOUND_HELP.format(operation=operation)
        return f"Telegram {operation}: {description}"

    @staticmethod
    def _raise_for_status(response: httpx.Response, operation: str) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = TelegramClient._error_detail(response, operation)
            if detail is not None:
                # Retry code consumes this explicit safe field instead of rendering
                # the exception URL, because that URL contains the bot token.
                exc.safe_detail = detail
                if detail == TelegramClient._CHAT_NOT_FOUND_HELP.format(
                    operation=operation
                ):
                    raise TelegramChatNotFoundError(
                        f"Permanente Adapterantwort: {detail}"
                    ) from exc
            raise

    @staticmethod
    def _raise_api_error(response: httpx.Response, operation: str) -> None:
        try:
            payload = response.json()
        except ValueError:
            return
        if isinstance(payload, dict) and payload.get("ok") is False:
            detail = TelegramClient._error_detail(response, operation)
            if detail is not None:
                if detail == TelegramClient._CHAT_NOT_FOUND_HELP.format(
                    operation=operation
                ):
                    raise TelegramChatNotFoundError(
                        f"Permanente Adapterantwort: {detail}"
                    )
                raise PermanentError(f"Permanente Adapterantwort: {detail}")

    def close(self) -> None:
        self.client.close()


def _validation_path(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return ", ".join(
            ".".join(str(part) for part in item["loc"]) or "<root>"
            for item in exc.errors(include_input=False)
        )
    return "<json>"


class TelegramTransport(Protocol):
    def poll(self, offset: int, timeout: int | None = None) -> list[dict[str, Any]]: ...
    def send(
        self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None
    ) -> None: ...
    def answer_callback(self, callback_id: str, text: str) -> None: ...
    def remove_inline_keyboard(self, chat_id: int, message_id: int) -> None: ...
