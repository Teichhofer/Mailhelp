"""Shared large synthetic topic catalog for browser tests."""
import pytest
import yaml

from mailhelp.config import Topic


@pytest.fixture
def topic_catalog(mailhelp):
    topics = [Topic(id="school", name="Schule", description="Verbindliche Schulpost. Zweiter Satz.",
                    enabled=True, examples=["Rechnung; verbindlich"], mailboxes=[1]),
              Topic(id="inactive", name="Sport", description="Nicht mehr benötigt", enabled=False)]
    topics += [Topic(id=f"topic-{index}", name=f"Thema {index:02}", description="Synthetisches Thema", enabled=True)
               for index in range(46)]
    directory = mailhelp.site.archive.configuration.directory
    (directory / "topics.yaml").write_text(yaml.safe_dump({"topics": [topic.model_dump() for topic in topics]}),
                                           encoding="utf-8")
    return directory
