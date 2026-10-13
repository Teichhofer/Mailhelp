"""Explicitly disabled Telegram transport; the web command inbox remains active."""

from __future__ import annotations

from threading import Event
from typing import Any


class DisabledTelegram:
    def __init__(self) -> None:
        self.stopped = Event()

    def send(self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None) -> None:
        return None

    def check_access(self) -> None:
        return None

    def started_chats(self, user_id: int) -> list[int]:
        return []

    def poll(self, offset: int, timeout: int | None = None) -> list[dict[str, Any]]:
        self.stopped.wait(30 if timeout is None else timeout)
        return []

    def answer_callback(self, callback_id: str, text: str) -> None:
        # Without Telegram no button can be pressed; the receiver contract still holds.
        return None

    def close(self) -> None:
        self.stopped.set()
