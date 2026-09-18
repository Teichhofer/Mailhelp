"""CLI path parsing remains native and does not hard-code either separator style."""
from pathlib import Path, PurePosixPath, PureWindowsPath
from contextlib import contextmanager
import sys

import pytest

from mailhelp.cli import _positive_int, main


@pytest.mark.parametrize("spelling", [
    str(PurePosixPath("workspace/Mailhelp/config")),
    str(PureWindowsPath(r"C:\Mailhelp\config")),
])
def test_cli_forwards_posix_and_windows_path_spellings(monkeypatch, capsys, spelling):
    captured = []
    monkeypatch.setattr("mailhelp.cli.load_all", lambda directory: captured.append(directory) or (None, None, [], None, "fingerprint"))
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--config-directory", spelling, "--check"])
    assert main() == 0
    assert captured == [Path(spelling)]
    assert capsys.readouterr().out == "Konfiguration ist gültig.\n"


def test_cli_forwards_mail_limit_and_rejects_non_positive_values(monkeypatch):
    class App:
        def __init__(self): self.limit = None
        def run(self, max_mails=None): self.limit = max_mails

    application = App()
    @contextmanager
    def builder(*_args):
        yield application
    monkeypatch.setattr("mailhelp.cli.load_all", lambda _directory: (None, None, [], None, "fingerprint"))
    monkeypatch.setattr("mailhelp.cli.build_application", builder)
    monkeypatch.setattr("mailhelp.cli.signal.signal", lambda *_args: None)
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--max-mails", "10"])

    assert main() == 0
    assert application.limit == 10
    assert _positive_int("1") == 1
    with pytest.raises(Exception, match="mindestens 1"):
        _positive_int("0")
