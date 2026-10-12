"""State store doubles; each delegates to a real ``JsonStore`` (Planung 2.1, T2).

Production code relies on the full ``StateStore`` protocol.  A double therefore
changes only the behaviour under test and forwards everything else, instead of
offering a reduced interface that production code would have to tolerate.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any

from pydantic import BaseModel

from mailhelp.storage import JsonStore


class DelegatingStore:
    """Forward every ``StateStore`` operation to *delegate*; subclasses override single ones."""

    def __init__(self, delegate: JsonStore):
        self.delegate = delegate
        self.directory = delegate.directory

    def load(self, name: str, default: Any = None) -> Any:
        return self.delegate.load(name, default)

    def save(self, name: str, value: Any) -> None:
        self.delegate.save(name, value)

    def load_model(self, name: str, model: type[BaseModel], default: BaseModel | None = None) -> BaseModel | None:
        return self.delegate.load_model(name, model, default)

    def peek_model(self, name: str, model: type[BaseModel], default: BaseModel | None = None) -> BaseModel | None:
        return self.delegate.peek_model(name, model, default)

    def names(self, prefix: str = "") -> list[str]:
        return self.delegate.names(prefix)

    def locked(self) -> AbstractContextManager[Any]:
        return self.delegate.locked()


class InterruptingStore(DelegatingStore):
    """Simulate a power loss: the *fail_at*-th write and every later one fail."""

    def __init__(self, delegate: JsonStore, fail_at: int):
        super().__init__(delegate)
        self.fail_at, self.count = fail_at, 0

    def save(self, name: str, value: Any) -> None:
        self.count += 1
        if self.count >= self.fail_at:
            raise RuntimeError("power loss")
        self.delegate.save(name, value)
