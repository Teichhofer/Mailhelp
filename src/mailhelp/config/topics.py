"""Relevant and excluded topics. (7.0: split from models.py)"""

from __future__ import annotations

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from .base import ConfigModel


class Topic(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=r"^[a-z0-9_-]+$")
    name: str
    enabled: bool
    description: str
    examples: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    mailboxes: list[int] | None = Field(default=None, max_length=10)

    @field_validator("mailboxes")
    @classmethod
    def valid_mailboxes(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and (len(value) != len(set(value)) or any(not 1 <= item <= 99 for item in value)):
            raise ValueError("Themen benötigen eindeutige Postfachnummern zwischen 1 und 99")
        return value

class TopicsConfig(ConfigModel):
    """Geschlossene Wurzel der Themendatei mit eindeutigen stabilen IDs."""

    topics: list[Topic] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_enabled_topics(self) -> TopicsConfig:
        identifiers = [topic.id for topic in self.topics]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Themen-IDs dürfen nicht doppelt vorkommen")
        if not any(topic.enabled for topic in self.topics):
            raise ValueError("mindestens ein Thema muss aktiviert sein")
        return self

class IrrelevantTopicsConfig(ConfigModel):
    """Closed topic file used to recognize categories excluded from learning."""

    topics: list[Topic] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_topic_ids(self) -> IrrelevantTopicsConfig:
        identifiers = [topic.id for topic in self.topics]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Themen-IDs dürfen nicht doppelt vorkommen")
        return self
