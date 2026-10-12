"""Typed read view of a prepared mail (``MailState.mail``).

The prepared mail stays stored and sent to the language model exactly as
``mime.prepare`` built it: its JSON is part of the state files and of every
analysis request, including the key order.  These models therefore only *read*
it.  ``extra="allow"`` keeps fields of older or newer releases readable, and
every field missing in an old state gets a neutral default instead of failing.
"""
from __future__ import annotations

from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    ValidatorFunctionWrapHandler,
    field_validator,
)


class _ReadModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    @field_validator("*", mode="wrap")
    @classmethod
    def _unusable_is_absent(cls, value: Any, handler: ValidatorFunctionWrapHandler, info: ValidationInfo) -> Any:
        """A damaged optional value reads as absent instead of hiding the whole mail."""
        try:
            return handler(value)
        except ValidationError:
            field = cls.model_fields[info.field_name]
            if field.is_required():
                raise
            return field.get_default(call_default_factory=True)


class MailHeaders(_ReadModel):
    """Untrusted, already cleaned header values; absent headers are empty."""

    sender: str = Field(default="", alias="from")
    subject: str = ""
    date: str = ""
    message_id: str = ""
    reply_to: str = ""
    references: str = ""


class ImagePreview(_ReadModel):
    """Re-encoded JPEG preview of an image attachment (2.0)."""

    index: int
    size_bytes: int = 0
    # Absent in previews written before their dimensions were recorded.
    width: int | None = None
    height: int | None = None


class PreparedAttachment(_ReadModel):
    """One extracted attachment, as stored; error entries carry fewer fields."""

    filename: str = "Anhang"
    content_type: str = ""
    size_bytes: int = 0
    text: str = ""
    extraction_status: str = "success"
    character_count: int = 0
    vision: str | None = None
    preview: ImagePreview | None = None

    @property
    def usable_text(self) -> str:
        """Text worth passing on: only from a successful extraction, stripped."""
        return self.text.strip() if self.extraction_status == "success" else ""


class PreparedMail(_ReadModel):
    headers: MailHeaders = Field(default_factory=MailHeaders)
    text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    extracted_attachments: list[PreparedAttachment] = Field(default_factory=list)
    calendar_events: list[dict[str, Any]] = Field(default_factory=list)
    date_header_original: str | None = None
    date_header_parsed: str | None = None
    imap_received_at: str | None = None
    user_timezone: str | None = None
    date_context_status: str = "missing"
    message_ids: list[str] = Field(default_factory=list)
    internal_id: str | None = None

    @property
    def received(self) -> str | None:
        """ISO timestamp of the mail: its valid Date header, else the IMAP arrival."""
        return self.date_header_parsed or self.imap_received_at


__all__ = ["ImagePreview", "MailHeaders", "PreparedAttachment", "PreparedMail"]
