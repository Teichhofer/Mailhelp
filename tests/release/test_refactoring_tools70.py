"""7.0.1: the measuring tools of the refactoring, with synthetic packages and states."""
from __future__ import annotations

import json
import runpy
import sys

import pytest

from devtools import code_metrics, state_roundtrip
from mailhelp.domain.run import TelegramOffset
from mailhelp.persistence.storage import JsonStore


def _package(tmp_path):
    package = tmp_path / "src" / "mailhelp"
    (package / "web").mkdir(parents=True)
    (package / "__init__.py").write_text("from . import web\n", encoding="utf-8")
    (package / "tools.py").write_text("import json\nimport mailhelp.web.pages\n", encoding="utf-8")
    (package / "web" / "__init__.py").write_text("from .. import tools\n", encoding="utf-8")
    body = "\n".join(f"    x{i} = {i}" for i in range(70))
    (package / "web" / "pages.py").write_text(
        "from ..tools import json\nfrom . import helper\n\n\n"
        "class Page:\n    def render(self, a, b, c, d, e, f, g, h, i, j, *, k):\n"
        "        from mailhelp.tools import json\n" + body.replace("    x", "        x") + "\n"
        "        return json\n\n\nasync def later():\n    import os\n    return os\n",
        encoding="utf-8")
    (package / "web" / "helper.py").write_text("", encoding="utf-8")
    return package


def test_metrics_count_sizes_parameters_late_imports_and_area_edges(tmp_path):
    figures = code_metrics.measure(_package(tmp_path))
    assert figures["files"] == 5 and figures["functions"] == 2
    longest = figures["longest_functions"][0]
    assert longest == {"file": "src/mailhelp/web/pages.py", "name": "render", "lines": 73, "parameters": 12}
    assert figures["functions_over_60_lines"] == figures["functions_over_10_parameters"] == 1
    assert figures["functions_over_80_lines"] == figures["functions_over_100_lines"] == 0
    assert figures["largest_classes"][0]["methods"] == 1
    assert figures["late_imports"] == 2 and figures["late_imports_by_file"] == {"src/mailhelp/web/pages.py": 2}
    # Relative and absolute imports across areas; imports within an area and of other packages are no edges.
    assert figures["imports_between_areas"] == {"mailhelp -> web": 1, "tools -> web": 1, "web -> tools": 3}


def test_metrics_command_writes_a_report_or_prints_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(code_metrics, "PACKAGE", _package(tmp_path))
    monkeypatch.setattr(code_metrics.measure, "__defaults__", (code_metrics.PACKAGE,))
    report = tmp_path / "report.json"
    assert code_metrics.main(["--output", str(report)]) == 0
    assert json.loads(report.read_text(encoding="utf-8"))["files"] == 5
    assert code_metrics.main([]) == 0
    assert json.loads(capsys.readouterr().out)["functions"] == 2


def _states(tmp_path):
    directory = tmp_path / "state"
    with JsonStore(directory) as store:
        store.save("telegram-offset", TelegramOffset(offset=5).model_dump(mode="json"))
    (directory / "telegram-dialog.json").write_text("{broken", encoding="utf-8")
    (directory / ("mail-" + "a" * 24 + ".json")).write_text('{"schema_version": 1}', encoding="utf-8")
    offset = directory / "telegram-offset.json"
    (directory / "proposal-x-y.json").write_text("{}", encoding="utf-8")
    (directory / "web-sessions.json").write_text('{"sessions": []}', encoding="utf-8")
    (directory / "leftover.tmp").write_text("ignored", encoding="utf-8")
    return directory, offset


def test_roundtrip_reports_identical_rewritten_invalid_and_unmodelled_files_without_content(tmp_path):
    directory, offset = _states(tmp_path)
    first = state_roundtrip.check(directory)
    kinds = first["kinds"]
    assert kinds["telegram-offset"] == {"files": 1, "identical": 1, "rewritten": 0, "invalid": 0}
    assert kinds["telegram-dialog"]["invalid"] == kinds["mail"]["invalid"] == kinds["proposal"]["invalid"] == 1
    assert kinds["unmodelled"]["files"] == 1 and "sessions" not in json.dumps(first)
    # The original is never touched; reformatting is visible as a rewrite and changes no digest.
    offset.write_text(json.dumps(json.loads(offset.read_text(encoding="utf-8"))), encoding="utf-8")
    second = state_roundtrip.check(directory)
    assert second["kinds"]["telegram-offset"]["rewritten"] == 1 and second["digest"] == first["digest"]
    assert (directory / "telegram-dialog.json").read_text(encoding="utf-8") == "{broken"  # not quarantined
    (directory / "web-sessions.json").write_text('{"sessions": [1]}', encoding="utf-8")
    assert state_roundtrip.check(directory)["digest"] != first["digest"]


def test_roundtrip_command_needs_an_existing_directory(tmp_path, capsys):
    directory, _offset = _states(tmp_path)
    assert state_roundtrip.main([str(tmp_path / "missing")]) == 2
    assert "nicht gefunden" in capsys.readouterr().err
    report = tmp_path / "roundtrip.json"
    assert state_roundtrip.main([str(directory), "--output", str(report)]) == 0
    assert "digest" in json.loads(report.read_text(encoding="utf-8"))
    assert state_roundtrip.main([str(directory)]) == 0
    assert "kinds" in json.loads(capsys.readouterr().out)
    assert state_roundtrip.model_for("mail-run-x") == ("mail-run", state_roundtrip.MailRunState)


@pytest.mark.parametrize("module", ["devtools.code_metrics", "devtools.state_roundtrip"])
def test_tools_run_as_modules(module, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", [module, "--help"])
    monkeypatch.delitem(sys.modules, module, raising=False)
    with pytest.raises(SystemExit) as stopped:
        runpy.run_module(module, run_name="__main__")
    assert stopped.value.code == 0
