"""Real process checkpoints for the help worker, with a durable synthetic model counter."""
from pathlib import Path
from types import SimpleNamespace

from mailhelp.config import HelpChatSettings
from mailhelp.helpdocs import HelpAnswer, load
from mailhelp.helpdocs.chat import HelpChat
from mailhelp.storage import JsonStore

QUESTION = "Was bewirkt das Abrufintervall?"


def run(directory, point, connection, coverage_file):
    cov = None
    if coverage_file:
        from coverage import Coverage
        cov = Coverage.current()
        if cov is None:
            cov = Coverage(data_file=coverage_file, data_suffix=True, branch=True, source=["mailhelp"])
            cov.start()

    def checkpoint(name):
        if point == name:
            if cov is not None:
                cov.save()
            connection.send(name)
            assert connection.poll(120), "Parent did not terminate the child"
            connection.recv()

    with JsonStore(Path(directory)) as store:
        class Analyzer:
            prompts = SimpleNamespace(prompts={"settings_help": object()})

            def settings_help(self, question, sources, history, settings, *, before_call):
                before_call()
                count = store.load("synthetic-model-calls") or {"count": 0}
                store.save("synthetic-model-calls", {"count": count["count"] + 1})
                checkpoint("running")
                return "synthetic-call", HelpAnswer(answer="Das Intervall steuert den Abruf.",
                                                     source_ids=[sources[0].id])

        service = HelpChat(store, HelpChatSettings, load, Analyzer, lambda sid: True, sessions=lambda: ["session"])
        changed = service.recover()
        if point is None:
            assert service.run_once() is False
            replay = service.submit("session", QUESTION, "synthetic-key", 1)
            connection.send((changed, replay.status, (store.load("synthetic-model-calls") or {"count": 0})["count"]))
        else:
            service.submit("session", QUESTION, "synthetic-key", 1)
            checkpoint("queued")
            service.run_once()
            checkpoint("completed")
    if cov is not None:
        cov.stop()
        cov.save()

