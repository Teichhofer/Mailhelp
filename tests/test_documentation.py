import re
from datetime import datetime
from pathlib import Path
from typing import get_args

import pytest
import yaml

from mailhelp.config import Settings
from mailhelp.models import MailState


ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize(
    ("document", "pattern"),
    [
        ("README.md", r"Mailzustände \(Schema (\d+)\)"),
        ("Mailhelp-Projektspezifikation.md", r"Maildateien tragen Schemaversion (\d+)"),
    ],
)
def test_documented_mail_schema_matches_application(document, pattern):
    """Keep operator-facing schema claims aligned with the strict state model."""
    annotation = MailState.model_fields["schema_version"].annotation
    (application_version,) = get_args(annotation)
    contents = (ROOT / document).read_text(encoding="utf-8")
    documented_versions = re.findall(pattern, contents)

    assert documented_versions == [str(application_version)]


def test_shipped_config_excludes_mail_before_requested_historical_boundary():
    """Pin the operator-facing cutoff to 15 September 2026 in Berlin."""
    config = Settings.model_validate(
        yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    )

    assert config.imap.historical_start == datetime.fromisoformat(
        "2026-09-15T00:00:00+02:00"
    )
