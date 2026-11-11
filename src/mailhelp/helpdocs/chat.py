"""5.3 (H9): the session-bound help chat: jobs, versions, idempotency, limits and clean-up.

A question becomes a job only through an explicit, authorized submit. A small shared worker
pool runs jobs outside every state lock; the session is checked again right before the paid
model call. After a restart, running jobs are shown as interrupted and are never sent again.
The chat changes nothing: it has no tool, it only explains with the packaged documentation.
"""
from __future__ import annotations

import hashlib
import secrets
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..config import HelpChatSettings
from ..logging import EventLogger, NullLogger
from ..storage import CorruptState, JsonStore
from . import HelpBase, HelpUnavailable

PREFIX = "help-chat-"
MAX_TURNS = 10
MAX_QUEUED = 8
WORKERS = 2
KEEP = timedelta(hours=24)
Status = Literal["queued", "running", "completed", "failed", "interrupted", "cancelled"]
OPEN = {"queued", "running"}

# Fixed, safe messages; never a provider text.
MESSAGES = {
    "disabled": "Der Hilfschat ist ausgeschaltet; es wird kein weiterer KI-Aufruf gestartet.",
    "cancelled": "Die Frage gehört zu einem geleerten Chat und wird nicht erneut gesendet.",
    "not_found": "Dazu enthält die Mailhelp-Dokumentation keinen passenden Abschnitt. Bitte die Frage "
                 "genauer fassen oder in der Hilfe unter „Alle Abschnitte“ nachsehen.",
    "help_unavailable": "Die mitgelieferte Dokumentation ist nicht verfügbar; der Hilfschat antwortet nicht.",
    "not_configured": "Der Hilfschat ist nicht eingerichtet: In prompts.yaml fehlt der Schritt settings_help. "
                      "Den Block aus der mitgelieferten prompts.yaml übernehmen.",
    "session_ended": "Die Sitzung ist abgelaufen; die Frage wurde nicht gesendet.",
    "budget": "Das KI-Aufrufbudget ist gerade ausgeschöpft. Bitte in einer Minute erneut fragen.",
    "provider_refused": "Der KI-Anbieter hat die Anfrage abgelehnt (Zugang prüfen).",
    "provider_unavailable": "Der KI-Anbieter ist gerade nicht erreichbar. Bitte später erneut fragen.",
    "invalid_answer": "Die KI hat keine verwendbare Antwort mit gültigen Quellen geliefert.",
    "failed": "Die Frage konnte nicht beantwortet werden.",
    "interrupted": "Mailhelp wurde während der Antwort beendet. Die Frage wird nicht automatisch erneut "
                   "gesendet; ein bereits begonnener Aufruf kann trotzdem Kosten verursacht haben.",
}


class ChatRefused(ValueError):
    """A question that is not accepted; *code* names the reason."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str
    answer: str
    source_ids: list[str] = Field(default_factory=list)
    setting_ids: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    revision: str
    local: bool = False


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    key_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    chat_version: int = Field(ge=1)
    question: str
    setting_id: str | None = None
    status: Status = "queued"
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class ChatState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    version: int = Field(default=1, ge=1)
    turns: list[Turn] = Field(default_factory=list, max_length=MAX_TURNS)
    jobs: list[Job] = Field(default_factory=list)
    updated_at: datetime


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chat_name(session_id: str) -> str:
    """The state name of one session's chat; the session id itself is never stored."""
    return PREFIX + _hash(session_id)[:32]


class HelpChat:
    def __init__(self, store: JsonStore, settings: Callable[[], HelpChatSettings], base: Callable[[], HelpBase],
                 analyzer: Callable[[], Any], authorized: Callable[[str], bool],
                 redact: Callable[[str], str] = lambda text: text, now: Callable[[], datetime] | None = None,
                 logger: EventLogger | None = None, sessions: Callable[[], list[str]] = lambda: [],
                 cleanup_extra: Callable[[], None] = lambda: None):
        self.store, self.settings, self.base, self.analyzer = store, settings, base, analyzer
        self.authorized, self.redact, self.active_sessions = authorized, redact, sessions
        self.cleanup_extra = cleanup_extra
        self.now = now or (lambda: datetime.now(UTC))
        self.logger = logger or NullLogger()
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.sessions: dict[str, str] = {}  # job id -> session id, only in this process
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()

    # --- state -------------------------------------------------------------------------------
    def state(self, session_id: str) -> ChatState:
        try:
            value = self.store.load_model(chat_name(session_id), ChatState)
        except CorruptState:
            value = None
        return value or ChatState(updated_at=self.now())

    def _save(self, session_id: str, state: ChatState) -> None:
        self.store.save(chat_name(session_id), state.model_copy(update={"updated_at": self.now()}).model_dump(
            mode="json"))

    # --- user actions ------------------------------------------------------------------------
    def submit(self, session_id: str, question: str, key: str, version: int, setting_id: str | None = None) -> Job:
        """Accept one explicitly sent question; the same key and content give the same job."""
        settings = self.settings()
        question = self.redact(" ".join(question.split()))
        if not settings.enabled:
            raise ChatRefused("disabled", "Der Hilfschat ist ausgeschaltet.")
        if not question:
            raise ChatRefused("empty", "Bitte eine Frage eingeben.")
        if len(question) > settings.max_question_chars:
            raise ChatRefused("too_long", f"Die Frage ist länger als {settings.max_question_chars} Zeichen.")
        key_hash, content = _hash(key), _hash(f"{version}\0{setting_id}\0{question}")
        with self.lock, self.store.locked():
            state = self.state(session_id)
            known = next((job for job in state.jobs if job.key_hash == key_hash), None)
            if known is not None:
                if known.content_hash != content:
                    raise ChatRefused("conflict", "Dieser Schlüssel wurde schon für eine andere Frage verwendet.")
                return known
            if version != state.version:
                raise ChatRefused("stale", "Der Chat wurde inzwischen geleert; bitte die Seite neu laden.")
            if any(job.status in OPEN for job in state.jobs):
                raise ChatRefused("busy", "Es wird noch eine Frage beantwortet.")
            now = self.now()
            recent = [job for job in state.jobs if job.created_at > now - timedelta(seconds=60)]
            if len(recent) >= settings.requests_per_minute_per_session:
                raise ChatRefused("rate_limited", "Zu viele Fragen in kurzer Zeit; bitte eine Minute warten.")
            if sum(1 for job in self._queued()) >= MAX_QUEUED:
                raise ChatRefused("full", "Die Hilfe ist gerade ausgelastet; bitte gleich erneut fragen.")
            job = Job(id=secrets.token_hex(16), key_hash=key_hash, content_hash=content, chat_version=state.version,
                      question=question, setting_id=setting_id, created_at=now, updated_at=now)
            jobs = [item for item in state.jobs if item.created_at > now - KEEP][-20:] + [job]
            self._save(session_id, state.model_copy(update={"jobs": jobs}))
            self.sessions[job.id] = session_id
        self.logger.event("INFO", "help_chat", "question_queued", job_id=job.id)
        self.wake.set()
        return job

    def job(self, session_id: str, job_id: str) -> Job | None:
        """A job of exactly this session; another session's job id finds nothing."""
        return next((job for job in self.state(session_id).jobs if job.id == job_id), None)

    def clear(self, session_id: str, version: int) -> int:
        """Forget the conversation; later results of older jobs are not appended."""
        with self.lock, self.store.locked():
            state = self.state(session_id)
            if version != state.version:
                raise ChatRefused("stale", "Der Chat wurde bereits geleert.")
            jobs = [job.model_copy(update={"question": "", "setting_id": None,
                                          "status": "cancelled" if job.status == "queued" else job.status})
                    for job in state.jobs]
            self._save(session_id, state.model_copy(update={"version": state.version + 1, "turns": [], "jobs": jobs}))
            return state.version + 1

    # --- worker ------------------------------------------------------------------------------
    def _queued(self) -> list[tuple[str, Job]]:
        found = []
        for job_id, session_id in list(self.sessions.items()):
            job = self.job(session_id, job_id)
            if job is not None and job.status == "queued":
                found.append((session_id, job))
        return sorted(found, key=lambda item: item[1].created_at)

    def _finish(self, session_id: str, job: Job, status: Status, error: str | None = None,
                turn: Turn | None = None) -> None:
        with self.lock, self.store.locked():
            state = self.state(session_id)
            jobs = [item.model_copy(update={"status": status, "error": error, "updated_at": self.now()})
                    if item.id == job.id else item for item in state.jobs]
            turns = state.turns
            if turn is not None and state.version == job.chat_version:
                turns = (turns + [turn])[-MAX_TURNS:]
            self._save(session_id, state.model_copy(update={"jobs": jobs, "turns": turns}))
        self.sessions.pop(job.id, None)
        self.logger.event("INFO", "help_chat", "question_finished", job_id=job.id, status=status, error=error)

    def run_once(self) -> bool:
        """Answer the oldest queued question; False when there is none."""
        with self.lock:
            queued = self._queued()
            if not queued:
                return False
            session_id, job = queued[0]
            with self.store.locked():
                state = self.state(session_id)
                running = [item.model_copy(update={"status": "running", "updated_at": self.now()})
                           if item.id == job.id else item for item in state.jobs]
                self._save(session_id, state.model_copy(update={"jobs": running}))
        history = [turn.question for turn in state.turns if state.version == job.chat_version]
        self._answer(session_id, job, history, state)
        return True

    def _answer(self, session_id: str, job: Job, history: list[str], state: ChatState) -> None:
        if not self.authorized(session_id):
            self._finish(session_id, job, "failed", "session_ended")
            return
        try:
            base = self.base()
        except HelpUnavailable:
            self._finish(session_id, job, "failed", "help_unavailable")
            return
        settings = self.settings()
        if not settings.enabled:
            self._finish(session_id, job, "failed", "disabled")
            return
        sources = base.select(job.question, setting_id=job.setting_id, history=tuple(history),
                              budget=settings.max_context_bytes)
        if not sources:
            self._finish(session_id, job, "completed", turn=Turn(
                question=job.question, answer=MESSAGES["not_found"], revision=base.revision, local=True,
                needs_clarification=True))
            return
        analyzer = self.analyzer()
        if analyzer is None or "settings_help" not in analyzer.prompts.prompts:
            self._finish(session_id, job, "failed", "not_configured")
            return
        from ..web.settings_search import catalog
        referenced = {key for section in sources for key in section.setting_ids}
        offered = [{"id": f"setting:{entry.key}", "label": entry.label, "path": entry.path}
                   for entry in catalog() if entry.key in referenced]
        recent = [{"question": turn.question, "answer": turn.answer} for turn in state.turns[-MAX_TURNS:]
                  if state.version == job.chat_version]
        try:
            _call, answer = analyzer.settings_help(job.question, sources, recent, offered,
                                                  before_call=lambda: self._before_call(session_id, job))
        except Exception as error:  # every failure ends in a fixed, safe message
            self._finish(session_id, job, "failed", classify(error))
            return
        self._finish(session_id, job, "completed", turn=Turn(
            question=job.question, answer=self.redact(answer.answer), source_ids=answer.source_ids,
            setting_ids=answer.setting_ids, needs_clarification=answer.needs_clarification, revision=base.revision))

    def _before_call(self, session_id: str, job: Job) -> None:
        """Recheck every paid attempt, including provider and structured-answer retries."""
        if not self.authorized(session_id):
            raise ChatRefused("session_ended")
        if not self.settings().enabled:
            raise ChatRefused("disabled")
        if self.state(session_id).version != job.chat_version:
            raise ChatRefused("cancelled")

    def cleanup(self) -> int:
        """Chats of ended sessions (logout, revocation) and chats idle for 24 hours are deleted."""
        self.cleanup_extra()
        keep = {chat_name(session_id) for session_id in self.active_sessions()}
        removed = 0
        for name in self.store.names(PREFIX):
            try:
                state = self.store.load_model(name, ChatState)
            except CorruptState:
                continue
            if name not in keep or state is None or state.updated_at < self.now() - KEEP:
                self.store.delete(name)
                removed += 1
        return removed

    def recover(self) -> int:
        """After a restart: open jobs are interrupted, never sent again; ended chats are removed."""
        self.cleanup()
        changed = 0
        for name in self.store.names(PREFIX):  # damaged chats were set aside by cleanup()
            state = self.store.load_model(name, ChatState)
            assert state is not None
            jobs = [job.model_copy(update={"status": "interrupted", "error": "interrupted"})
                    if job.status in OPEN else job for job in state.jobs]
            jobs = [job.model_copy(update={"question": "", "setting_id": None})
                    if job.chat_version < state.version else job for job in jobs]
            if jobs != state.jobs:
                self.store.save(name, state.model_copy(update={"jobs": jobs}).model_dump(mode="json"))
                changed += 1
        return changed

    def start(self) -> None:
        for number in range(WORKERS):
            thread = threading.Thread(target=self._loop, name=f"help-chat-{number}", daemon=True)
            thread.start()
            self._threads.append(thread)

    def _loop(self) -> None:
        while not self._stop.is_set():
            if not self.run_once():
                self.cleanup()
                self.wake.wait(60)
                self.wake.clear()

    def stop(self) -> None:
        self._stop.set()
        self.wake.set()
        for thread in self._threads:
            thread.join(5)


def redactor(values: list[str]) -> Callable[[str], str]:
    """Known secrets (from .env) never reach the model or the stored chat."""
    known = sorted({value for value in values if len(value) >= 6}, key=len, reverse=True)

    def redact(text: str) -> str:
        for value in known:
            text = text.replace(value, "[entfernt]")
        return text
    return redact


def secret_values(model: BaseModel) -> list[str]:
    """Every secret string of the secrets model, including those of each mailbox."""
    from pydantic import SecretStr
    found: list[str] = []
    for value in model.__dict__.values():
        items = value.values() if isinstance(value, dict) else [value]
        for item in items:
            if isinstance(item, SecretStr):
                found.append(item.get_secret_value())
            elif isinstance(item, BaseModel):
                found += secret_values(item)
    return found


def classify(error: Exception) -> str:
    from ..llm.adapter import PermanentError, RetryableError
    from ..llm.openrouter import RateLimitExceeded
    from ..processing.analysis import TechnicalRevisionError
    if isinstance(error, ChatRefused):
        return error.code
    if isinstance(error, RateLimitExceeded):
        return "budget"
    if isinstance(error, PermanentError):
        return "provider_refused"
    if isinstance(error, (RetryableError, TimeoutError, ConnectionError)):
        return "provider_unavailable"
    if isinstance(error, TechnicalRevisionError):
        return "invalid_answer"
    return "failed"
