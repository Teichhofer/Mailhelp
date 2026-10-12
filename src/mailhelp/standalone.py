"""Explicitly disabled Telegram transport; the web command inbox remains active."""

from __future__ import annotations

from threading import Event


class DisabledTelegram:
    def __init__(self):
        self.stopped = Event()

    def send(self, chat_id, text, reply_markup=None):
        return None

    def check_access(self):
        return None

    def poll(self, offset, timeout=None):
        self.stopped.wait(30 if timeout is None else timeout)
        return []

    def close(self):
        self.stopped.set()
