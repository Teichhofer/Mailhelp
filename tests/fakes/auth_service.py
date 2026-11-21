"""8.0: the central sign-in flow against a simulated Google, with two synthetic instances."""
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from inboxstride_auth.google import Client, GoogleTokens
from inboxstride_auth.models import Instance
from inboxstride_auth.secret_store import SecretStore, create_key
from inboxstride_auth.service import AuthService, Refused, digest
from inboxstride_auth.state_file import StateConflict, StateDamaged, StateFile
from tests.fakes.google_oauth import FakeGoogle

T0 = datetime(2026, 11, 19, 8, 0, tzinfo=UTC)
ANNA, BERT = "a" * 64, "b" * 64  # local session references of the two instances


class Clock:
    def __init__(self):
        self.now, self.tick = T0, 0.0

    def __call__(self):
        return self.now

    def monotonic(self):
        return self.tick


class Tokens:
    def __init__(self):
        self.count = 0

    def __call__(self, size):
        self.count += 1
        return f"tok{self.count:04d}" + "x" * size


@pytest.fixture
def service(tmp_path):
    key = tmp_path / "auth.key"
    create_key(key)
    google = FakeGoogle()
    clock = Clock()
    tokens = GoogleTokens(Client("synthetic-client", "synthetic-client-secret"), transport=httpx.MockTransport(google))
    auth = AuthService(StateFile(tmp_path / "state"), SecretStore(tmp_path / "state", key), tokens, clock,
                       Tokens(), clock.monotonic)
    auth.register(Instance(id="anna", host="anna.inboxstride.example", certificate="1" * 64))
    auth.register(Instance(id="bert", host="bert.inboxstride.example", certificate="2" * 64))
    auth.fake, auth.clock_ = google, clock
    yield auth
    tokens.close()


def sign_in(service, code="good", instance="anna", session=ANNA, target="profile:1", key="k1"):
    job, url = service.start(instance, session, target, "connect", key)
    oauth_state = parse_qs(urlsplit(url).query)["state"][0]
    return job, url, oauth_state, service.callback(oauth_state, code, None)


def receipt_of(redirect):
    return parse_qs(urlsplit(redirect).query)["beleg"][0]


