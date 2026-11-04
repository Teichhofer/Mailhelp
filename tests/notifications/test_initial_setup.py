"""First-run configuration uses synthetic credentials and read-only service doubles."""
import pytest

from mailhelp.config.loader import provider_secret_names
from mailhelp.config.models import TargetSettings


def test_todoist_personal_token_does_not_require_an_unrelated_oauth_client():
    targets = TargetSettings(google_calendar="primary", todoist_project="inbox")
    assert provider_secret_names(targets) == ["TODOIST_TOKEN", "GOOGLE_OAUTH_CLIENT_ID",
                                            "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN"]
