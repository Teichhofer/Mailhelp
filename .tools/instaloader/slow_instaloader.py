"""Run Instaloader's CLI with an additional pause before every API query."""

from functools import partial
import time
from unittest.mock import patch

from instaloader import Instaloader, RateController
from instaloader import __main__ as cli


class SlowRateController(RateController):
    """Keep upstream tracking/backoff and add 30 seconds before each query."""

    def wait_before_query(self, query_type):
        time.sleep(30)
        super().wait_before_query(query_type)


def main():
    """Preserve the standard CLI, login, resume, and error handling."""
    print("Slow mode: 30 seconds before each API query; automatic backoff remains enabled.", flush=True)
    with patch.object(cli, "Instaloader", partial(Instaloader, rate_controller=SlowRateController)):
        cli.main()
