"""Pure formatting and Telegram callback-markup validation helpers."""

from ._core import (
    format_proposal,
    numbered_message_parts,
    split_message,
    validate_callback_data,
    validate_callback_markup,
)

__all__ = [
    "format_proposal", "numbered_message_parts", "split_message",
    "validate_callback_data", "validate_callback_markup",
]
