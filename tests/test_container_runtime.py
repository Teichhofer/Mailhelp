"""Run the installed CLI with real state/log files and exclusively fake services.

CI invokes this in two fresh containers sharing the production data mounts.
The ordinary suite runs both starts against an isolated temporary directory.
"""
import json
import os
from pathlib import Path
import shutil
import sys

from mailhelp.cli import main


class OfflineResource:
    def __init__(self, *_args, **_kwargs):
        pass

    def close(self):
        pass


class OfflineImap(OfflineResource):
    account_id = "0" * 24
    last_uidvalidity = 7
    discoveries = []

    def discover_since(self, folder, start, validity, ranges):
        self.discoveries.append((folder, validity))
        return []


class OfflineTelegram(OfflineResource):
    messages = []

    def send(self, chat_id, text, reply_markup=None):
        self.messages.append(text)


def test_installed_cli_persists_state_and_logs_across_restart(tmp_path, monkeypatch):
    supplied = os.environ.get("MAILHELP_SMOKE_CONFIG")
    config = Path(supplied) if supplied else tmp_path / "config"
    if not supplied:
        config.mkdir()
        for name in ("prompts.yaml", "topics.yaml", "irrelevant_topics.yaml"):
            shutil.copyfile(Path(__file__).parents[1] / name, config / name)
        shutil.copyfile(Path(__file__).parents[1] / "config.example.yaml", config / "config.yaml")
    for name in ("IMAP_USERNAME", "IMAP_PASSWORD", "OPENROUTER_API_KEY", "TELEGRAM_BOT_TOKEN",
                 "TODOIST_TOKEN", "TODOIST_CLIENT_ID", "TODOIST_CLIENT_SECRET",
                 "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN"):
        monkeypatch.setenv(name, "synthetic-smoke-value")
    for name in ("OpenRouterClient", "HttpWriter", "GoogleOAuthTokenProvider"):
        monkeypatch.setattr(f"mailhelp.application.{name}", OfflineResource)
    monkeypatch.setattr("mailhelp.application.ImapReader", OfflineImap)
    monkeypatch.setattr("mailhelp.application.TelegramClient", OfflineTelegram)
    # Even an unexpected adapter path must fail instead of reaching a real service.
    def forbid_network(*_args, **_kwargs):
        raise AssertionError("External network access in simulated smoke test")
    monkeypatch.setattr("socket.socket.connect", forbid_network)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["mailhelp", "--config-directory", str(config),
                                    "--max-mails", "1", "--ignore-historical-start"])
    stages = [int(os.environ["MAILHELP_SMOKE_STAGE"])] if supplied else [1, 2]
    for stage in stages:
        checkpoints = list((config / "data/production").glob("imap-*.json"))
        assert bool(checkpoints) is (stage == 2)
        OfflineImap.discoveries = []
        OfflineTelegram.messages = []
        assert main() == 0
        assert OfflineImap.discoveries
        assert all(validity == (7 if stage == 2 else None)
                   for _, validity in OfflineImap.discoveries)
        assert any("vollständig abgearbeitet" in text for text in OfflineTelegram.messages)
        checkpoints = list((config / "data/production").glob("imap-*.json"))
        assert checkpoints
        assert all(json.loads(path.read_text(encoding="utf-8"))["uidvalidity"] == 7
                   for path in checkpoints)
        logs = list((config / "logs").glob("*.jsonl"))
        records = [json.loads(line) for path in logs for line in path.read_text(encoding="utf-8").splitlines()]
        assert records
        assert not any(record.get("level") == "ERROR" for record in records)
        assert not (tmp_path / "data").exists()
        assert not (tmp_path / "logs").exists()
