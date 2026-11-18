"""8.0: readable state of the central OAuth service (synthetic instances only)."""
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from inboxstride_auth.models import SCOPES, AuthJob, AuthState, Connection, Instance, utc

NOW = datetime(2026, 11, 19, 8, 0, tzinfo=UTC)
CERT = "c" * 64


def job(**changes):
    values = dict(id="a" * 32, instance="anna", session="5" * 64, target="profile:1", operation="connect",
                  client_revision=1, created=NOW, expires=NOW + timedelta(minutes=10))
    values.update(changes)
    return AuthJob(**values)


def test_an_instance_returns_only_to_its_own_completion_page():
    instance = Instance(id="anna", host="Anna.Inboxstride.Example", certificate=CERT)
    assert instance.host == "anna.inboxstride.example"
    assert instance.return_url == "https://anna.inboxstride.example/einrichtung/google/abschluss"
    for host in ("https://anna.example", "anna.example:443", "anna", "auth.inboxstride.example",
                 "www.inboxstride.example", "anna.example/pfad"):
        with pytest.raises(ValidationError):
            Instance(id="anna", host=host, certificate=CERT)


def test_a_job_moves_only_along_the_allowed_states():
    first = job()
    waiting = first.advance("awaiting_google", NOW, state_hash="1" * 64)
    assert (waiting.state, waiting.version, waiting.state_hash) == ("awaiting_google", 2, "1" * 64)
    with pytest.raises(ValueError, match="nicht erlaubt"):
        waiting.advance("active", NOW)  # never without the local confirmation
    with pytest.raises(ValueError, match="nicht erlaubt"):
        waiting.advance("exchanging", NOW).advance("exchanging", NOW)
    ready = waiting.advance("exchanging", NOW).advance("candidate_ready", NOW, candidate="b" * 32)
    done = ready.advance("awaiting_local_confirmation", NOW).advance("activating", NOW).advance("active", NOW)
    assert done.state == "active" and done.version == 7
    with pytest.raises(ValueError, match="nicht erlaubt"):
        done.advance("failed", NOW)  # a terminal state stays


def test_an_expired_job_can_only_end():
    late = NOW + timedelta(minutes=10)
    with pytest.raises(ValueError, match="abgelaufen"):
        job().advance("awaiting_google", late)
    assert job().advance("expired", late).state == "expired"


@pytest.mark.parametrize("changes", [
    {"expires": NOW + timedelta(minutes=11)},  # a restart never prolongs a sign-in
    {"receipt_hash": "2" * 64, "receipt_expires": NOW + timedelta(minutes=11)},
    {"receipt_expires": NOW + timedelta(minutes=1)},  # an expiry without a receipt
    {"state": "candidate_ready"},  # without a candidate
    {"target": "profile:0"}, {"target": "draft:x"}, {"session": "kurz"},
])
def test_inconsistent_jobs_are_refused(changes):
    with pytest.raises(ValidationError):
        job(**changes)


def test_a_connection_needs_every_calendar_scope():
    values = dict(id="b" * 32, instance="anna", target="profile:1", status="candidate", generation=1,
                  secret="refresh:" + "d" * 32, client_revision=1, created=NOW)
    connection = Connection(scopes=(*reversed(SCOPES), SCOPES[0]), **values)
    assert connection.scopes == tuple(sorted(SCOPES))
    with pytest.raises(ValidationError, match="Kalenderberechtigungen"):
        Connection(scopes=SCOPES[:2], **values)


def test_the_state_keeps_its_references_consistent():
    anna = Instance(id="anna", host="anna.inboxstride.example", certificate=CERT)
    state = AuthState(instances={"anna": anna}, jobs={"a" * 32: job()})
    assert AuthState.model_validate_json(state.model_dump_json()) == state
    with pytest.raises(ValidationError, match="übereinstimmen"):
        AuthState(instances={"other": anna})
    with pytest.raises(ValidationError, match="Unbekannte Instanz"):
        AuthState(jobs={"a" * 32: job()})


def test_times_need_a_zone():
    assert utc(datetime(2026, 11, 19, 9, tzinfo=UTC) + timedelta(0)) == datetime(2026, 11, 19, 9, tzinfo=UTC)
    with pytest.raises(ValueError, match="Zeitzone"):
        utc(datetime(2026, 11, 19, 9))
