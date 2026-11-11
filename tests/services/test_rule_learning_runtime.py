import json

from mailhelp.config import load_all
from mailhelp.review.learning_log import learning_path
from mailhelp.rule_learning.service import DecisionRuleLearning
from mailhelp.runtime import composition
from tests.fakes.learning_harness import learning
from tests.fakes.rule_learning import record


def test_the_existing_learning_worker_runs_rule_jobs_and_recovers_on_start(learning, monkeypatch):
    harness = learning
    path = learning_path(harness.store.directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record()) + "\n", encoding="utf-8")
    actor = harness.initial.actor
    service = DecisionRuleLearning(harness.configuration, lambda: harness.app.analyzer, lambda _: True)
    harness.worker.rules = service
    service.change(actor, 0, "runtime-start", "analyze", {"confirm": True})
    assert harness.worker.tick() is True  # the synthetic normal-learning model lacks this optional step
    assert service.state().status == "failed"
    monkeypatch.setattr(service, "recover", lambda: None)
    monkeypatch.setattr(harness.worker, "run", lambda: None)
    harness.worker.start()
    harness.worker.stop()


def test_real_composition_binds_current_analyzer_limits_session_and_shutdown(learning, monkeypatch):
    from mailhelp.external import providers

    harness = learning

    class Resource:
        service = "synthetic"
        account_id = "0" * 24

        def __init__(self, *args, **kwargs):
            pass

        def close(self):
            pass

    monkeypatch.setattr(composition, "ImapReader", Resource)
    monkeypatch.setattr(composition, "OpenRouterClient", Resource)
    monkeypatch.setattr(providers, "HttpWriter", Resource)
    monkeypatch.setattr(providers, "GoogleOAuthTokenProvider", Resource)
    cfg, sec, topics, _, prompts, fingerprint = load_all(harness.directory, harness.initial.setup.environment())
    with composition.build_application(cfg, sec, topics, prompts, fingerprint, harness.directory,
                                       shared_store=harness.store, use_jev_relevance=False) as app:
        rules = app.services.learning.rules
        assert rules is app.web_site.rule_learning.service
        assert rules.analyzer() is app.analyzer
        current = app.analyzer
        app.analyzer = object()
        assert rules.analyzer() is app.analyzer
        app.analyzer = current
        assert rules.payload_limit() == cfg.limits.max_llm_payload_bytes
        app.settings.limits.max_llm_payload_bytes = 12345
        assert rules.payload_limit() == 12345
        assert rules.active(harness.actor)
        assert not rules.active("web:invalid")
        app.stop_event.set()
        assert not rules.active(harness.actor)
