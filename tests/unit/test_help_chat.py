"""5.3 H9: the session-bound help chat with simulated model answers only."""
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from mailhelp.config import HelpChatSettings, ImapCredentials, Secrets
from mailhelp.helpdocs import HelpAnswer, HelpUnavailable, load
from mailhelp.helpdocs.chat import MAX_QUEUED, ChatRefused, HelpChat, chat_name, classify, redactor, secret_values
from mailhelp.llm.adapter import PermanentError, RetryableError
from mailhelp.llm.openrouter import RateLimitExceeded
from mailhelp.processing.analysis import LlmInvalidJson
from mailhelp.storage import JsonStore

NOW = datetime(2026, 11, 10, 12, tzinfo=UTC)
QUESTION = "Was bewirkt das Abrufintervall?"


class Analyzer:
    """Answers like the settings_help step; records what it was given."""

    def __init__(self, error=None, during=None):
        self.prompts = SimpleNamespace(prompts={"settings_help": object()})
        self.calls, self.error, self.during = [], error, during

    def settings_help(self, question, sources, history, settings):
        self.calls.append((question, [item.id for item in sources], history, settings))
        if self.during is not None:
            self.during()
        if self.error is not None:
            raise self.error
        return "call-1", HelpAnswer(answer=f"Antwort mit geheim-12345 zu: {question}", source_ids=[sources[0].id])


class Clock:
    def __init__(self):
        self.value = NOW

    def __call__(self):
        return self.value


@pytest.fixture
def chat(tmp_path):
    with JsonStore(tmp_path) as store:
        clock, analyzer, active = Clock(), Analyzer(), {"s1", "s2"}
        settings = HelpChatSettings()
        service = HelpChat(store, lambda: settings, load, lambda: analyzer, lambda sid: sid in active,
                           redactor(["geheim-12345"]), clock, sessions=lambda: sorted(active))
        yield SimpleNamespace(store=store, clock=clock, analyzer=analyzer, active=active, service=service,
                              settings=settings)


def ask(context, question=QUESTION, key="k1", session="s1", version=1, setting=None):
    return context.service.submit(session, question, key, version, setting)


def test_a_question_is_answered_with_sources_and_secrets_removed(chat):
    job = ask(chat, "Mein Token geheim-12345 – " + QUESTION)
    assert job.status == "queued" and "geheim-12345" not in job.question
    assert chat.service.run_once() is True and chat.service.run_once() is False
    state = chat.service.state("s1")
    turn = state.turns[0]
    assert chat.service.job("s1", job.id).status == "completed" and turn.source_ids
    assert "geheim-12345" not in turn.answer and "[entfernt]" in turn.answer
    question, sources, history, offered = chat.analyzer.calls[0]
    assert "web-einstellungen/mailabruf-und-betrieb" in sources and history == []
    assert {"id": "setting:poll_interval_seconds", "label": "Abrufintervall (Sekunden)"} in offered
    assert chat.service.job("s2", job.id) is None  # another session never sees it
    assert chat.store.load(chat_name("s1")) is not None and "s1" not in str(chat.store.names("help-chat-"))


def test_the_same_key_replays_and_a_changed_question_conflicts(chat):
    job = ask(chat)
    assert ask(chat).id == job.id
    with pytest.raises(ChatRefused) as refused:
        ask(chat, "Etwas anderes?")
    assert refused.value.code == "conflict"


@pytest.mark.parametrize(("change", "code"), [
    ({"enabled": False}, "disabled"), ({"question": "   "}, "empty"), ({"question": "x" * 4001}, "too_long"),
    ({"version": 2}, "stale"),
])
def test_refused_questions(chat, change, code):
    if "enabled" in change:
        chat.settings.enabled = False
    with pytest.raises(ChatRefused) as refused:
        ask(chat, change.get("question", QUESTION), version=change.get("version", 1))
    assert refused.value.code == code and chat.analyzer.calls == []


def test_one_question_at_a_time_a_session_rate_and_a_bounded_queue(chat):
    ask(chat)
    with pytest.raises(ChatRefused, match="noch eine Frage"):
        ask(chat, key="k2")
    chat.service.run_once()
    chat.settings.requests_per_minute_per_session = 1
    with pytest.raises(ChatRefused) as refused:
        ask(chat, key="k3")
    assert refused.value.code == "rate_limited"
    chat.settings.requests_per_minute_per_session = 20
    for number in range(MAX_QUEUED):
        chat.active.add(f"t{number}")
        ask(chat, key=f"q{number}", session=f"t{number}")
    with pytest.raises(ChatRefused) as refused:
        ask(chat, key="voll", session="s2")
    assert refused.value.code == "full"


def test_a_follow_up_uses_the_history_and_no_source_answers_locally(chat):
    ask(chat)
    chat.service.run_once()
    ask(chat, "Und pro Postfach?", key="k2")
    chat.service.run_once()
    assert chat.analyzer.calls[1][2][0]["question"] == QUESTION
    ask(chat, "Bananenbrot?", key="k3")
    chat.service.run_once()
    turn = chat.service.state("s1").turns[-1]
    assert turn.local and turn.needs_clarification and len(chat.analyzer.calls) == 2


@pytest.mark.parametrize(("setup", "code"), [
    ("ended", "session_ended"), ("unavailable", "help_unavailable"), ("no_analyzer", "not_configured"),
    ("no_step", "not_configured"),
])
def test_a_question_that_cannot_be_sent_ends_safely(chat, setup, code):
    if setup == "ended":
        chat.active.discard("s1")
    elif setup == "unavailable":
        def broken():
            raise HelpUnavailable("kaputt")
        chat.service.base = broken
    elif setup == "no_analyzer":
        chat.service.analyzer = lambda: None
    else:
        chat.analyzer.prompts.prompts = {}
    job = ask(chat)
    chat.service.run_once()
    assert (chat.service.job("s1", job.id).status, chat.service.job("s1", job.id).error) == ("failed", code)
    assert chat.analyzer.calls == []


@pytest.mark.parametrize(("error", "code"), [
    (RateLimitExceeded(0), "budget"), (PermanentError("401"), "provider_refused"),
    (RetryableError("503"), "provider_unavailable"), (TimeoutError(), "provider_unavailable"),
    (LlmInvalidJson("settings_help"), "invalid_answer"), (RuntimeError("?"), "failed"),
])
def test_model_errors_end_in_fixed_messages(chat, error, code):
    chat.analyzer.error = error
    job = ask(chat)
    chat.service.run_once()
    assert chat.service.job("s1", job.id).error == code and chat.service.state("s1").turns == []
    assert classify(error) == code


def test_clearing_forgets_the_chat_and_drops_a_late_answer(chat):
    first = ask(chat)
    chat.service.run_once()
    chat.analyzer.during = lambda: chat.service.clear("s1", 1)
    ask(chat, "Und pro Postfach?", key="k2")
    chat.service.run_once()  # cleared while the model was answering
    state = chat.service.state("s1")
    assert state.version == 2 and state.turns == [] and chat.service.job("s1", first.id).status == "completed"
    with pytest.raises(ChatRefused, match="bereits geleert"):
        chat.service.clear("s1", 1)
    chat.analyzer.during = None
    queued = ask(chat, key="k4", version=2)
    assert chat.service.clear("s1", 2) == 3 and chat.service.job("s1", queued.id).status == "cancelled"


def test_a_restart_interrupts_open_questions_and_cleans_up(chat):
    chat.active.add("s3")
    done = ask(chat, session="s3", key="fertig")
    chat.service.run_once()  # an answered chat stays as it is
    job = ask(chat)
    ask(chat, session="s2", key="other")
    chat.store.save(chat_name("weg"), {"schema_version": 1, "version": 1, "turns": [], "jobs": [],
                                         "updated_at": NOW.isoformat()})
    chat.store.save(chat_name("kaputt"), {"schema_version": 1, "kaputt": True})
    chat.clock.value = NOW + timedelta(hours=1)
    assert chat.service.recover() == 2
    assert chat.service.job("s1", job.id).status == "interrupted" and len(chat.analyzer.calls) == 1
    assert chat.service.job("s3", done.id).status == "completed"
    assert chat.store.load(chat_name("weg")) is None and chat.store.load(chat_name("kaputt")) is None
    assert chat.service.state("kaputt").turns == []
    chat.clock.value = NOW + timedelta(hours=26)
    assert chat.service.cleanup() == 3 and chat.store.names("help-chat-") == []
    chat.store.save(chat_name("s1"), {"schema_version": 1, "kaputt": True})
    assert chat.service.state("s1").version == 1  # a damaged chat starts afresh


def test_the_worker_pool_answers_in_the_background(chat):
    job = ask(chat)
    chat.service.start()
    try:
        for _attempt in range(200):
            if chat.service.job("s1", job.id).status == "completed":
                break
            time.sleep(0.01)
    finally:
        chat.service.stop()
    assert chat.service.job("s1", job.id).status == "completed"


def test_known_secrets_are_collected_from_every_mailbox():
    secrets = Secrets(imap={1: ImapCredentials(username="a@example.test", password=SecretStr("imap-geheim"))},
                      openrouter_api_key=SecretStr("router-geheim"), todoist_token=SecretStr("kurz"))
    values = secret_values(secrets)
    assert {"imap-geheim", "router-geheim", "kurz"} <= set(values)
    redact = redactor(values)
    assert redact("imap-geheim und router-geheim und kurz") == "[entfernt] und [entfernt] und kurz"
