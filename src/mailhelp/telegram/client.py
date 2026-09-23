"""Telegram HTTP transport and API error handling."""

from ._core import TelegramChatNotFoundError, TelegramClient, _validation_path

__all__ = ["TelegramChatNotFoundError", "TelegramClient", "_validation_path"]
