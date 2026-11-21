"""Shared central-service fixture and HTML form inspection."""
import re
from html import unescape

import pytest

from tests.fakes.hosted_google import Central


@pytest.fixture
def central(tmp_path):
    hub = Central(tmp_path)
    yield hub
    hub.close()


def fields(html, action):
    block = re.search(rf'<form method="post" action="{re.escape(action)}"[^>]*>(.*?)</form>', html, re.S)[1]
    return {name: unescape(value) for name, value in re.findall(r'name="([^"]+)" value="([^"]*)"', block)}


