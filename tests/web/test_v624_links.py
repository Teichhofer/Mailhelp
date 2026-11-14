"""6.2.4: pages link to settings and help instead of naming configuration keys."""
import json
import re
from pathlib import Path

import pytest

from mailhelp.web.reconciliation_pages import section_head
from mailhelp.web.settings_search import setting_href
from tests.scenarios.web_scenario import proposal

ROOT = Path(__file__).resolve().parents[2]
SECTIONS = {section["id"] for section in
            json.loads((ROOT / "src" / "mailhelp" / "helpdocs" / "sections.json").read_text(encoding="utf-8"))}


def test_a_setting_link_opens_its_area_at_the_setting():
    assert setting_href("activity_report.enabled") == "/einstellungen?bereich=ki#einstellung-activity-report-enabled"
    with pytest.raises(StopIteration):
        setting_href("gibt.es.nicht")


def test_every_help_link_in_the_pages_points_to_a_packaged_section():
    links = {match for path in (ROOT / "src" / "mailhelp" / "web").glob("*.py")
             for match in re.findall(r"/hilfe/dokumentation/([a-z0-9-]+/[a-z0-9-]+)", path.read_text(encoding="utf-8"))}
    assert links and links <= SECTIONS


def test_the_target_names_the_profile_when_no_service_was_stored():
    """Regression 6.2.4: proposals without a stored service read "Ziel: Anbieter nicht gespeichert · Familie"."""
    older = proposal(1, "a", target="Familie", target_provider="")
    assert "<p>Ziel: Zielprofil „Familie“</p>" in section_head(older, "c" * 32)
    google = proposal(1, "b", target="Familie", target_provider="todoist")
    assert "<p>Ziel: Todoist · Familie</p>" in section_head(google, "c" * 32)
