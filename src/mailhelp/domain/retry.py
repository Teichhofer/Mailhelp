"""Durable attempts for one mail-processing failure, independent of external writes."""
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class ProcessingRetry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fingerprint: str
    attempts: int = Field(ge=1, le=5)
    first_failed_at: AwareDatetime
    last_failed_at: AwareDatetime
    abandoned: bool = False
    notification_marked_at: AwareDatetime | None = None
