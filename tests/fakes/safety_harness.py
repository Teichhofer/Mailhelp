"""Deterministic thread/process checkpoints and an independent synthetic provider.

No production credentials, network access or timing-based synchronisation.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Event

from mailhelp.storage import JsonStore, atomic_replace

MAIL = f"{1:024x}"

LIMIT = 20


class Gate:
    def __init__(self):
        self.entered, self.release = Event(), Event()

    def hold(self):
        self.entered.set()
        assert self.release.wait(LIMIT), "Checkpoint was not released"

    @contextmanager
    def during(self, operation):
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(operation)
            try:
                assert self.entered.wait(LIMIT), "Checkpoint was not reached"
                yield future
            finally:
                self.release.set()
            future.result(timeout=LIMIT)


class PersistentWriter:
    """Provider state survives the application process, including actual call history."""

    def __init__(self, path: Path, checkpoint=lambda point: None, reconcile="found"):
        self.path, self.checkpoint, self.mode = path, checkpoint, reconcile

    def state(self):
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {
            "entries": {}, "calls": []}

    def _save(self, state):
        atomic_replace(self.path, json.dumps(state, indent=2, sort_keys=True) + "\n")

    def reconcile(self, key):
        state = self.state()
        state["calls"].append(["reconcile", key])
        self._save(state)
        if self.mode == "error":
            raise RuntimeError("Synthetic reconciliation failure")
        if self.mode == "invalid":
            return {"id": False}
        return state["entries"].get(key) if self.mode == "found" else None

    def create(self, proposal, key):
        state = self.state()
        state["calls"].append(["create", key])
        result = {"id": f"external-{len(state['entries']) + 1}", "url": "https://provider.test/item"}
        state["entries"][key] = result
        self._save(state)
        self.checkpoint("A2")
        return result


class ProcessHarness:
    """Spawn with real store locking; always reap children, even on failed assertions."""

    def __init__(self, directory, provider, coverage_file=None):
        self.directory, self.provider, self.coverage_file = directory, provider, coverage_file

    def run(self, point=None, mode="found"):
        from multiprocessing import get_context

        from coverage import Coverage
        from safety_process import run_application
        active = Coverage.current()
        coverage_file = self.coverage_file or (active.config.data_file if active is not None else None)
        context = get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(target=run_application, args=(str(self.directory), str(self.provider),
                                  point, child, mode, coverage_file))
        process.start()
        child.close()
        try:
            assert parent.poll(LIMIT), "Application did not reach checkpoint or finish"
            result = parent.recv()
            if point is not None:
                assert result == ("checkpoint", point), result
                process.kill()
            process.join(LIMIT)
            assert not process.is_alive(), "Application process did not exit"
            assert (process.exitcode != 0) if point else (process.exitcode == 0)
            return result
        finally:
            if process.is_alive():
                process.kill()
                process.join(LIMIT)
            parent.close()


def seed(directory, merge=False, web=False):
    # Parent-only fixtures must not import the whole web application in every spawned child.
    from shared_web_auth import SECRET
    from web_scenario import mail_id, proposal, save_mail

    from mailhelp.review.commands import ReviewCommand
    from mailhelp.review.inbox import CommandInbox
    from mailhelp.web.auth import WebAuth

    with JsonStore(directory) as store:
        item = proposal(1, "target" if merge else "action", title="Synthetische Aufgabe",
                        protected_fields=["title"])
        save_mail(store, 1, "a@example.test", "Synthetisch", [item])
        actor = "telegram:1:2"
        if web:
            auth = WebAuth(store, SECRET, 30, lambda text: None)
            code = auth.issue_code()
            token = auth.redeem("browser", code, "Testgerät")
            actor = f"web:{auth.authenticate(token).id}"
        if merge:
            source = proposal(2, "source", title=item.title, description="Zusätzliche Quelle")
            save_mail(store, 2, "b@example.test", "Synthetisch", [source])
            command = ReviewCommand(kind="merge_proposals", source="telegram", actor=actor,
                mail_id=source.source_mail_id, proposal_id=source.id, version=1,
                target_ref={"mail_id": MAIL, "proposal_id": item.id}, target_version=1,
                idempotency_key="synthetic-merge")
        else:
            command = ReviewCommand(kind="confirm", source="web" if web else "telegram", actor=actor,
                mail_id=MAIL, proposal_id=item.id, version=1, idempotency_key="synthetic-confirm")
        entry, _ = CommandInbox(store).submit(command)
        return entry.id


