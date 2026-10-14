from types import SimpleNamespace as NS

import pytest
import yaml
from shared_application import settings
from shared_core import prompt_config

from mailhelp.configuration import ConfigurationService
from mailhelp.orchestrator import Orchestrator
from mailhelp.setup_runtime import SetupRuntime


@pytest.fixture
def configured(web, tmp_path):
    cfg = settings(tmp_path)
    cfg.web.enabled = True
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
    app = NS(settings=cfg, store=web.store, dialog=web.dialog, logger=web.logger, telegram=web.telegram,
             calendar=NS(check_access=lambda: None), todoist=NS(check_access=lambda: None),
             analyzer=NS(prompts=prompt_config()), openrouter=NS(complete=lambda *args, **kw: None))
    app.telegram.check_access = lambda: None
    app.orchestrator = Orchestrator(app.analyzer, web.store, object(), 2, [], 1024)
    app.orchestrator.configure_mailboxes(cfg, app.analyzer.prompts, {"0" * 24: 1})
    app.configuration = ConfigurationService(tmp_path, web.store, cfg,
        lambda actor: web.auth.active(actor.removeprefix("web:")), lambda value: setattr(app, "settings", value))
    web.site.archive.configuration = web.dialog.review.configuration = app.configuration
    runtime = SetupRuntime(app, web.site, None, target_probe=lambda service, cfg: None)
    web.site.setup_page.runtime = runtime
    return NS(web=web, app=app, runtime=runtime, cfg=cfg, tmp_path=tmp_path)

