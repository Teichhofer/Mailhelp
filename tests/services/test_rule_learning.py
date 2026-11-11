import pytest
import yaml

from mailhelp.rule_learning.models import RuleAnalysis
from mailhelp.rule_learning.service import STATE, DecisionRuleLearning, redact_data
from mailhelp.rule_learning.validation import RuleConflict
from tests.fakes.rule_learning import RuleHarness, proposal, record, topic


@pytest.fixture
def rules(tmp_path):
    harness = RuleHarness(tmp_path)
    with harness.store:
        yield harness


def test_analysis_is_explicit_redacted_isolated_and_never_changes_rules(rules):
    before = rules.service.hashes()
    rules.log(record())
    job = rules.analyze()
    assert job.status == "queued" and rules.analyzer.calls == []
    assert rules.service.change("web:a", 0, "analyze-1", "analyze", {"confirm": True}).status == "queued"
    with pytest.raises(RuleConflict):
        rules.service.change("web:a", 0, "analyze-1", "analyze", {"confirm": False})
    assert rules.service.tick() and not rules.service.tick()
    state = rules.service.state("web:a")
    assert state.status == "review" and len(state.proposals) == 1
    assert "secret-token" not in str(rules.analyzer.calls)
    assert rules.service.state("web:b").proposals == []
    assert rules.service.hashes() == before and rules.activated == []
    with pytest.raises(PermissionError):
        rules.apply([], actor="web:b")


def test_hand_edits_replace_suggestions_and_valid_rules_activate_once(rules):
    state = rules.review()
    edited = topic(name="Von Hand", examples=["Eigener Beleg"], exclusions=["Eigener Ausschluss"])
    choices = [{"index": 0, "topic": edited.model_dump()}]
    result = rules.apply(choices)
    assert result.status == "done" and result.evidence == []
    assert yaml.safe_load((rules.directory / "topics.yaml").read_text(encoding="utf-8"))["topics"][0] == edited.model_dump()
    replay = rules.service.change("web:a", state.version, "apply-key", "apply", {"confirm": True, "choices": choices})
    assert replay.status == "done" and len(rules.activated) == 1
    assert rules.activated[0][0].name == "Von Hand"


@pytest.mark.parametrize("reason", ["session", "stale", "key", "confirm", "action", "empty", "busy", "invalid_file"])
def test_rejected_requests_do_not_write_or_call_a_model(rules, reason):
    rules.log(record())
    version, key, action, payload = 0, "start-key", "analyze", {"confirm": True}
    if reason == "session":
        rules.authorized.clear()
    elif reason == "stale":
        version = 99
    elif reason == "key":
        key = "bad"
    elif reason == "confirm":
        payload = {"confirm": False}
    elif reason == "action":
        action = "other"
        rules.service.save(rules.service.state().model_copy(update={"owner": __import__("hashlib").sha256(b"web:a").hexdigest()}))
    elif reason == "empty":
        rules.log()
    elif reason == "busy":
        rules.analyze()
        version = rules.service.state().version
    else:
        (rules.directory / "topics.yaml").write_text("topics: [", encoding="utf-8")
    before = rules.service.hashes()
    with pytest.raises((ValueError, PermissionError)):
        rules.service.change("web:a", version, key, action, payload)
    assert rules.service.hashes() == before and rules.analyzer.calls == []


@pytest.mark.parametrize("failure", ["provider", "prompt", "unknown_evidence", "budget", "logout", "changed"])
def test_a_failed_analysis_ends_safely_without_rule_writes(rules, failure):
    rules.log(record())
    rules.analyze()
    if failure == "provider":
        rules.analyzer.error = RuntimeError("secret-token must not appear")
    elif failure == "prompt":
        rules.analyzer.prompts.prompts.clear()
    elif failure == "unknown_evidence":
        rules.analyzer.result = RuleAnalysis(proposals=[proposal(evidence=["forged"])])
    elif failure == "budget":
        rules.limit = 1
    elif failure == "logout":
        rules.authorized.clear()
    else:
        (rules.directory / "topics.yaml").write_text("topics: []", encoding="utf-8")
    before = rules.service.hashes()
    assert rules.service.tick()
    state = rules.service.state()
    assert state.status == "failed" and "secret-token" not in state.message
    assert rules.service.hashes() == before and rules.activated == []


def test_a_large_context_drops_old_evidence_without_sending_secrets(rules):
    rules.log(*(record(identity="decision-" + str(n)) for n in range(1, 30)))
    rules.analyze()
    rules.limit = 2200
    rules.analyzer.result = RuleAnalysis()
    assert rules.service.tick() and rules.service.state().status == "review"
    assert 0 < len(rules.analyzer.calls[0]["decisions"]) < 29
    assert redact_data([{"a": "secret-token", "b": True, "c": None}], rules.service.redact)[0] == {
        "a": "[entfernt]", "b": True, "c": None}


def test_context_trimming_cannot_restore_secrets_from_untrusted_decision_fields(rules):
    rules.log(*(record(identity="decision-" + str(n), decision="secret-token",
                      analysis={"relevance": {"topic_ids": ["secret-token"]}}) for n in range(1, 30)))
    rules.analyze()
    rules.limit = 2200
    rules.analyzer.result = RuleAnalysis()
    assert rules.service.tick() and rules.service.state().status == "review"
    sent = rules.analyzer.calls[0]
    assert 0 < len(sent["decisions"]) < 29
    assert "secret-token" not in str(sent)


def test_invalid_selection_and_a_changed_file_leave_both_files_untouched(rules):
    rules.review()
    before = rules.service.hashes()
    with pytest.raises(ValueError):
        rules.apply([{"index": 0, "topic": topic(enabled=False).model_dump()}])
    assert rules.service.hashes() == before
    with (rules.directory / "irrelevant_topics.yaml").open("a", encoding="utf-8") as stream:
        stream.write("# external edit\n")
    changed = rules.service.hashes()
    with pytest.raises(RuleConflict):
        rules.apply()
    assert rules.service.hashes() == changed


def test_an_authorization_lost_during_validation_prevents_all_writes(rules, monkeypatch):
    from mailhelp.rule_learning.validation import RuleValidationService
    rules.review()
    before = rules.service.hashes()
    prepare = RuleValidationService.prepare

    def revoke(*args):
        value = prepare(*args)
        rules.authorized.clear()
        return value

    monkeypatch.setattr(RuleValidationService, "prepare", revoke)
    with pytest.raises(PermissionError):
        rules.apply()
    assert before == rules.service.hashes()


def test_a_concurrent_edit_during_validation_is_not_journaled_or_overwritten(rules, monkeypatch):
    from mailhelp.rule_learning.validation import RuleValidationService
    rules.review()
    prepare = RuleValidationService.prepare

    def changed(*args):
        result = prepare(*args)
        with (rules.directory / "topics.yaml").open("a", encoding="utf-8") as stream:
            stream.write("# concurrent\n")
        return result

    monkeypatch.setattr(RuleValidationService, "prepare", changed)
    with pytest.raises(RuleConflict, match="während"):
        rules.apply()
    assert rules.service.state().status == "review"
    assert (rules.directory / "topics.yaml").read_text(encoding="utf-8").endswith("# concurrent\n")


def test_a_partial_local_commit_is_reconciled_after_restart_without_a_new_model_call(rules, monkeypatch):
    from mailhelp.rule_learning import service
    rules.analyzer.result = RuleAnalysis(proposals=[proposal(), proposal(
        category="irrelevant", action="create", topic_id="noise", proposed=topic(id="noise", name="Werbung"))])
    state = rules.review()
    expected = state.proposals[0].proposed.model_dump()
    original = service.atomic_replace
    writes = []

    def interrupted(path, content):
        writes.append(path.name)
        if len(writes) == 2:
            raise OSError("synthetic disk failure")
        original(path, content)

    monkeypatch.setattr(service, "atomic_replace", interrupted)
    with pytest.raises(OSError):
        rules.apply([{"index": index, "topic": item.proposed.model_dump()}
                     for index, item in enumerate(state.proposals)])
    assert rules.service.state().status == "committing"
    restarted = DecisionRuleLearning(rules.configuration, lambda: rules.analyzer, rules.active, clock=lambda: rules.now)
    restarted.recover()
    monkeypatch.setattr(service, "atomic_replace", original)
    pending = restarted.state("web:b")
    assert pending.status == "committing" and pending.evidence == []
    result = restarted.change("web:b", pending.version, "resume-key", "resume", {"confirm": True})
    assert result.status == "done" and len(rules.analyzer.calls) == 1
    assert yaml.safe_load((rules.directory / "topics.yaml").read_text(encoding="utf-8"))["topics"][0] == expected
    with pytest.raises(PermissionError):
        restarted.change("web:a", 0, "analyze-1", "analyze", {"confirm": True})


def test_recovery_will_not_overwrite_newer_files_or_changed_mailbox_config(rules, monkeypatch):
    from mailhelp.rule_learning import service
    rules.review()
    original = service.atomic_replace
    monkeypatch.setattr(service, "atomic_replace", lambda *_: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        rules.apply()
    monkeypatch.setattr(service, "atomic_replace", original)
    state = rules.service.state()
    with (rules.directory / "config.yaml").open("a", encoding="utf-8") as stream:
        stream.write("# changed\n")
    before = rules.service.hashes()
    with pytest.raises(RuleConflict, match="Postfach"):
        rules.service.finish("web:a", state)
    state.hashes["config.yaml"] = before["config.yaml"]
    (rules.directory / "topics.yaml").write_text("external revision", encoding="utf-8")
    changed = rules.service.hashes()
    with pytest.raises(RuleConflict, match="extern"):
        rules.service.finish("web:a", state)
    assert changed == rules.service.hashes()
    state.commit = {"../outside.yaml": "invalid"}
    with pytest.raises(RuleConflict, match="ungültiger"):
        rules.service.finish("web:a", state)


def test_the_same_authorized_request_finishes_an_interrupted_local_write_once(rules, monkeypatch):
    from mailhelp.rule_learning import service
    state = rules.review()
    payload = {"confirm": True, "choices": [{"index": 0, "topic": state.proposals[0].proposed.model_dump()}]}
    original = service.atomic_replace
    monkeypatch.setattr(service, "atomic_replace", lambda *_: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        rules.service.change("web:a", state.version, "same-apply", "apply", payload)
    monkeypatch.setattr(service, "atomic_replace", original)
    assert rules.service.change("web:a", state.version, "same-apply", "apply", payload).status == "done"
    assert len(rules.activated) == 1


@pytest.mark.parametrize("status", ["queued", "running"])
def test_restarts_interrupt_analysis_and_never_replay_it_automatically(rules, status):
    rules.log(record())
    rules.analyze()
    state = rules.service.state().model_copy(update={"status": status})
    rules.service.save(state)
    rules.service.recover()
    assert rules.service.state().status == "interrupted" and not rules.service.tick()
    rules.service.recover()
    assert rules.analyzer.calls == []


def test_a_corrupt_or_expired_state_is_not_exposed_and_late_answers_are_discarded(rules):
    rules.store.save(STATE, {"invalid": "state"})
    assert rules.service.state().status == "empty"
    rules.log(record())
    rules.analyze()
    rules.analyzer.before = lambda: setattr(rules, "now", rules.now + 86401)
    assert rules.service.tick()
    assert rules.service.state().status == "empty" and rules.analyzer.calls == []


def test_expiration_keeps_a_durable_revision_and_rejects_old_analysis_confirmations(rules):
    completed = rules.review()
    rules.now += 86401
    expired = rules.service.state("web:a")
    assert expired.status == "empty" and expired.version > completed.version
    restarted = DecisionRuleLearning(rules.configuration, lambda: rules.analyzer, rules.active,
                                    clock=lambda: rules.now)
    assert restarted.state("web:a").version == expired.version
    assert restarted.state().evidence == []
    with pytest.raises(RuleConflict):
        restarted.change("web:a", 0, "analyze-1", "analyze", {"confirm": True})
    assert len(rules.analyzer.calls) == 1


def test_before_call_refuses_replaced_jobs_and_during_call_replacement_is_not_overwritten(rules):
    rules.log(record())
    rules.analyze()
    with pytest.raises(RuleConflict):
        rules.service.before_call("web:a")
    def replace():
        state = rules.service.state()
        rules.service.save(state.model_copy(update={"status": "interrupted"}))
    rules.analyzer.before = replace
    assert rules.service.tick() and rules.service.state().status == "interrupted"


def test_a_late_answer_cannot_replace_a_newer_running_job_of_the_same_session(rules):
    rules.log(record())
    rules.analyze()

    def replace_with_newer_job():
        current = rules.service.state()
        rules.service.save(current.model_copy(update={"version": current.version + 10, "message": "Neuer Auftrag"}))

    rules.analyzer.before = replace_with_newer_job
    assert rules.service.tick()
    current = rules.service.state()
    assert current.status == "running" and current.message == "Neuer Auftrag"
    assert current.version == 12 and rules.activated == []
