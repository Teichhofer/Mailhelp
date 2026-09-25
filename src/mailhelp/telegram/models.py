"""Validated Telegram transport models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


__all__ = [
    "InternalTelegramModel",
    "TelegramBot",
    "TelegramBotResponse",
    "TelegramCallbackQuery",
    "TelegramChat",
    "TelegramMessage",
    "TelegramTransportModel",
    "TelegramUpdate",
    "TelegramUpdatesResponse",
    "TelegramUser",
    "TelegramWriteResponse",
    "TelegramWriteResult",
]


class TelegramTransportModel(BaseModel):
    """Validated Telegram fields used by Mailhelp; API additions are discarded."""

    model_config = ConfigDict(extra="ignore", strict=True, populate_by_name=True)


class InternalTelegramModel(BaseModel):
    """Closed model for decisions that can affect Mailhelp's persisted state."""

    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)


class TelegramUser(TelegramTransportModel):
    id: int


class TelegramChat(TelegramTransportModel):
    id: int


class TelegramMessage(TelegramTransportModel):
    message_id: int
    sender: TelegramUser = Field(alias="from")
    chat: TelegramChat
    text: str = Field(min_length=1, max_length=4096)


class TelegramCallbackQuery(TelegramTransportModel):
    id: str = Field(min_length=1, max_length=128)
    sender: TelegramUser = Field(alias="from")
    message: TelegramMessage
    data: str = Field(min_length=1, max_length=64)


class TelegramUpdate(TelegramTransportModel):
    update_id: int = Field(ge=0)
    message: TelegramMessage | None = None
    callback_query: TelegramCallbackQuery | None = None

    @model_validator(mode="after")
    def exactly_one_payload(self) -> "TelegramUpdate":
        if (self.message is None) == (self.callback_query is None):
            raise ValueError(
                "Update muss genau eine Nachricht oder Callback-Query enthalten"
            )
        return self


class TelegramUpdatesResponse(TelegramTransportModel):
    ok: bool
    # Telegram may return update kinds this application does not subscribe to
    # (in particular updates queued before allowed_updates was changed).  Keep
    # the envelope strict, but validate each update independently in the dialog
    # controller so one unrelated update cannot block every later reply.
    result: list[TelegramUpdate | dict[str, Any]]

    @model_validator(mode="after")
    def successful(self) -> "TelegramUpdatesResponse":
        if not self.ok:
            raise ValueError("Telegram meldet keinen Erfolg")
        if any(
            isinstance(item, dict) and ({"message", "callback_query"} & item.keys())
            for item in self.result
        ):
            raise ValueError("Telegram-Update mit unterstütztem Typ ist ungültig")
        return self


class TelegramWriteResult(TelegramTransportModel):
    message_id: int | None = None


class TelegramWriteResponse(TelegramTransportModel):
    ok: bool
    result: TelegramWriteResult | bool

    @model_validator(mode="after")
    def successful(self) -> "TelegramWriteResponse":
        if not self.ok:
            raise ValueError("Telegram meldet keinen Erfolg")
        return self


class TelegramBot(TelegramTransportModel):
    id: int
    is_bot: bool
    username: str | None = None


class TelegramBotResponse(TelegramTransportModel):
    ok: bool
    result: TelegramBot

    @model_validator(mode="after")
    def successful(self) -> "TelegramBotResponse":
        if not self.ok or not self.result.is_bot:
            raise ValueError("Telegram meldet keinen gültigen Bot")
        return self
