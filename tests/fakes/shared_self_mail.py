"""Synthetic mailboxes with own addresses (4.5); no test-module dependencies."""
from mailhelp.config import Settings
from mailhelp.processing.orchestrator import Orchestrator
from tests.fakes.shared_core import prompt_config
from tests.fakes.shared_profiles import ACCOUNT_ONE, ACCOUNT_TWO, TOPICS, settings
from tests.fakes.shared_services import AnalyzerStub, Notify


def own_settings(tmp_path, personal_info="Synthetische Person, privat erreichbar unter Notiz@Privat.Example.Test"):
    cfg = settings(tmp_path, personal_info=personal_info).model_dump(mode="json")
    cfg["imap"]["mailboxes"][0]["own_addresses"] = ["alias@private.example.test"]
    cfg["imap"]["mailboxes"][1]["personal_info"] = "Im Büro: buero@work.example.test"
    return Settings.model_validate(cfg)


def orchestrator(store, cfg):
    run = Orchestrator(AnalyzerStub("relevant"), store, Notify(), 1, TOPICS, cfg.limits, targets=cfg.targets)
    run.configure_mailboxes(cfg, prompt_config(), {ACCOUNT_ONE: 1, ACCOUNT_TWO: 2})
    run.mailbox_usernames = {1: "ich@private.example.test", 2: "kennung-ohne-adresse"}
    return run
