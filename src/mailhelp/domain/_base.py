"""Gemeinsame, nicht persistenzspezifische Modellbasis."""
from datetime import date
from pydantic import BaseModel, ConfigDict

CalendarDate = date

class StrictModel(BaseModel):
    """Reject unknown input at every domain trust boundary."""
    model_config = ConfigDict(extra="forbid")
