"""Default HTTP clients in tests cannot contact real providers or initialize unused TLS pools."""
import httpx
import pytest


def reject_network(request):
    raise AssertionError(f"Nicht simulierter HTTP-Aufruf im Test: {request.method} {request.url.host}")


@pytest.fixture(autouse=True)
def offline_http_clients(monkeypatch):
    original = httpx.Client.__init__
    def initialize(self, *args, **kwargs):
        if kwargs.get("transport") is None:
            kwargs["transport"] = httpx.MockTransport(reject_network)
        original(self, *args, **kwargs)
    monkeypatch.setattr(httpx.Client, "__init__", initialize)
