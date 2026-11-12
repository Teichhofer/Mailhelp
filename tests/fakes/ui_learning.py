"""Local learning server with synthetic mail and model services for UI tests."""
from types import SimpleNamespace

import pytest

from mailhelp.web.server import WebServer
from tests.fakes.initial_harness import InitialHarness
from tests.fakes.learning_harness import LearningHarness


@pytest.fixture
def learning_server(tmp_path):
    initial=InitialHarness(tmp_path)
    h=LearningHarness(initial)
    server=WebServer('127.0.0.1',0,h.web,SimpleNamespace(event=lambda *a,**kw:None))
    server.start()
    host,port=server.address
    h.web.allowed_hosts=frozenset({f'{host}:{port}'})
    h.url=f'http://{host}:{port}'
    h.auth.channel='console'
    h.code=h.auth.issue_code()
    try:yield h
    finally:server.stop();initial.close()
