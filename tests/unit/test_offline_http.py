"""Composition tests keep real client lifecycle and HTTP semantics with simulated transports."""
import httpx
import pytest


def test_unsimulated_clients_reject_requests_without_constructing_a_tls_pool(monkeypatch):
    def unexpected_pool(*args, **kwargs):
        pytest.fail("An offline composition test must not initialize a network pool")
    monkeypatch.setattr("httpx._client.HTTPTransport", unexpected_pool)
    with httpx.Client() as client:
        with pytest.raises(AssertionError, match="Nicht simulierter HTTP-Aufruf im Test: GET synthetic.test"):
            client.get("https://synthetic.test/private?token=never-log-this")
    assert client.is_closed


def test_explicit_simulated_transports_keep_request_body_response_and_lifecycle():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(201, json={"id": "synthetic"})
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        result = client.post("https://synthetic.test", json={"title": "Aufgabe"})
        assert result.status_code == 201 and result.json() == {"id": "synthetic"}
        assert requests[0].method == "POST" and requests[0].content == b'{"title":"Aufgabe"}'
    assert client.is_closed
