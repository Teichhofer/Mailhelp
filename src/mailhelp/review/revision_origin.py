"""Trusted provenance at publication; never obtained from mail or model output."""
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

ORIGIN: ContextVar[str] = ContextVar('revision_origin', default='system')


@contextmanager
def revision_origin(source: str) -> Iterator[None]:
    token = ORIGIN.set(source)
    try:
        yield
    finally:
        ORIGIN.reset(token)
