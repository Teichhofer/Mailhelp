"""CLI path parsing remains native and does not hard-code either separator style."""
from pathlib import Path, PurePosixPath, PureWindowsPath
import sys

import pytest

from mailhelp.cli import main


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
