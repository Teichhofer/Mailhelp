"""Credentials and account addresses never enter profile diagnostics or logs."""
import pytest
from shared_profiles import settings

from mailhelp.config import Settings


@pytest.mark.parametrize("url", ["https://user@caldav.example.test/calendar/", "https://user:secret@caldav.example.test/c/"])
def test_caldav_urls_cannot_embed_credentials(tmp_path, url):
    raw = settings(tmp_path).model_dump(mode="json")
    raw["target_profiles"][0].update(calendar_provider="caldav", caldav_calendar_url=url)
    with pytest.raises(ValueError):
        Settings.model_validate(raw)
