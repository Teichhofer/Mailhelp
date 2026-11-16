"""7.1 (D1): the demo is chosen only by --demo/-demo and never opens a normal installation."""
from __future__ import annotations

import json
from threading import Event
from types import SimpleNamespace

import pytest

from mailhelp import cli
from mailhelp.app import demo


def test_an_empty_directory_becomes_a_demo_directory_and_stays_one(tmp_path):
    runtime = tmp_path / "neu" / "demo"
    demo.prepare_directory(runtime)
    assert json.loads((runtime / demo.MARKER).read_text(encoding="utf-8")) == demo.MARKER_CONTENT
    assert demo.is_demo_directory(runtime)
    demo.prepare_directory(runtime)  # a restart opens the same demo directory again
    assert demo.is_demo_directory(runtime)


@pytest.mark.parametrize("name", ["config.yaml", ".env", "irgendwas.txt"])
def test_a_directory_with_other_files_is_refused(tmp_path, name):
    (tmp_path / name).write_text("x", encoding="utf-8")
    with pytest.raises(demo.DemoDirectoryError, match="leeres Laufzeitverzeichnis"):
        demo.prepare_directory(tmp_path)
    assert not demo.is_demo_directory(tmp_path)


@pytest.mark.parametrize(("content", "message"), [("{kaputt", "nicht lesbar"),
                                                   ('{"kind": "anderes"}', "keiner bekannten Demo-Version")])
def test_a_damaged_or_foreign_marker_is_refused(tmp_path, content, message):
    (tmp_path / demo.MARKER).write_text(content, encoding="utf-8")
    with pytest.raises(demo.DemoDirectoryError, match=message):
        demo.prepare_directory(tmp_path)


def test_the_secret_is_created_once_and_a_short_one_is_replaced(tmp_path):
    first = demo.demo_secret(tmp_path)
    assert len(first) >= 32 and demo.demo_secret(tmp_path) == first
    (tmp_path / demo.SECRET).write_text("kurz\n", encoding="utf-8")
    replaced = demo.demo_secret(tmp_path)
    assert replaced != "kurz" and len(replaced) >= 32


def test_settings_come_from_the_environment_and_default_to_local_access():
    default = demo.demo_settings({})
    assert (default.host, default.port, default.lan_access) == ("127.0.0.1", 8765, False)
    assert default.allowed_hosts == ["localhost:8765", "127.0.0.1:8765"]
    custom = demo.demo_settings({"MAILHELP_DEMO_PORT": "9000", "MAILHELP_DEMO_HOST": "0.0.0.0",
                                 "MAILHELP_DEMO_ALLOWED_HOSTS": "demo.example.org,,www.example.org"})
    assert (custom.host, custom.port) == ("0.0.0.0", 9000)
    assert custom.allowed_hosts == ["localhost:9000", "127.0.0.1:9000", "demo.example.org", "www.example.org"]


def test_run_demo_serves_until_stopped_and_refuses_a_foreign_directory(tmp_path, monkeypatch):
    started = []

    class Server:
        def __init__(self, host, port, app, logger):
            self.address = (host, port)

        def start(self):
            started.append(self.address)

        def stop(self):
            started.append("stopped")

    monkeypatch.setattr(demo, "WebServer", Server)
    shutdown, messages = SimpleNamespace(), []
    emit = lambda text: (messages.append(text), shutdown.stop())
    assert demo.run_demo(tmp_path / "demo", shutdown, emit=emit, environ={"MAILHELP_DEMO_PORT": "8899"}) == 0
    assert started == [("127.0.0.1", 8899), "stopped"]
    assert messages == ["Mailhelp-Demo: http://localhost:8899/anmelden"]
    assert (tmp_path / "demo" / "data" / "demo").is_dir() and (tmp_path / "demo" / demo.SECRET).is_file()
    (tmp_path / "normal").mkdir()
    (tmp_path / "normal" / "config.yaml").write_text("x", encoding="utf-8")
    messages.clear()
    assert demo.run_demo(tmp_path / "normal", shutdown, emit=messages.append) == 2
    assert messages[0].startswith("Demo nicht gestartet:")


def test_the_worker_executes_actions_until_the_instance_stops():
    stopped, calls = Event(), []
    runtimes = SimpleNamespace(work=lambda: (calls.append(1), stopped.set()))
    demo._work(runtimes, stopped)
    assert calls == [1]


@pytest.mark.parametrize("flag", ["--demo", "-demo"])
def test_both_spellings_start_the_same_demo(tmp_path, monkeypatch, flag):
    calls = []
    monkeypatch.setattr(demo, "run_demo", lambda directory, shutdown: calls.append(directory) or 0)
    monkeypatch.setattr("sys.argv", ["mailhelp", flag, "--config-directory", str(tmp_path)])
    assert cli.main() == 0 and calls == [tmp_path]


@pytest.mark.parametrize("extra", [["--check"], ["--max-mails", "3"], ["--pair"], ["--log-directory", "logs"]])
def test_the_demo_cannot_be_combined_with_another_mode(tmp_path, monkeypatch, capsys, extra):
    monkeypatch.setattr(demo, "run_demo", lambda directory, shutdown: pytest.fail("Demo darf nicht starten"))
    monkeypatch.setattr("sys.argv", ["mailhelp", "--demo", "--config-directory", str(tmp_path), *extra])
    with pytest.raises(SystemExit) as exited:
        cli.main()
    assert exited.value.code == 2
    assert "--demo lässt sich nicht mit anderen Optionen kombinieren" in capsys.readouterr().err


def test_a_normal_start_refuses_a_demo_directory(tmp_path, monkeypatch, capsys):
    demo.prepare_directory(tmp_path)
    monkeypatch.setattr("mailhelp.app.bootstrap.run_initial_setup",
                        lambda *args, **kwargs: pytest.fail("Einrichtung darf nicht starten"))
    for argv in (["--config-directory", str(tmp_path)], ["--check", "--config-directory", str(tmp_path)]):
        monkeypatch.setattr("sys.argv", ["mailhelp", *argv])
        assert cli.main() == 2
        assert "ist ein Demo-Verzeichnis" in capsys.readouterr().err
