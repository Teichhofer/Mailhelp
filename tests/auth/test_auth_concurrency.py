"""Deterministic interleavings protect one-use codes and disconnected credentials."""
from threading import Barrier, Thread
from urllib.parse import parse_qs, urlsplit

import pytest

from inboxstride_auth.service import Refused
from tests.fakes.auth_service import ANNA, receipt_of, service, sign_in  # noqa: F401


def test_two_simultaneous_callbacks_exchange_the_code_once(service, monkeypatch):
    _job, url = service.start("anna", ANNA, "profile:1", "connect", "parallel-callback")
    state = parse_qs(urlsplit(url).query)["state"][0]
    barrier = Barrier(2)
    save = service._save_job

    def synchronized(job):
        if job.state == "exchanging":
            barrier.wait(5)
        save(job)

    monkeypatch.setattr(service, "_save_job", synchronized)
    results = []

    def callback():
        try:
            results.append(service.callback(state, "good", None))
        except Refused as error:
            results.append(error.code)

    threads = [Thread(target=callback) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
        assert not thread.is_alive()
    assert sum(request.get("grant_type") == "authorization_code" for request in service.fake.requests) == 1
    assert len(results) == 2 and "job_changed" in results


@pytest.mark.parametrize("replace", [False, True])
def test_disconnect_or_replacement_during_refresh_cannot_restore_a_secret(service, monkeypatch, replace):
    _job, _url, _state, redirect = sign_in(service)
    redeemed = service.redeem("anna", ANNA, receipt_of(redirect))
    connection = service.activate("anna", ANNA, redeemed.id, redeemed.version)
    service.clock_.tick = 4000
    service.fake.rotate = True
    refresh = service.google.refresh

    def interrupted(token):
        answer = refresh(token)
        if replace:
            _, _, _, returned = sign_in(service, key="replacement")
            ready = service.redeem("anna", ANNA, receipt_of(returned))
            service.activate("anna", ANNA, ready.id, ready.version)
        else:
            service.disconnect("anna", connection.id)
        return answer

    monkeypatch.setattr(service.google, "refresh", interrupted)
    with pytest.raises(Refused, match="disconnected"):
        service.access_token("anna", connection.id)
    assert service.store.get(connection.secret) is None
    assert connection.id not in service._tokens


def test_a_request_waiting_for_renewal_rechecks_disconnect(service):
    _, _, _, redirect = sign_in(service)
    ready = service.redeem("anna", ANNA, receipt_of(redirect))
    connection = service.activate("anna", ANNA, ready.id, ready.version)

    class Interleaving:
        def __enter__(self):
            service.disconnect("anna", connection.id)

        def __exit__(self, *_args):
            pass

    service._renewals[connection.id] = Interleaving()
    with pytest.raises(Refused, match="disconnected"):
        service.access_token("anna", connection.id)


def test_parallel_instances_keep_all_separate_secrets(service):
    barrier = Barrier(8)
    errors = []

    def write(number):
        barrier.wait(5)
        try:
            for index in range(10):
                service.store.put(f"synthetic-{number}-{index}", "synthetic-secret")
        except Exception as error:
            errors.append(type(error).__name__)

    threads = [Thread(target=write, args=(number,)) for number in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
        assert not thread.is_alive()
    assert errors == []
    assert len(service.store.names()) == 80
