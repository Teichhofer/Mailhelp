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


def test_a_complete_sign_in_activates_exactly_the_confirmed_access(service):
    job, url, oauth_state, redirect = sign_in(service)
    query = parse_qs(urlsplit(url).query)
    assert url.startswith("https://accounts.google.com/") and query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent select_account"] and query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == ["https://auth.inboxstride.de/auth/google/callback"]
    assert redirect.startswith("https://anna.inboxstride.example/einrichtung/google/abschluss?beleg=")
    assert "good" not in redirect and "refresh" not in redirect and "access" not in redirect
    state = service.state.read()
    assert state.jobs[job.id].state == "candidate_ready" and oauth_state not in (service.state.path.read_text())
    redeemed = service.redeem("anna", ANNA, receipt_of(redirect))
    with pytest.raises(Refused, match="unknown_receipt"):
        service.redeem("anna", ANNA, receipt_of(redirect))  # a receipt works once
    connection = service.activate("anna", ANNA, redeemed.id, redeemed.version)
    assert (connection.status, connection.generation, connection.target) == ("active", 1, "profile:1")
    assert service.access_token("anna", connection.id) == ("access-1", 3540)  # from the exchange, cached
    assert service.store.get(connection.secret) == "refresh-for-good"
    # A crash after "activating" is finished by resume without a second effect.
    assert service.resume(redeemed.id) == connection


def test_the_other_instance_can_use_nothing_of_it(service):
    job, _url, _state, redirect = sign_in(service)
    with pytest.raises(Refused, match="unknown_receipt"):
        service.redeem("bert", ANNA, receipt_of(redirect))
    with pytest.raises(Refused, match="unknown_receipt"):
        service.redeem("anna", BERT, receipt_of(redirect))  # another browser session of the same instance
    redeemed = service.redeem("anna", ANNA, receipt_of(redirect))
    with pytest.raises(Refused, match="unknown_job"):
        service.activate("bert", ANNA, redeemed.id, redeemed.version)
    with pytest.raises(Refused, match="job_changed"):
        service.activate("anna", ANNA, redeemed.id, redeemed.version - 1)
    connection = service.activate("anna", ANNA, redeemed.id, redeemed.version)
    with pytest.raises(Refused, match="unknown_connection"):
        service.access_token("bert", connection.id)
    with pytest.raises(Refused, match="unknown_connection"):
        service.disconnect("bert", connection.id)
    # Parallel sign-ins of both instances stay apart.
    _job, _url, _state, other = sign_in(service, instance="bert", session=BERT, key="k1")
    assert other.startswith("https://bert.inboxstride.example/")


def test_a_replacement_keeps_the_old_access_until_the_new_one_is_confirmed(service):
    _job, _url, _state, redirect = sign_in(service)
    redeemed = service.redeem("anna", ANNA, receipt_of(redirect))
    old = service.activate("anna", ANNA, redeemed.id, redeemed.version)
    _job, _url, _state, again = sign_in(service, code="second", key="k2")
    assert service.state.read().connections[old.id].status == "active"  # untouched while a candidate exists
    redeemed = service.redeem("anna", ANNA, receipt_of(again))
    new = service.activate("anna", ANNA, redeemed.id, redeemed.version)
    state = service.state.read()
    assert new.generation == 2 and state.connections[old.id].status == "disconnected"
    assert service.store.get(old.secret) is None and service.store.get(new.secret) == "refresh-for-second"
    with pytest.raises(Refused, match="disconnected"):
        service.access_token("anna", old.id)


def test_tokens_are_renewed_and_a_refused_renewal_asks_for_a_new_sign_in(service):
    _job, _url, _state, redirect = sign_in(service)
    redeemed = service.redeem("anna", ANNA, receipt_of(redirect))
    connection = service.activate("anna", ANNA, redeemed.id, redeemed.version)
    service.clock_.tick = 4000  # the first token has run out
    service.fake.rotate = True
    assert service.access_token("anna", connection.id) == ("access-2", 3540)
    assert service.store.get(connection.secret) == "rotated-2"
    service.clock_.tick = 8000
    service.fake.rotate = False
    assert service.access_token("anna", connection.id)[0] == "access-3"
    assert service.store.get(connection.secret) == "rotated-2"  # no new one in the answer: the old stays
    service.clock_.tick = 12000
    for value, reason in (("busy", "temporarily_unavailable"), ("lost", "temporarily_unavailable")):
        service.store.put(connection.secret, value)
        with pytest.raises(Refused, match=reason):
            service.access_token("anna", connection.id)
    service.store.put(connection.secret, "refused")
    with pytest.raises(Refused, match="reconnect_required"):
        service.access_token("anna", connection.id)
    assert service.state.read().connections[connection.id].status == "reconnect_required"
    with pytest.raises(Refused, match="reconnect_required"):
        service.access_token("anna", connection.id)


def test_a_missing_secret_or_a_refused_client_never_issues_a_token(service):
    _job, _url, _state, redirect = sign_in(service)
    redeemed = service.redeem("anna", ANNA, receipt_of(redirect))
    connection = service.activate("anna", ANNA, redeemed.id, redeemed.version)
    service.clock_.tick = 4000
    service.google.client = Client("synthetic-client", "wrong")
    with pytest.raises(Refused, match="client_refused"):
        service.access_token("anna", connection.id)
    service.store.delete(connection.secret)
    with pytest.raises(Refused, match="reconnect_required"):
        service.access_token("anna", connection.id)


@pytest.mark.parametrize(("code", "reason"), [
    ("refused", "grant_refused"), ("lost", "exchange_unclear"), ("down", "exchange_unclear"),
    ("norefresh", "no_refresh_token"), ("narrow", "missing_scopes"),
])
def test_an_unusable_exchange_ends_the_sign_in_without_a_candidate(service, code, reason):
    job, _url, oauth_state, redirect = sign_in(service, code=code)
    assert redirect.endswith("?abbruch=1")
    state = service.state.read()
    assert (state.jobs[job.id].state, state.jobs[job.id].error) == ("failed", reason)
    assert state.connections == {} and service.store.names() == []
    with pytest.raises(Refused, match="state_used"):
        service.callback(oauth_state, "good", None)  # the code is never exchanged twice
    assert sum(1 for item in service.fake.requests if item.get("grant_type") == "authorization_code") == (
        1 if code not in {"lost"} else 1)


def test_a_wrong_client_secret_ends_the_sign_in(service):
    service.google.client = Client("synthetic-client", "wrong")
    job, _url, _state, redirect = sign_in(service)
    assert redirect.endswith("?abbruch=1") and service.state.read().jobs[job.id].error == "client_refused"


@pytest.mark.parametrize(("error", "final", "reason"), [("access_denied", "cancelled", "access_denied"),
                                                        ("server_error", "failed", "provider_error")])
def test_a_refusal_at_google_ends_cleanly(service, error, final, reason):
    job, url = service.start("anna", ANNA, "profile:1", "connect", "k1")
    oauth_state = parse_qs(urlsplit(url).query)["state"][0]
    assert service.callback(oauth_state, None, error).endswith("?abbruch=1")
    stored = service.state.read().jobs[job.id]
    assert (stored.state, stored.error) == (final, reason) and service.store.names() == []


def test_unknown_late_or_foreign_returns_are_refused(service):
    with pytest.raises(Refused, match="unknown_state"):
        service.callback("erfunden", "good", None)
    job, url = service.start("anna", ANNA, "profile:1", "connect", "k1")
    oauth_state = parse_qs(urlsplit(url).query)["state"][0]
    service.clock_.now = T0 + timedelta(minutes=10)
    with pytest.raises(Refused, match="expired"):
        service.callback(oauth_state, "good", None)
    assert service.state.read().jobs[job.id].state == "expired" and service.fake.requests == []


def test_the_receipt_runs_out_after_two_minutes(service):
    job, _url, _state, redirect = sign_in(service)
    assert service.sweep() == 0 and service.state.read().jobs[job.id].state == "candidate_ready"  # still open
    service.clock_.now = T0 + timedelta(minutes=2)
    with pytest.raises(Refused, match="receipt_expired"):
        service.redeem("anna", ANNA, receipt_of(redirect))
    service.clock_.now = T0 + timedelta(minutes=10)
    assert service.sweep() == 1
    state = service.state.read()
    assert state.jobs[job.id].state == "expired" and service.store.names() == []
    assert state.connections[state.jobs[job.id].candidate].status == "disconnected"
    assert service.sweep() == 0


def test_starts_are_bound_to_registered_instances_and_their_key(service):
    with pytest.raises(Refused, match="unknown_instance"):
        service.start("carla", ANNA, "profile:1", "connect", "k1")
    job, first = service.start("anna", ANNA, "profile:1", "connect", "k1")
    again, second = service.start("anna", ANNA, "profile:1", "connect", "k1")
    assert again.id == job.id and again.version == job.version + 1 and first != second
    old_state = parse_qs(urlsplit(first).query)["state"][0]
    with pytest.raises(Refused, match="unknown_state"):
        service.callback(old_state, "good", None)  # the replaced state no longer works
    with pytest.raises(Refused, match="key_reused"):
        service.start("anna", ANNA, "profile:2", "connect", "k1")
    service.callback(parse_qs(urlsplit(second).query)["state"][0], "good", None)
    with pytest.raises(Refused, match="job_not_open"):
        service.start("anna", ANNA, "profile:1", "connect", "k1")
    with pytest.raises(Refused, match="host_taken"):
        service.register(Instance(id="carla", host="anna.inboxstride.example", certificate="3" * 64))


def test_a_new_sign_in_makes_older_open_ones_of_the_same_target_stale(service):
    waiting, _url = service.start("anna", ANNA, "profile:1", "connect", "k1")
    ready, _url, _state, _redirect = sign_in(service, key="k2")
    newest, _url = service.start("anna", ANNA, "profile:1", "reauthorize", "k3")
    other, _url = service.start("anna", ANNA, "profile:2", "connect", "k4")
    jobs = service.state.read().jobs
    assert jobs[waiting.id].state == "cancelled" and jobs[ready.id].state == "cancelled"
    assert jobs[newest.id].state == jobs[other.id].state == "awaiting_google"


def test_disconnecting_stops_tokens_but_revokes_nothing_at_google(service):
    _job, _url, _state, redirect = sign_in(service)
    redeemed = service.redeem("anna", ANNA, receipt_of(redirect))
    connection = service.activate("anna", ANNA, redeemed.id, redeemed.version)
    requests = len(service.fake.requests)
    service.disconnect("anna", connection.id)
    assert service.store.get(connection.secret) is None and len(service.fake.requests) == requests
    with pytest.raises(Refused, match="disconnected"):
        service.access_token("anna", connection.id)


def test_the_state_file_refuses_lost_updates_and_reports_damage(tmp_path):
    states = StateFile(tmp_path / "s")
    first = states.read()
    states.write(first, first.revision)
    with pytest.raises(StateConflict):
        states.write(first, first.revision)
    (tmp_path / "s" / "auth-state.json").write_text("{", encoding="utf-8")
    with pytest.raises(StateDamaged):
        states.read()


def test_a_failed_state_write_keeps_the_previous_file(tmp_path, monkeypatch):
    import os
    states = StateFile(tmp_path / "s")
    states.write(states.read(), 0)
    before = states.path.read_text(encoding="utf-8")
    monkeypatch.setattr(os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        states.write(states.read(), 1)
    assert states.path.read_text(encoding="utf-8") == before and len(list((tmp_path / "s").iterdir())) == 1


def test_google_answers_are_checked_before_use():
    google = FakeGoogle()
    tokens = GoogleTokens(Client("c", "synthetic-client-secret"), transport=httpx.MockTransport(google))
    from inboxstride_auth.google import TemporaryFailure
    for value in ("html", "odd", "huge", "partial", "mac", "list"):
        with pytest.raises(TemporaryFailure):
            tokens.refresh(value)
    with pytest.raises(TemporaryFailure) as busy:
        tokens.refresh("busy")
    assert busy.value.retry_after == 30
    with pytest.raises(TemporaryFailure) as down:
        tokens.refresh("down")
    assert down.value.retry_after is None
    assert digest("x") == digest("x") != digest("y")
