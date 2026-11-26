"""7.1 (D2): the demo dataset tool feeds every synthetic mail at the normal entry point and exports it.

The real generation run uses the configured models once, by hand; these tests replace the application
and never call a model.
"""
from __future__ import annotations

import json
import runpy
from contextlib import contextmanager
from email import message_from_bytes
from email.policy import default
from pathlib import Path
from types import SimpleNamespace

import pytest

from devtools.demo import dataset
from devtools.demo.mails import IRRELEVANT, MAILS, RELEVANT, message
from mailhelp.config import load_all


def test_the_mails_are_synthetic_complete_and_in_reserved_domains():
    assert len(RELEVANT) == 10 and len(IRRELEVANT) == 20 and len({mail.name for mail in MAILS}) == 30
    for mail in MAILS:
        parsed = message_from_bytes(message(mail), policy=default)
        addresses = [item.addr_spec for header in ("From", "To") for item in parsed[header].addresses]
        assert len(addresses) == 2 and all(address.endswith(".example") for address in addresses)
        assert parsed["Message-ID"] == f"<{mail.name}@demo.mailhelp.example>" and parsed["Date"]


def test_the_configuration_is_a_valid_test_mode_installation_without_telegram(tmp_path):
    dataset.configuration(tmp_path, "sk-synthetic")
    settings, secrets, topics, _irrelevant, prompts, _fingerprint = load_all(tmp_path, environ={})
    assert settings.test_mode and not settings.telegram.enabled and settings.personal_info == dataset.PERSONA
    assert secrets.openrouter_api_key.get_secret_value() == "sk-synthetic"
    assert [topic.id for topic in topics] == ["schule", "verein", "musikschule", "foerderverein"]
    assert prompts.prompts


def test_english_generation_uses_english_originals_and_effective_prompts(tmp_path):
    from devtools.demo import mails_en
    from mailhelp.i18n import Locale
    dataset.configuration(tmp_path, "sk-synthetic", Locale.EN)
    settings, _secrets, topics, _ignored, prompts, english_fingerprint = load_all(tmp_path, environ={})
    assert settings.personal_info == mails_en.PERSONA and topics[0].id == "school"
    assert "auf Deutsch zusammen" not in prompts.prompts["summary"].system_prompt
    assert all("in English" in step.system_prompt for step in prompts.prompts.values())
    arrivals = list(dataset.fetched("a" * 24, Locale.EN))
    assert len(arrivals) == 30 and len(mails_en.RELEVANT) == 10 and len(mails_en.IRRELEVANT) == 20
    assert all(b"miller-family.example" in mail.raw for mail in arrivals)
    store = tmp_path / "state"
    store.mkdir()
    # This fake proves export routing; graph integrity is tested on the genuine packaged corpus.
    (store / ("mail-" + "a" * 24 + ".json")).write_text("{}", encoding="utf-8")
    manifest = dataset.export(store, tmp_path / "english", english_fingerprint, "test", "model/x", [], Locale.EN)
    assert manifest["locale"] == Locale.EN and manifest["dataset"] == "standard-en-v1"
    assert len(manifest["files"]) == 1
    dataset.configuration(tmp_path, "sk-synthetic")
    assert load_all(tmp_path, environ={})[-1] != english_fingerprint


def test_mails_arrive_in_date_order_at_the_mailbox_entry_point():
    fetched = list(dataset.fetched("a" * 24))
    assert [mail.uid for mail in fetched] == list(range(1, 31))
    assert [mail.received_at for mail in fetched] == sorted(mail.received_at for mail in fetched)
    assert {mail.account_id for mail in fetched} == {"a" * 24} and fetched[0].folder == "INBOX"


class Result:
    def __init__(self, **fields):
        self.fields = fields

    def model_dump(self, mode):
        return self.fields


class Analyzer:
    """Stands in for the model-backed revision service; the tool wraps these methods to record them."""

    def interpret_telegram_answer(self, proposal, question, answer):
        return "c1", Result(usable=True, normalized_answer=answer, reason="ok")

    def clarify_telegram_answer(self, question, answer, reason, *, current_date=None):
        return "c2", Result(message="genauer")

    def revise_proposal(self, proposal, question, answer):
        return "c3", Result(id=proposal.id, version=proposal.version + 1)


def _application(store_directory: Path, calls: list, submitted: list | None = None):
    submitted = [] if submitted is None else submitted

    @contextmanager
    def application(settings, secrets, topics, prompts, fingerprint, directory):
        def process(mail):
            calls.append(mail.uid)
            message_id = message_from_bytes(mail.raw, policy=default)["Message-ID"]
            proposals = [{"id": "p1", "status": "needs_clarification"}, {"id": "p2", "status": "pending_confirmation"}]
            (store_directory / f"mail-{mail.uid:024d}.json").write_text(json.dumps(
                {"id": f"{mail.uid:024d}", "mail": {"headers": {"message_id": message_id}}, "proposals": proposals}),
                encoding="utf-8")
        orchestrator = SimpleNamespace(precheck=SimpleNamespace(writers={"tasks": object()}), process=process,
                                       config_fingerprint="f" * 64)
        analyzer = Analyzer()

        def poll_once():
            if submitted and submitted[-1].text:
                command = submitted[-1]
                item = SimpleNamespace(source_mail_id=command.mail_id, id=command.proposal_id, version=command.version)
                analyzer.interpret_telegram_answer(item, "Frage?", command.text)
                analyzer.clarify_telegram_answer("Frage?", command.text, "unklar")
                analyzer.revise_proposal(item, "Frage?", command.text)
                submitted.append(SimpleNamespace(text=None))
        dialog = SimpleNamespace(review=SimpleNamespace(web_authorizer=None), poll_once=poll_once,
                                 repository=SimpleNamespace(load_current=lambda mail_id, proposal_id:
                                                            SimpleNamespace(version=1)),
                                 commands=SimpleNamespace(submit=submitted.append))
        store_directory.mkdir(parents=True, exist_ok=True)
        (store_directory / "llm-budget.json").write_text("{}", encoding="utf-8")
        (store_directory / "mail-ohne-kopf.json").write_text('{"id": "x", "proposals": []}', encoding="utf-8")
        yield SimpleNamespace(orchestrator=orchestrator, store=SimpleNamespace(directory=store_directory),
                              analyzer=analyzer, dialog=dialog,
                              sources=[SimpleNamespace(reader=SimpleNamespace(account_id="b" * 24))])
        assert orchestrator.precheck.writers == {} and dialog.review.web_authorizer("web:x")
    return application


def test_the_shipped_mails_need_no_prepared_answer():
    """7.6: the demo mails are complete, so the generation run answers nothing."""
    assert dataset.ANSWERS == {}


def test_process_uses_the_normal_entry_point_and_answers_through_the_dialog(tmp_path, monkeypatch):
    # The answer path stays for datasets that ask something; here it gets two synthetic answers.
    monkeypatch.setattr(dataset, "ANSWERS", {"07-vorspiel": ("Um 16:00 Uhr.",),
                                             "03-workshop-material": ("Von 10 bis 12:30 Uhr.",)})
    dataset.configuration(tmp_path, "sk-synthetic")
    calls, submitted = [], []
    store, fingerprint, recorded = dataset.process(tmp_path, _application(tmp_path / "data", calls, submitted))
    assert store == tmp_path / "basis" and fingerprint == "f" * 64 and calls == list(range(1, 31))
    answers = [command.text for command in submitted if command.text]
    assert sorted(answers) == sorted(text for texts in dataset.ANSWERS.values() for text in texts)
    assert {item["method"] for item in recorded} == set(dataset.REVISION_METHODS)
    assert next(item for item in recorded if item["method"] == "clarify_telegram_answer")["proposal"] is None
    assert all(item["proposal"][2] == 1 for item in recorded if item["proposal"])


def test_export_writes_messages_states_and_a_verifiable_manifest(tmp_path):
    store = tmp_path / "store"
    (store / "history").mkdir(parents=True)
    (store / "mail-1.json").write_text('{"id": 1}', encoding="utf-8")
    (store / "history" / "h.json").write_text("[]", encoding="utf-8")
    (store / "llm-budget.json").write_text("{}", encoding="utf-8")
    output = tmp_path / "out" / "standard-v1"
    output.mkdir(parents=True)
    (output / "veraltet.txt").write_text("alt", encoding="utf-8")
    manifest = dataset.export(store, output, "f" * 64, "abc1234", "model/x", [{"method": "x"}])
    assert not (output / "veraltet.txt").exists() and not output.with_name("standard-v1.neu").exists()
    assert sorted(manifest["files"]) == ["history/h.json", "mail-1.json"]
    assert len(manifest["mails"]) == 30 and (output / "mails" / f"{MAILS[0].name}.eml").read_bytes() == message(MAILS[0])
    stored = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert stored == manifest and stored["source_commit"] == "abc1234" and stored["dataset"] == "standard-v1"
    assert json.loads((output / "answers.json").read_text(encoding="utf-8")) == [{"method": "x"}]


@pytest.mark.parametrize("locale", ["de", "en"])
def test_main_refuses_a_missing_key_and_builds_with_a_replaced_application(tmp_path, monkeypatch, capsys, locale):
    env = tmp_path / ".env"
    env.write_text("ANDERES=1\n", encoding="utf-8")
    assert dataset.main(["--env", str(env)]) == 2
    assert "OPENROUTER_API_KEY fehlt" in capsys.readouterr().err
    env.write_text("OPENROUTER_API_KEY=sk-synthetic\n", encoding="utf-8")
    monkeypatch.setattr(dataset, "source_commit", lambda: "abc1234")
    calls = []

    def application(*args):
        return _application(Path(args[5]) / "data", calls)(*args)

    output = tmp_path / "standard-v1"
    assert dataset.main(["--env", str(env), "--output", str(output), "--locale", locale], application) == 0
    assert "30 Mails" in capsys.readouterr().out and len(calls) == 30
    assert json.loads((output / "manifest.json").read_text(encoding="utf-8"))["model"]
    from mailhelp.i18n import Locale
    assert json.loads((output / "manifest.json").read_text(encoding="utf-8")).get("locale", "de") == Locale(locale)


def test_the_source_commit_is_the_current_head():
    assert len(dataset.source_commit()) >= 7


def test_english_default_output_is_a_separate_package(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("OPENROUTER_API_KEY=sk-synthetic\n", encoding="utf-8")
    output = tmp_path / "standard-v1"
    monkeypatch.setattr(dataset, "OUTPUT", output)
    monkeypatch.setattr(dataset, "source_commit", lambda: "abc1234")
    calls = []
    def application(*args):
        return _application(Path(args[5]) / "data", calls)(*args)
    assert dataset.main(["--env", str(env), "--locale", "en"], application) == 0
    assert not output.exists() and (output.with_name("standard-en-v1") / "manifest.json").is_file()


def test_export_retains_the_old_package_when_publication_fails(tmp_path, monkeypatch):
    store = tmp_path / "store"
    store.mkdir()
    output = tmp_path / "package"
    output.mkdir()
    (output / "old.json").write_text("old", encoding="utf-8")
    import os

    from mailhelp.persistence import storage
    original = os.replace
    def fail_publish(path, target):
        if Path(path) == output.with_name("package.neu"):
            raise OSError("publication failed")
        return original(path, target)
    monkeypatch.setattr(storage.os, "replace", fail_publish)
    with pytest.raises(OSError, match="publication failed"):
        dataset.export(store, output, "f" * 64, "abc1234", "model", [])
    assert (output / "old.json").read_text(encoding="utf-8") == "old"
    assert not output.with_name("package.previous").exists()
    output.with_name("package.previous").mkdir()
    with pytest.raises(FileExistsError, match="needs recovery"):
        dataset.export(store, output, "f" * 64, "abc1234", "model", [])


def test_a_failed_first_publication_leaves_no_package_and_no_backup(tmp_path, monkeypatch):
    store = tmp_path / "store"
    store.mkdir()
    output = tmp_path / "first"
    from mailhelp.persistence import storage
    def fail_publish(path, target):
        raise OSError("publication failed")
    monkeypatch.setattr(storage.os, "replace", fail_publish)
    with pytest.raises(OSError, match="publication failed"):
        dataset.export(store, output, "f" * 64, "abc1234", "model", [])
    assert not output.exists() and not output.with_name("first.previous").exists()


def test_regression_export_survives_a_briefly_locked_directory(tmp_path, monkeypatch):
    """8.7.11: under the full check on Windows the rename of ``standard-en-v1.neu`` failed with
    "[WinError 5] Zugriff verweigert" while a scanner held the fresh directory open."""
    import os

    from mailhelp.persistence import storage
    store = tmp_path / "store"
    store.mkdir()
    output = tmp_path / "package"
    output.mkdir()
    original, blocked = os.replace, []
    def locked_twice(source, target):
        if str(source).endswith(".neu") and len(blocked) < 2:
            blocked.append(Path(source).name)
            raise PermissionError(5, "Zugriff verweigert")
        return original(source, target)
    monkeypatch.setattr(storage.os, "replace", locked_twice)
    monkeypatch.setattr(storage.time, "sleep", lambda _seconds: None)
    dataset.export(store, output, "f" * 64, "abc1234", "model", [])
    assert blocked == ["package.neu", "package.neu"] and (output / "manifest.json").is_file()
    assert not output.with_name("package.previous").exists()


def test_the_module_runs_as_a_command(monkeypatch):
    monkeypatch.setattr("sys.argv", ["dataset"])
    with pytest.raises(SystemExit) as exited:
        runpy.run_module("devtools.demo.dataset", run_name="__main__")
    assert exited.value.code == 2
