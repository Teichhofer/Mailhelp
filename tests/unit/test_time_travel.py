"""Planung 4.1, Schritt 9.11: the production default clocks under deterministic time travel.

The other tests inject clocks; these run the real defaults (``datetime.now``, ``time.time``)
so a default that reads the wrong clock or zone cannot hide behind a test double.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import time_machine

from mailhelp.external.oauth import GoogleOAuthTokenProvider
from mailhelp.storage import JsonStore
from mailhelp.web.auth import PairingRefused, WebAuth
from tests.fakes.shared_web_auth import SECRET, code_from

START = datetime(2026, 11, 5, 8, 0, tzinfo=UTC)


def paired(auth, messages):
    auth.request_code("browser", "PC")
    return auth.redeem("browser", code_from(messages), "PC")


def test_a_web_session_lasts_its_configured_days_on_the_real_clock(tmp_path):
    messages = []
    with time_machine.travel(START, tick=False) as traveller, JsonStore(tmp_path) as store:
        auth = WebAuth(store, SECRET, 30, messages.append)
        token = paired(auth, messages)
        assert auth.authenticate(token) is not None
        traveller.move_to(START + timedelta(days=30, seconds=1))
        assert auth.authenticate(token) is None


def test_pairing_codes_expire_after_ten_minutes_on_the_real_clock(tmp_path):
    messages = []
    with time_machine.travel(START, tick=False) as traveller, JsonStore(tmp_path) as store:
        auth = WebAuth(store, SECRET, 30, messages.append)
        auth.request_code("browser", "PC")
        traveller.shift(timedelta(minutes=10, seconds=1))
        with pytest.raises(PairingRefused):
            auth.redeem("browser", code_from(messages), "PC")


def test_google_access_tokens_are_reused_until_shortly_before_they_expire():
    requests = []

    def token(request):
        requests.append(request)
        return httpx.Response(200, json={"access_token": f"token-{len(requests)}", "expires_in": 3600,
                                         "token_type": "Bearer"}, request=request)

    with time_machine.travel(START, tick=False) as traveller:
        # The default clock is bound when the provider is created; time travel still reaches it.
        provider = GoogleOAuthTokenProvider("id", "secret", "refresh", transport=httpx.MockTransport(token))
        try:
            assert provider.access_token() == "token-1"
            traveller.shift(3600 - 61)
            assert provider.access_token() == "token-1"
            traveller.shift(2)
            assert provider.access_token() == "token-2" and len(requests) == 2
        finally:
            provider.close()
