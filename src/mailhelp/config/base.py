"""Common base of all configuration models. (7.0: split from models.py)"""

from __future__ import annotations

from pydantic import (
    BaseModel,
    ConfigDict,
)


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
