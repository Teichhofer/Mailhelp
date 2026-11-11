"""Versioned, session-owned topic previews contain no authorization to execute a write."""
from __future__ import annotations

import hashlib
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ..config import Topic
from ..rule_learning.models import RuleTopic
from .settings_search import normalize


def owner(actor: str) -> str:
    return hashlib.sha256(actor.encode()).hexdigest()


def draft_id(actor: str, kind: str, original: str) -> str:
    return owner(actor + "\0" + kind + "\0" + original)


def proposed_id(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", normalize(name)).strip("-_")[:64].strip("-_") or "thema"


class TopicDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    version: int = 0
    owner: str = ""
    created_at: float = 0
    kind: Literal["relevant", "ausschluss"] = "relevant"
    original_id: str = ""
    expected_hash: str = ""
    key: str = ""
    input_hash: str = ""
    topic: RuleTopic | None = None
    before: Topic | None = None


class TopicFieldError(ValueError):
    def __init__(self, field: str, message: str, status: int = 422):
        super().__init__(message)
        self.field, self.status = field, status
