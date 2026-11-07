"""Admission must remain usable while the application store is busy."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event, Thread
from time import perf_counter

import pytest


@pytest.mark.slow
def test_web_acknowledges_while_another_thread_holds_the_store_lock_for_five_seconds(web):
    fields = web.form('/', kind='reject', proposal_id='elternabend')
    held, release = Event(), Event()
    def hold():
        with web.store.locked():
            held.set()
            release.wait(5)
    holder = Thread(target=hold)
    holder.start()
    assert held.wait(1)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            started = perf_counter()
            future = pool.submit(web.submit, fields, accept='application/json')
            try:
                response = future.result(timeout=0.3)
            except TimeoutError:
                release.set()
                pytest.fail('POST /aktion waits for the application store lock')
            elapsed = perf_counter() - started
            assert response.status == 202 and elapsed < 0.3
            assert holder.is_alive()
    finally:
        release.set()
        holder.join(6)
