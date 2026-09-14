"""Kommandozeileneinstieg und kontrollierter Signal-Shutdown."""
from __future__ import annotations
import argparse, signal
from pathlib import Path
from .config import load_all


def main() -> int:
    parser = argparse.ArgumentParser(description="Mailhelp E-Mail-Assistent")
    parser.add_argument("--config-directory", type=Path, default=Path("."))
    parser.add_argument("--check", action="store_true", help="Konfiguration validieren und beenden")
    args = parser.parse_args(); load_all(args.config_directory)
    if args.check: print("Konfiguration ist gültig."); return 0
    print("Konfiguration ist gültig; für den Dienstbetrieb Adapter in der Deployment-Konfiguration starten.")
    signal.signal(signal.SIGTERM, lambda *_: None)
    return 0

