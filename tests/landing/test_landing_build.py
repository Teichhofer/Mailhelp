"""7.9.7: the landing page sources in landing/ reproduce the delivered site byte for byte."""
import runpy
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "landing"
BUILD = ROOT / "build_site.py"


def files(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*")) if path.is_file() and "__pycache__" not in path.parts}


def build(copy: Path, monkeypatch) -> None:
    monkeypatch.setenv("INBOXSTRIDE_SITE_ROOT", str(copy))
    runpy.run_path(str(BUILD), run_name="build_site")


def test_a_fresh_build_regenerates_every_delivered_page_identically(tmp_path, monkeypatch, capsys):
    copy = tmp_path / "landing"
    shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__"))
    generated = [path for path in (copy / "public").rglob("*") if path.suffix in {".html", ".xml", ".txt"}
                 and path.name != "DM-Sans-OFL.txt"]
    for path in generated:
        path.unlink()  # pages, sitemap and robots.txt come from the sources only
    build(copy, monkeypatch)
    assert files(copy) == files(ROOT)
    assert capsys.readouterr().out.splitlines() == [
        "Static pages generated", "Fingerprinted local assets and formatted static pages"]


def test_the_build_writes_only_into_its_root(tmp_path, monkeypatch, capsys):
    before = files(ROOT)
    copy = tmp_path / "landing"
    shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__"))
    (copy / "content" / "terms-de.html").write_text("<h1>Geänderte Bedingungen</h1>", encoding="utf-8")
    build(copy, monkeypatch)
    capsys.readouterr()
    assert "Geänderte Bedingungen" in (copy / "public" / "nutzungsbedingungen" / "index.html").read_text("utf-8")
    assert files(ROOT) == before
