"""Planung Lernmodus: a realistic budget starts and finishes a learning run (regression).

On 8 November 2026 every start in the web interface was refused with 409: the estimate
assumed 17 to 69 million tokens per mail (twice the payload limit for every call and
attempt), so a budget of a few dollars never sufficed, and every call reserved the
payload limit on top of its actual size.
"""
from tests.fakes.learning_harness import learning  # noqa: F401  (fixture)


def production_limits(h):
    """The values of the reporting installation: 500,000 bytes payload, 16,000 output tokens."""
    limits = h.app.settings.limits.model_copy(update={"max_llm_payload_bytes": 500_000})
    h.app.settings = h.app.settings.model_copy(update={"limits": limits})
    for stage in ("relevance", "learning_classification", "learning_abstraction"):
        step = h.app.analyzer.prompts.prompts[stage]
        step.parameters = {**step.parameters, "max_tokens": 16_000}
    h.client.policy.retries = 1


def test_regression_a_realistic_budget_starts_and_finishes_a_run(learning):
    h = learning
    production_limits(h)
    selection = dict(mailbox=1, folders=["INBOX"], count=20, budget_usd=1.0, usd_per_million_tokens=0.5)
    state = h.change("start", selection)
    assert state.status == "running"
    while h.worker.tick():
        pass
    finished = h.jobs.state()
    assert finished.status == "review" and finished.cursor == 2, finished.message
    assert finished.reserved_tokens * 0.5 / 1_000_000 <= 1.0


def test_the_reservation_counts_the_request_once_and_settles_with_the_reported_usage(learning):
    h = learning
    production_limits(h)
    reported = []

    def complete(model, parameters, system, payload, **kwargs):
        reported.append(kwargs)
        kwargs["usage"]({"prompt_tokens": 3_000, "completion_tokens": 500, "total_tokens": 3_500})
        return "call", {"categories": [{"name": "Thema", "description": "Synthetisch"}]} if kwargs[
            "stage"] != "relevance" else {"decision": "irrelevant", "topic_ids": [], "reason": "x"}

    h.client.complete = complete
    h.change("start", dict(mailbox=1, folders=["INBOX"], count=1, budget_usd=0.05, usd_per_million_tokens=0.5))
    while h.worker.tick():
        pass
    state = h.jobs.state()
    # Each call reserved its own size plus max_tokens (not the 500,000 byte limit again) and
    # then kept only the reported 3,500 tokens.
    assert state.status == "review" and state.reserved_tokens == 3_500 * len(reported)


def test_without_a_usable_report_the_reservation_stays(learning):
    h = learning
    production_limits(h)
    original = h.client.complete
    usages = iter([{"total_tokens": "viel"}, {"prompt_tokens": 1}, {"prompt_tokens": 10, "completion_tokens": 5}])

    def complete(model, parameters, system, payload, **kwargs):
        report = next(usages, None)
        if report is not None:
            kwargs["usage"](report)
        return original(model, parameters, system, payload, **{k: v for k, v in kwargs.items() if k != "usage"})

    h.client.complete = complete
    h.change("start", dict(mailbox=1, folders=["INBOX"], count=1, budget_usd=1.0, usd_per_million_tokens=0.5))
    before = h.jobs.state().reserved_tokens
    h.worker.tick()  # discovery
    h.worker.tick()  # first mail: three reports, one of them usable (15 tokens)
    state = h.jobs.state()
    assert state.reserved_tokens > before and state.cursor == 1


def test_a_settlement_of_an_older_run_is_ignored(learning):
    from mailhelp.runtime.learning_worker import LearningCompleter
    h = learning
    h.change("start", dict(mailbox=1, folders=["INBOX"], count=1, budget_usd=1.0, usd_per_million_tokens=0.5))
    completer = LearningCompleter(h.worker, h.client, generation=h.jobs.state().generation - 1)
    reserved = h.jobs.state().reserved_tokens
    completer._settle(1_000, {"total_tokens": 10})
    assert h.jobs.state().reserved_tokens == reserved


def test_the_estimate_is_typical_and_the_maximum_is_shown_separately(learning):
    from mailhelp.runtime.learning_jobs import LearningSelection
    h = learning
    production_limits(h)
    selection = LearningSelection(mailbox=1, folders=["INBOX"], count=20, budget_usd=1.0, usd_per_million_tokens=0.5)
    assert h.worker.estimate(selection) == 20 * 4 * 5_000
    assert h.worker.maximum(selection) > 100 * h.worker.estimate(selection)


def test_a_start_the_budget_cannot_cover_is_explained_and_not_offered(learning):
    from urllib.parse import urlencode
    h = learning
    page = h.browser.request("GET", "/lernen?" + urlencode(dict(mailbox=1, count=20, folders="INBOX", price=0.5,
                                                                 budget=0.01))).body.decode()
    assert "Bitte mindestens 0.200000 USD angeben" in page and "kostenpflichtig starten" not in page


def test_the_reason_of_a_refused_action_is_shown_and_logged(learning):
    h = learning
    events = []
    h.site.logger.event = lambda level, module, name, **context: events.append((name, context))
    form = {"csrf": h.auth.csrf_token(h.auth.sessions()[0].id), "version": "0", "key": "a" * 32, "action": "start",
            "selection": '{"mailbox": 1, "folders": ["INBOX"], "count": 20, "budget_usd": 0.01, '
                         '"usd_per_million_tokens": 0.5}'}
    answer = h.browser.request("POST", "/lernen", form)
    assert answer.status == 409 and "Budget reicht für den geschätzten Lauf nicht aus." in answer.body.decode()
    assert events[-1] == ("action_rejected", {"error_class": "LearningConflict",
                                              "reason": "Budget reicht für den geschätzten Lauf nicht aus."})
    broken = h.browser.request("POST", "/lernen", {**form, "key": "b" * 32, "version": "x"})
    assert broken.status == 409 and "Auswahl ungültig oder inzwischen geändert." in broken.body.decode()


def test_a_paused_run_with_a_changed_configuration_is_replaced_by_a_new_one(learning):
    h = learning
    h.change("start", h.selection)
    h.change("pause")
    (h.directory / "topics.yaml").write_text((h.directory / "topics.yaml").read_text(encoding="utf-8") + "\n",
                                             encoding="utf-8")
    page = h.browser.request("GET", "/lernen").body.decode()
    assert "kann nicht fortgesetzt werden" in page and "Fortsetzen" not in page and "Neuer Lernlauf" in page
    old = h.jobs.state().generation
    state = h.change("start", h.selection)
    assert state.status == "running" and state.generation == old + 1


def test_a_paused_run_without_changes_still_blocks_a_second_start(learning):
    import pytest

    from mailhelp.runtime.learning_jobs import LearningConflict
    h = learning
    h.change("start", h.selection)
    h.change("pause")
    assert "Fortsetzen" in h.browser.request("GET", "/lernen").body.decode()
    with pytest.raises(LearningConflict, match="offenen Lernlauf"):
        h.change("start", h.selection)


def test_a_second_run_starts_after_the_first_was_adopted(learning):
    h = learning
    h.review()
    h.change("apply", {})
    assert h.jobs.state().status == "done"
    state = h.change("start", h.selection)
    assert state.status == "running"
    while h.worker.tick():
        pass
    assert h.jobs.state().status == "review"
