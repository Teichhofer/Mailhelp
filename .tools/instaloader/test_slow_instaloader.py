"""Offline verification of delays, upstream backoff, and CLI restoration."""

from unittest.mock import Mock, patch
import sys

import pytest
from instaloader import Instaloader, RateController
from instaloader import __main__ as cli

import slow_instaloader as slow


@pytest.mark.parametrize("query_type", ["other", "iphone", "graphql-id"])
def test_every_query_waits_before_upstream_tracking(query_type):
    events = []
    controller = slow.SlowRateController(Mock())
    with (
        patch("random.uniform", return_value=45),
        patch.object(slow.time, "sleep", side_effect=lambda seconds: events.append(("pause", seconds))),
        patch.object(RateController, "wait_before_query", side_effect=lambda kind: events.append(("upstream", kind))),
    ):
        controller.wait_before_query(query_type)
        controller.wait_before_query(query_type)
    assert events == [("pause", 30), ("upstream", query_type)] * 2


def test_429_keeps_upstream_backoff_and_next_query_tracking():
    context = Mock()
    controller = slow.SlowRateController(context)
    with (
        patch.object(slow.time, "monotonic", return_value=1000),
        patch.object(slow.time, "sleep"),
        patch.object(RateController, "sleep") as backoff,
    ):
        controller.wait_before_query("other")
        controller.handle_429("other")
        backoff.assert_called_once_with(666)
        controller.wait_before_query("other")
        assert backoff.call_count == 2
    assert controller._query_timestamps["other"] == [1000, 1000]
    context.error.assert_called()


def test_new_instance_starts_fresh_and_still_waits():
    with (
        patch.object(slow.time, "sleep") as sleep,
    ):
        first = slow.SlowRateController(Mock())
        first.wait_before_query("other")
        second = slow.SlowRateController(Mock())
        assert second._query_timestamps == {}
        second.wait_before_query("other")
    assert sleep.call_count == 2
    assert sleep.call_args_list == [((30,),), ((30,),)]


@pytest.mark.parametrize("failure", [False, True])
def test_cli_uses_slow_controller_and_restores_constructor(failure):
    original = cli.Instaloader

    def fake_main():
        loader = cli.Instaloader(quiet=True)
        assert isinstance(loader, Instaloader)
        assert isinstance(loader.context._rate_controller, slow.SlowRateController)
        assert loader.context.sleep is True
        assert loader.context.is_logged_in is False
        loader.close()
        if failure:
            raise SystemExit(3)

    with patch.object(cli, "main", side_effect=fake_main):
        if failure:
            with pytest.raises(SystemExit) as caught:
                slow.main()
            assert caught.value.code == 3
        else:
            slow.main()
    assert cli.Instaloader is original


def test_anonymous_cli_never_imports_or_saves_account_session():
    profile = Mock(username="raus.life", is_private=False)
    arguments = [
        "slow_instaloader", "--quiet", "--no-iphone",
        "--abort-on=302,400,401,403,429", "--max-connection-attempts=1",
        "--no-compress-json", "--sanitize-paths",
        "--dirname-pattern=downloads/instagram/{target}", "raus.life",
    ]
    with (
        patch.object(sys, "argv", arguments),
        patch.object(Instaloader, "check_profile_id", return_value=profile),
        patch.object(Instaloader, "download_profiles") as download,
        patch.object(cli, "import_session") as import_session,
        patch.object(Instaloader, "load_session_from_file") as load_session,
        patch.object(Instaloader, "interactive_login") as login,
        patch.object(Instaloader, "save_session_to_file") as save_session,
    ):
        with pytest.raises(SystemExit) as caught:
            slow.main()
    assert caught.value.code == 0
    download.assert_called_once()
    import_session.assert_not_called()
    load_session.assert_not_called()
    login.assert_not_called()
    save_session.assert_not_called()
