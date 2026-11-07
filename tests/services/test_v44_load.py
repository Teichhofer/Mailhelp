"""Five authenticated browsers remain responsive during blocked analysis and delivery."""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from statistics import median
from threading import Event, Thread
from time import perf_counter

from mailhelp.mailbox.imap import FetchedMail
from mailhelp.models import ProposalStatus
from tests.fakes.shared_application import Imap, Orch, Telegram, app
from tests.fakes.shared_web_actions import web as web
from tests.fakes.shared_web_auth import Browser, code_from
from tests.scenarios.web_scenario import proposal, save_mail


def test_five_browsers_accept_during_analysis_delivery_and_a_five_second_store_lock(web, tmp_path):
    items = [proposal(42, f"load-{index}") for index in range(5)]
    save_mail(web.store, 42, "Synthetic <synthetic@example.test>", "Synthetic load", items)
    browsers, forms = [], []
    codes = []
    web.auth.notify = codes.append
    clock = web.auth.clock
    for index, item in enumerate(items):
        browser = web.browser if index == 0 else Browser(web.app, agent=f"synthetic-browser-{index}")
        if index:
            # These are pre-existing browser sessions, paired over separate rate-limit windows.
            web.auth.clock = lambda index=index: clock() + timedelta(hours=index)
            csrf = browser.csrf()
            assert browser.request("POST", "/anmelden/code", {"csrf": csrf}).status == 303
            browser.request("POST", "/anmelden", {"csrf": csrf, "code": code_from(codes)})
        fields = web.form("/", kind="already_done", proposal_id=item.id)
        session = web.auth.authenticate(browser.cookies["mh_session"])
        fields["csrf"] = web.auth.csrf_token(session.id)
        browsers.append(browser)
        forms.append(fields)
    release, analysing, sending, held = Event(), Event(), Event(), Event()
    class HeldAnalysis(Orch):
        def process(self, mail):
            analysing.set()
            assert release.wait(15)
            return super().process(mail)
    service = app(tmp_path, Imap([(1, [FetchedMail("INBOX", 1, 99, b"Subject: Synthetic\n\nSynthetic")])]),
                  Telegram([]), HeldAnalysis(), store=web.store)
    service.dialog = web.dialog
    original_send = web.telegram.send
    def send(*args, **kwargs):
        sending.set()
        assert release.wait(15)
        original_send(*args, **kwargs)
    web.telegram.send = send
    web.dialog.outbox.enabled = False
    mail = Thread(target=service.mailbox.poll)
    notification = Thread(target=web.dialog.send, args=(2, "synthetic blocked delivery"))
    mail.start()
    notification.start()
    try:
        assert analysing.wait(5) and sending.wait(5)
        # Like the composed application, action-result notices use their own durable queue.
        web.dialog.outbox.background = lambda reference: "background-notification"
        def hold_store():
            with web.store.locked():
                held.set()
                Event().wait(5)
        holder = Thread(target=hold_store)
        holder.start()
        assert held.wait(5)
        def submit(pair):
            started = perf_counter()
            response = pair[0].request("POST", "/aktion", pair[1], accept="application/json")
            return response, (perf_counter() - started) * 1000
        with ThreadPoolExecutor(max_workers=5) as pool:
            measured = list(pool.map(submit, zip(browsers, forms, strict=True)))
        responses = [response for response, _ in measured]
        accepts = [elapsed for _, elapsed in measured]
        assert holder.is_alive(), "The store lock was released before admission finished"
        assert median(accepts) < 100 and max(accepts) < 300, accepts
        # Even the redirected overview must render without acquiring the held lock.
        assert browsers[0].request("GET", "/").status == 200
        holder.join(6)
        assert not holder.is_alive()
        ids = [json.loads(response.body)["id"] for response in responses]
        assert all(response.status == 202 for response in responses) and len(set(ids)) == 5
        web.run()
        timings = [web.commands.get(entry_id).timings for entry_id in ids]
        waits = [timing["queue_wait_ms"] for timing in timings]
        assert min(waits) >= 4900
        assert web.commands.latencies()["count"] == 5
        assert all(timing["dialog_lock_wait_ms"] >= 0 and timing["store_lock_wait_ms"] >= 0 for timing in timings)
        assert mail.is_alive() and notification.is_alive() and not release.is_set()
        assert web.writer.created == web.writer.reconciled == 0
        for browser, fields, response in zip(browsers, forms, responses, strict=True):
            assert json.loads(browser.request("POST", "/aktion", fields, accept="application/json").body)["id"] == json.loads(response.body)["id"]
        assert all(web.dialog.repository.load_current(item.source_mail_id, item.id).status == ProposalStatus.REJECTED
                   for item in items)
        print("V44_BUSY_LOAD " + json.dumps({"platform": sys.platform, "browsers": 5,
              "median_accept_ms": median(accepts), "maximum_accept_ms": max(accepts),
              "median_queue_ms": median(waits), "maximum_queue_ms": max(waits), "timings": timings}))
    finally:
        release.set()
        mail.join(10)
        notification.join(10)
        service.stop()
    assert not mail.is_alive() and not notification.is_alive()
