"""4.8, step 19.4: the runtime wires automatic drafts per mailbox (off by default)."""
from __future__ import annotations

from types import SimpleNamespace as NS

from pydantic import SecretStr

from mailhelp.config import ImapCredentials, PromptStep, Secrets, Settings
from mailhelp.mailbox.imap import account_id
from mailhelp.processing.analysis import Analyzer
from mailhelp.runtime.experience import ExperienceRuntime
from tests.fakes.activity_fakes import Model, activity_prompts
from tests.fakes.shared_application import Log, settings


def runtime(web, tmp_path, *, auto, mailbox_auto=None):
    configuration = activity_prompts()
    configuration.prompts = {"draft_reply": PromptStep(system_prompt="Entwurf")}
    data = settings(tmp_path).model_dump(mode="json")
    data.update(smart_reply=True, auto_draft=auto)
    data["imap"] = {"mailboxes": [
        {"id": 1, "label": "Privat", "host": "a.test", "port": 993, "folders": ["INBOX"]},
        {"id": 2, "label": "Arbeit", "host": "b.test", "port": 993, "folders": ["INBOX"],
         **({} if mailbox_auto is None else {"auto_draft": mailbox_auto})},
        {"id": 3, "label": "Ohne", "host": "c.test", "port": 993, "folders": ["INBOX"], "smart_reply": False,
         "auto_draft": True}]}
    orchestrator = NS(drafts=None)
    app = NS(settings=Settings.model_validate(data), store=web.store, logger=Log(), calendar=None, todoist=None,
             telegram=NS(send=lambda *a: None), analyzer=Analyzer(Model(), configuration), orchestrator=orchestrator)
    secrets = Secrets.model_construct(imap={n: ImapCredentials(username=f"u{n}@test", password=SecretStr("p"))
                                            for n in (1, 2, 3)})
    built = ExperienceRuntime(app, NS(site=web.site, auth=web.auth), secrets)
    return built, orchestrator, web.site.experience.drafts


def accounts():
    return [account_id(host, 993, f"u{n}@test") for n, host in ((1, "a.test"), (2, "b.test"), (3, "c.test"))]


def test_automatic_drafts_are_off_by_default_and_the_orchestrator_gets_the_service(web, tmp_path):
    built, orchestrator, drafts = runtime(web, tmp_path, auto=False)
    assert orchestrator.drafts is drafts
    assert [drafts.auto_policy(account) for account in accounts()] == [False, False, False]
    assert drafts.auto_policy("f" * 24) is False  # mail of no configured mailbox


def test_a_mailbox_can_switch_them_on_but_never_without_smart_reply(web, tmp_path):
    _, _, drafts = runtime(web, tmp_path, auto=False, mailbox_auto=True)
    assert [drafts.auto_policy(account) for account in accounts()] == [False, True, False]
    _, _, drafts = runtime(web, tmp_path, auto=True, mailbox_auto=False)
    assert [drafts.auto_policy(account) for account in accounts()] == [True, False, False]
