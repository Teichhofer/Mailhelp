"""The triggering channel receives immediate replies; web uses its result page."""
from contextvars import ContextVar

web_reply: ContextVar[bool] = ContextVar("mailhelp_web_reply", default=False)
