"""Shared synthetic topic-editor configuration."""
import pytest
import yaml

from mailhelp.config import Topic
from tests.fakes.shared_web_v12 import configure


@pytest.fixture
def topics(web, tmp_path):
    configure(web, tmp_path)
    entries = [Topic(id="school", name="Schule", description="Schulpost", enabled=True,
                     examples=["Elternabend; Klasse 3"], mailboxes=[1]),
               Topic(id="club", name="Verein", description="Vereinspost", enabled=True)]
    (tmp_path / "topics.yaml").write_text(yaml.safe_dump({"topics": [item.model_dump() for item in entries]}),
                                          encoding="utf-8")
    return web, tmp_path
