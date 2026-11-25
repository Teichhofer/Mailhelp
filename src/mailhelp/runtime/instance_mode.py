"""8.7: the instance mode, set only in ``operator.yaml`` – a file Mailhelp itself never writes.

Without the file the instance is self-operated, exactly as before. With ``customer_mode: true`` every
web session carries a server-side role (``customer`` or ``operator``) bound to this instance; nothing a
browser, a form, an import or a queued command sends can switch the mode off.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

FILE = "operator.yaml"


class InstanceModeError(ValueError):
    """operator.yaml exists but is not valid; the instance does not start in an unclear mode."""


class InstanceMode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    customer_mode: bool = False
    # The identity sessions are bound to; one per customer instance (subdomain).
    instance: str = Field(default="self", pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")


def load_instance_mode(config_directory: Path) -> InstanceMode:
    path = config_directory / FILE
    if not path.exists():
        return InstanceMode()
    try:
        return InstanceMode.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise InstanceModeError(f"{FILE} ist ungültig: Kundenmodus kann nicht bestimmt werden") from exc


__all__ = ["FILE", "InstanceMode", "InstanceModeError", "load_instance_mode"]
