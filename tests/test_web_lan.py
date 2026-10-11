"""Access from the home network: the PC's IP address in /web links and host checks."""
from __future__ import annotations

import re
import socket

import pytest

from mailhelp.config import WebSettings
from mailhelp.review.inbox import CommandInbox
from mailhelp.storage import JsonStore
from mailhelp.web import Request, WebApp
from mailhelp.web import network
from mailhelp.web.factory import base_url, create_web
from test_web_auth import LOCAL, SECRET, TAILNET, Browser, Logger, code_from, signed_in, site  # noqa: F401

LAN = "192.168.1.20"


@pytest.mark.parametrize(("value", "expected"), [
    ("192.168.1.20", True), ("10.0.0.5", True), ("172.16.3.4", True),
    ("127.0.0.1", False), ("8.8.8.8", False), ("169.254.1.1", False), ("fd00::1", False),
    ("mailhelp.test", False), ("", False),
])
def test_only_private_ipv4_addresses_count_as_home_network(value, expected):
    assert network.is_lan_address(value) is expected


def test_lan_host_needs_the_service_port():
    assert network.lan_host(f"{LAN}:8765", 8765)
    assert not network.lan_host(f"{LAN}:9999", 8765)
    assert not network.lan_host(LAN, 8765)
    assert not network.lan_host("evil.test:8765", 8765)


class Probe:
    def __init__(self, address=None, error=None):
        self.address, self.error = address, error

    def __call__(self, *args):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def connect(self, target):
        assert target == ("192.0.2.1", 80)
        if self.error:
            raise self.error

    def getsockname(self):
        return (self.address, 50000)


@pytest.mark.parametrize(("probe", "expected"), [
    (Probe(LAN), LAN), (Probe("127.0.0.1"), None), (Probe(error=OSError("kein Netz")), None),
])
def test_lan_ip_uses_the_outgoing_interface(monkeypatch, probe, expected):
    monkeypatch.setattr(network.socket, "socket", probe)
    assert network.lan_ip() == expected


def test_lan_ip_on_this_machine_is_private_or_none():
    address = network.lan_ip()
    assert address is None or network.is_lan_address(address)
    assert socket.AF_INET


def get(app, host):
    return app(Request("GET", "/health", {"host": host}))


def test_ip_hosts_are_accepted_only_with_lan_access():
    with_lan, without = WebApp([LOCAL], lan_port=8765), WebApp([LOCAL])
    assert get(with_lan, f"{LAN}:8765").status == 200
    assert get(without, f"{LAN}:8765").status == 421
    for host in ("8.8.8.8:8765", f"{LAN}:9999", "evil.test:8765"):
        assert get(with_lan, host).status == 421


def test_lan_access_requires_listening_on_all_interfaces():
    with pytest.raises(ValueError, match="0.0.0.0"):
        WebSettings(lan_access=True)
    assert WebSettings(lan_access=True, host="0.0.0.0").lan_access


def test_sign_in_over_the_lan_ip_uses_cookies_without_secure(tmp_path):
    with JsonStore(tmp_path) as store:
        messages = []
        from mailhelp.web.auth import WebAuth
        from mailhelp.web.site import MailhelpSite
        from mailhelp.review.views import ReviewViews
        auth = WebAuth(store, SECRET, 30, messages.append)
        app = WebApp([LOCAL], lan_port=8765)
        MailhelpSite(app, auth, WebSettings(host="0.0.0.0", lan_access=True), "UTC", Logger(),
                     ReviewViews(store, "UTC"), CommandInbox(store))
        phone = Browser(app, f"{LAN}:8765")
        csrf = phone.csrf()
        phone.request("POST", "/anmelden/code", {"csrf": csrf})
        response = phone.request("POST", "/anmelden", {"csrf": csrf, "code": code_from(messages)})
        assert response.status == 303 and all("Secure" not in line for line in response.cookies)
        assert phone.request("GET", "/").status == 200


def settings(tmp_path, **web):
    from test_application import settings as app_settings
    configured = app_settings(tmp_path)
    configured.web = WebSettings(enabled=True, **web)
    return configured


def test_link_prefers_the_lan_ip_and_falls_back(tmp_path):
    lan = settings(tmp_path, host="0.0.0.0", lan_access=True, allowed_hosts=[LOCAL, TAILNET])
    assert base_url(lan, lambda: LAN) == f"http://{LAN}:8765"
    assert base_url(lan, lambda: None) == f"https://{TAILNET}"
    assert base_url(settings(tmp_path, allowed_hosts=[LOCAL, TAILNET]), lambda: LAN) == f"https://{TAILNET}"


def test_web_command_sends_the_current_lan_address(tmp_path, monkeypatch):
    addresses = iter([LAN, "192.168.1.31"])
    monkeypatch.setattr("mailhelp.web.factory.lan_ip", lambda: next(addresses))
    with JsonStore(tmp_path / "data") as store:
        components = create_web(settings(tmp_path, host="0.0.0.0", lan_access=True), SECRET, store,
                                print, Logger(), CommandInbox(store))
        first, second = components.invite(), components.invite()
    assert re.search(rf"http://{LAN}:8765/anmelden\?code=\d{{8}}", first)
    assert "Nur im selben Netzwerk" in first and "nur am PC" not in first
    # The address is determined anew for every /web (DHCP may change it).
    assert "http://192.168.1.31:8765/anmelden" in second
