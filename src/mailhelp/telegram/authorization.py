"""Authorization boundary for untrusted Telegram updates."""

from ._core import AuthorizedUpdateValidator, UpdateValidation

__all__ = ["AuthorizedUpdateValidator", "UpdateValidation"]
