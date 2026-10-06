"""One path policy for runtime state, logging and explicit cleanup."""
from pathlib import Path


def runtime_path(path: Path, base_directory: Path) -> Path:
    """Resolve relative runtime paths against the configuration directory."""
    return (base_directory / path).resolve()
