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


def test_mails_arrive_in_date_order_at_the_mailbox_entry_point():
    fetched = list(dataset.fetched("a" * 24))
    assert [mail.uid for mail in fetched] == list(range(1, 31))
    assert [mail.received_at for mail in fetched] == sorted(mail.received_at for mail in fetched)
    assert {mail.account_id for mail in fetched} == {"a" * 24} and fetched[0].folder == "INBOX"


def _application(store_directory: Path, calls: list):
    @contextmanager
    def application(settings, secrets, topics, prompts, fingerprint, directory):
        def process(mail):
            calls.append(mail.uid)
            (store_directory / f"mail-{mail.uid:024d}.json").write_text("{}", encoding="utf-8")
        orchestrator = SimpleNamespace(precheck=SimpleNamespace(writers={"tasks": object()}), process=process,
                                       config_fingerprint="f" * 64)
        store_directory.mkdir(parents=True, exist_ok=True)
        (store_directory / "llm-budget.json").write_text("{}", encoding="utf-8")
        yield SimpleNamespace(orchestrator=orchestrator, store=SimpleNamespace(directory=store_directory),
                              sources=[SimpleNamespace(reader=SimpleNamespace(account_id="b" * 24))])
        assert orchestrator.precheck.writers == {}
    return application


def test_process_uses_the_normal_entry_point_and_never_a_write_target(tmp_path):
    dataset.configuration(tmp_path, "sk-synthetic")
    calls = []
    store, fingerprint = dataset.process(tmp_path, _application(tmp_path / "data", calls))
    assert store == tmp_path / "data" and fingerprint == "f" * 64 and calls == list(range(1, 31))


def test_export_writes_messages_states_and_a_verifiable_manifest(tmp_path):
    store = tmp_path / "store"
    (store / "history").mkdir(parents=True)
    (store / "mail-1.json").write_text('{"id": 1}', encoding="utf-8")
    (store / "history" / "h.json").write_text("[]", encoding="utf-8")
    (store / "llm-budget.json").write_text("{}", encoding="utf-8")
    output = tmp_path / "out" / "standard-v1"
    output.mkdir(parents=True)
    (output / "veraltet.txt").write_text("alt", encoding="utf-8")
    manifest = dataset.export(store, output, "f" * 64, "abc1234", "model/x")
    assert not (output / "veraltet.txt").exists() and not output.with_name("standard-v1.neu").exists()
    assert sorted(manifest["files"]) == ["history/h.json", "mail-1.json"]
    assert len(manifest["mails"]) == 30 and (output / "mails" / f"{MAILS[0].name}.eml").read_bytes() == message(MAILS[0])
    stored = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert stored == manifest and stored["source_commit"] == "abc1234" and stored["dataset"] == "standard-v1"


def test_main_refuses_a_missing_key_and_builds_with_a_replaced_application(tmp_path, monkeypatch, capsys):
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
    assert dataset.main(["--env", str(env), "--output", str(output)], application) == 0
    assert "30 Mails" in capsys.readouterr().out and len(calls) == 30
    assert json.loads((output / "manifest.json").read_text(encoding="utf-8"))["model"]


def test_the_source_commit_is_the_current_head():
    assert len(dataset.source_commit()) >= 7


def test_the_module_runs_as_a_command(monkeypatch):
    monkeypatch.setattr("sys.argv", ["dataset"])
    with pytest.raises(SystemExit) as exited:
        runpy.run_module("devtools.demo.dataset", run_name="__main__")
    assert exited.value.code == 2
