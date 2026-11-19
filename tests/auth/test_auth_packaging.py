"""8.0: the central service runs from its own image with nothing but its package and pinned packages."""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
PACKAGE = ROOT / "src" / "inboxstride_auth"
ALLOWED = {"cryptography", "httpx", "pydantic", "inboxstride_auth"}


def imported_roots(path: Path) -> set[str]:
    roots = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            roots.add(str(node.module).split(".")[0])
    return roots


def test_the_service_imports_only_the_standard_library_and_its_image_packages():
    foreign = {name for path in PACKAGE.glob("*.py") for name in imported_roots(path)
               if name not in sys.stdlib_module_names and name not in ALLOWED}
    assert foreign == set()  # in particular no mailhelp module: the image does not contain it


def test_the_image_copies_only_the_service_and_runs_it_without_root():
    lines = (ROOT / "ops" / "auth" / "Dockerfile").read_text(encoding="utf-8").splitlines()
    copies = [line.split()[1] for line in lines if line.startswith("COPY ")]
    assert copies == ["ops/auth/requirements.lock", "src/inboxstride_auth"]
    assert "USER 65532:65532" in lines and any("/health" in line for line in lines)
    assert 'ENTRYPOINT ["python", "-m", "inboxstride_auth"]' in lines
