"""Starting without the required configuration files ends with guidance, not a traceback."""
import sys

import pytest

from mailhelp import cli
from mailhelp.config.loader import MissingConfiguration, load_all


def test_a_missing_config_yaml_ends_with_guidance_instead_of_a_traceback(tmp_path, monkeypatch, capsys):
    # Regression: an empty configuration directory crashed with FileNotFoundError and a traceback.
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--check", "--config-directory", str(tmp_path)])
    assert cli.main() == 2
    error = capsys.readouterr().err
    assert str(tmp_path / "config.yaml") in error and "config.example.yaml" in error
    assert "Traceback" not in error


def test_a_missing_prompts_yaml_is_named(tmp_path):
    (tmp_path / "config.yaml").write_text("timezone: Europe/Berlin\n", encoding="utf-8")
    with pytest.raises(MissingConfiguration) as raised:
        load_all(tmp_path, {})
    assert raised.value.path == tmp_path / "prompts.yaml"
    # It stays a FileNotFoundError for callers that already handle that.
    assert isinstance(raised.value, FileNotFoundError)
