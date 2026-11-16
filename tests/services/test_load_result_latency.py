"""4.4.1: with an instance-sized store, a web action shows its result within 0.5 s.

Two thousand synthetic mails, 500 proposals and a mailbox poll that saves state twice
a second. Measured as a browser sees it: from the POST until the overview shows the
result, polling the action status every 0.1 s like app.js.
"""
import json
import sys
from statistics import median
from threading import Event, Thread
from time import perf_counter, sleep

import pytest

from tests.fakes.shared_web_actions import web as web
from tests.scenarios.web_scenario import proposal, save_mail

MAILS = 2000
TEXT = "Synthetischer Mailtext ohne echte Daten. " * 250


@pytest.mark.slow
def test_an_action_shows_its_result_within_half_a_second_with_two_thousand_mails(web):
    for number in range(100, 100 + MAILS):
        items = [proposal(number, f"p{number}", status="rejected")] if number % 4 == 0 else []
        save_mail(web.store, number, "Absender <absender@example.test>", f"Mail {number}", items, text=TEXT)
    web.run()  # The first pass after a start checks every proposal once.
    passes = []
    for _ in range(5):
        started = perf_counter()
        web.run()
        passes.append((perf_counter() - started) * 1000)
    stop = Event()
    def operator():
        while not stop.is_set():
            web.run()
            stop.wait(0.1)
    def mailbox_poll():
        number = 0
        while not stop.is_set():
            number += 1
            web.store.save("imap-synthetic-folder", {"uid": number})
            stop.wait(0.5)
    threads = [Thread(target=operator), Thread(target=mailbox_poll)]
    for thread in threads:
        thread.start()
    results, timings = [], []
    try:
        for item in ("formular", "elternabend", "zahnarzt", "fest", "boese"):
            fields = web.form("/", kind="reject", proposal_id=item)
            started = perf_counter()
            response = web.submit(fields, accept="application/json")
            entry_id = json.loads(response.body)["id"]
            while not json.loads(web.browser.request("GET", f"/api/aktion/{entry_id}",
                                                     accept="application/json").body)["target"]:
                assert perf_counter() - started < 10
                sleep(0.1)
            page = web.browser.request("GET", "/").body.decode()
            results.append((perf_counter() - started) * 1000)
            assert response.status == 202 and "data-command-result" in page
            timings.append(web.commands.get(entry_id).timings)
            sleep(0.3)
    finally:
        stop.set()
        for thread in threads:
            thread.join(30)
    assert not any(thread.is_alive() for thread in threads)
    print("V441_LOAD " + json.dumps({"platform": sys.platform, "mails": MAILS, "median_pass_ms": median(passes),
          "median_result_ms": median(results), "maximum_result_ms": max(results),
          "results_ms": results, "timings": timings}))
    assert median(passes) < 250, passes
    assert median(results) < 500 and max(results) < 1000, results
