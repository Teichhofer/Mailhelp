"""Telegram, limits, timeouts, logging, retention, web and the further services. (7.0: split from models.py)"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path, PureWindowsPath
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    Field,
    field_validator,
    model_validator,
)

from .base import ConfigModel


class TelegramSettings(ConfigModel):
    enabled: bool = True
    user_id: int = Field(default=1, gt=0)
    chat_id: int = 1
    sequential_questions: bool = True

class LimitSettings(ConfigModel):
    max_mail_bytes: int = Field(ge=1024, le=100_000_000)
    max_attachment_bytes: int = Field(default=5_000_000, ge=1024, le=100_000_000)
    max_header_bytes: int = Field(default=64_000, ge=256, le=1_000_000)
    max_display_header_characters: int = Field(default=500, ge=1, le=10_000)
    max_mime_parts: int = Field(default=100, ge=1, le=10_000)
    max_decoded_text_bytes: int = Field(default=1_000_000, ge=1, le=100_000_000)
    max_html_characters: int = Field(default=1_000_000, ge=1, le=100_000_000)
    max_html_tags: int = Field(default=20_000, ge=1, le=1_000_000)
    max_html_depth: int = Field(default=100, ge=1, le=10_000)
    max_llm_payload_bytes: int = Field(default=500_000, ge=1, le=100_000_000)
    llm_calls_per_minute: int = Field(ge=1, le=600)

class AdapterPolicySettings(ConfigModel):
    timeout_seconds: float = Field(ge=1, le=300)
    retries: int = Field(ge=0, le=10)
    initial_backoff_seconds: float = Field(ge=0, le=30)
    max_backoff_seconds: float = Field(ge=0, le=60)

    @model_validator(mode="after")
    def valid_backoff(self) -> AdapterPolicySettings:
        if self.max_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError("max_backoff_seconds muss mindestens initial_backoff_seconds sein")
        return self

class LocalLlmPolicySettings(AdapterPolicySettings):
    """Local models answer much slower than hosted ones: up to 1800 seconds."""

    timeout_seconds: float = Field(ge=1, le=1800)

class RetrySettings(ConfigModel):
    provider_retry: int = Field(ge=0, le=10)
    json_repair: int = Field(ge=0, le=10)
    schema_repair: int = Field(ge=0, le=10)
    interpretation_attempts: int = Field(default=3, ge=1, le=20)
    interpretation_backoff_seconds: int = Field(default=60, ge=1, le=86400)
    revision_attempts: int = Field(default=3, ge=1, le=20)
    revision_backoff_seconds: int = Field(default=60, ge=1, le=86400)

class TimeoutSettings(ConfigModel):
    imap: AdapterPolicySettings
    telegram: AdapterPolicySettings
    openrouter: AdapterPolicySettings
    todoist: AdapterPolicySettings
    google_calendar: AdapterPolicySettings
    caldav: AdapterPolicySettings = Field(default_factory=lambda: AdapterPolicySettings(
        timeout_seconds=30, retries=2, initial_backoff_seconds=1, max_backoff_seconds=10))
    microsoft: AdapterPolicySettings = Field(default_factory=lambda: AdapterPolicySettings(
        timeout_seconds=30, retries=2, initial_backoff_seconds=1, max_backoff_seconds=10))
    google_tasks: AdapterPolicySettings = Field(default_factory=lambda: AdapterPolicySettings(
        timeout_seconds=30, retries=2, initial_backoff_seconds=1, max_backoff_seconds=10))
    telegram_poll_seconds: int = Field(ge=1, le=50)
    # Only used in the experimental local mode (--ollama). Local models are
    # much slower than hosted ones, hence the generous default and limit.
    ollama: LocalLlmPolicySettings = Field(default_factory=lambda: LocalLlmPolicySettings(
        timeout_seconds=1800, retries=1, initial_backoff_seconds=2, max_backoff_seconds=10))

LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

class LogTargetSettings(ConfigModel):
    enabled: bool = True
    level: str = "INFO"
    format: Literal["text", "jsonl"] = "jsonl"

    @field_validator("level")
    @classmethod
    def valid_level(cls, value: str) -> str:
        if value not in LOG_LEVELS:
            raise ValueError("erlaubt sind DEBUG, INFO, WARNING, ERROR und CRITICAL")
        return value

class ConsoleLoggingSettings(LogTargetSettings):
    format: Literal["text", "jsonl"] = "text"

class RotatingLogSettings(LogTargetSettings):
    filename: Path
    max_bytes: int = Field(gt=0)
    backup_count: int = Field(ge=0)
    retention_days: int = Field(gt=0, le=3650)

    @field_validator("filename", mode="before")
    @classmethod
    def valid_filename(cls, value: object) -> Path:
        if not isinstance(value, (str, Path)):
            raise ValueError("Dateiname muss eine Zeichenkette sein")
        path = _valid_path(Path(value))
        if path.anchor or PureWindowsPath(path).anchor:
            raise ValueError("Log-Dateiname muss relativ zum Logverzeichnis sein")
        return path

class LlmLoggingSettings(RotatingLogSettings):
    include_requests: bool = False
    include_responses: bool = False

class TelegramLoggingSettings(RotatingLogSettings):
    """Separate audit trail containing Telegram message contents."""

    filename: Path = Path("telegram/messages.jsonl")
    max_bytes: int = Field(default=10_000_000, gt=0)
    backup_count: int = Field(default=5, ge=0)
    retention_days: int = Field(default=30, gt=0, le=3650)

class LoggingSettings(ConfigModel):
    verbose: bool = False
    directory: Path
    console: ConsoleLoggingSettings
    file: RotatingLogSettings
    modules: dict[str, str] = Field(default_factory=dict)
    llm: LlmLoggingSettings
    telegram: TelegramLoggingSettings = Field(default_factory=TelegramLoggingSettings)

    @field_validator("modules")
    @classmethod
    def valid_modules(cls, value: dict[str, str]) -> dict[str, str]:
        if any(not module.strip() or level not in LOG_LEVELS for module, level in value.items()):
            raise ValueError("Modulnamen müssen nicht leer sein und Log-Level gültig sein")
        return value

    @field_validator("directory", mode="before")
    @classmethod
    def valid_directory(cls, value: object) -> Path:
        if not isinstance(value, (str, Path)): raise ValueError("Pfad muss eine Zeichenkette sein")
        return _valid_path(Path(value))

RetentionPeriod = Annotated[int, Field(ge=1, le=3650)] | Literal["disabled", "unlimited"]

class RetentionSettings(ConfigModel):
    """Fristen für Inhalte abgeschlossener Vorgänge.

    Eine Zahl bezeichnet volle Tage, ``disabled`` entfernt den jeweiligen Inhalt
    beim nächsten Lauf sofort und ``unlimited`` schaltet dessen Bereinigung aus.
    """

    full_mail_days: RetentionPeriod = 30
    debug_llm_days: RetentionPeriod = "disabled"
    # None preserves the earlier debug retention for existing installations.
    analysis_days: RetentionPeriod | None = None
    history_days: RetentionPeriod = 90
    # Activity reports (2.2): full texts are removed, dates and senders stay.
    activity_report_days: RetentionPeriod = 365
    # Manual decisions as learning material (3.5.3); disabled records none.
    decision_learning_days: RetentionPeriod = "unlimited"
    # Minutes between cleanup runs (3.5.5); each run blocks the main thread. 0 runs it every cycle.
    cleanup_interval_minutes: int = Field(default=60, ge=0, le=1440)

class MailboxRetention(ConfigModel):
    full_mail_days: RetentionPeriod

class LearningSettings(ConfigModel):
    """Concurrency controls for the interactive learning workflow."""

    parallel_llm_calls: int = Field(default=4, ge=1, le=100)
    # Copies full prompts and responses from the LLM log into each decision record.
    decision_llm_content: bool = False
    sender_hints_enabled: bool = True
    sender_hint_days: int = Field(default=90, ge=1, le=365)
    sender_hint_min_proposals: int = Field(default=5, ge=1, le=100)
    sender_hint_max_acceptance_rate: float = Field(default=0.10, ge=0.0, le=1.0)
    learning_run_hints_enabled: bool = True
    learning_run_hint_rejections: int = Field(default=20, ge=1, le=500)

_WEB_HOST = re.compile(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:[0-9]{1,5})?")

class WebSettings(ConfigModel):
    """Optional web interface; disabled by default (Mailhelp then behaves like 1.0)."""

    enabled: bool = False
    # 127.0.0.1 on Windows; 0.0.0.0 only inside a container whose port is
    # published on 127.0.0.1 of the host.
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    # Exact Host headers accepted (protection against DNS rebinding).
    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["127.0.0.1:8765", "localhost:8765"], min_length=1, max_length=20)
    session_days: int = Field(default=30, ge=1, le=365)
    # Reachable in the home network under the PC's private IP address (plain
    # HTTP); /web uses it if no domain is configured. Requires host 0.0.0.0.
    lan_access: bool = False
    google_redirect_uri: str = "http://localhost:8765/auth/google/callback"

    @field_validator("google_redirect_uri")
    @classmethod
    def valid_google_redirect(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path != "/auth/google/callback"
                or parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}):
            raise ValueError("Google-Rückleitung benötigt HTTPS oder localhost und /auth/google/callback")
        return value

    @model_validator(mode="after")
    def lan_needs_all_interfaces(self) -> WebSettings:
        if self.lan_access and ipaddress.ip_address(self.host).is_loopback:
            raise ValueError("lan_access benötigt host 0.0.0.0")
        return self

    @field_validator("host")
    @classmethod
    def valid_host(cls, value: str) -> str:
        try:
            ipaddress.ip_address(value)
        except ValueError as exc:
            raise ValueError("host muss eine IP-Adresse sein") from exc
        return value

    @field_validator("allowed_hosts")
    @classmethod
    def valid_allowed_hosts(cls, value: list[str]) -> list[str]:
        if any(not _WEB_HOST.fullmatch(item) for item in value):
            raise ValueError("allowed_hosts enthält nur kleingeschriebene Hostnamen mit optionalem Port")
        return value

class VisionSettings(ConfigModel):
    """Multimodal OCR for image attachments and scanned PDFs (1.4).

    Model and prompt are the ``vision_ocr`` step in ``prompts.yaml``; without
    that step no image is sent.  The limits bound cost and data transfer.
    """

    enabled: bool = True
    max_images_per_mail: int = Field(default=3, ge=1, le=10)
    max_image_bytes: int = Field(default=5_000_000, ge=10_240, le=50_000_000)
    max_edge_pixels: int = Field(default=1600, ge=512, le=4096)

class PushSettings(ConfigModel):
    enabled: bool = False
    subject: str = Field(default="mailto:admin@example.invalid", pattern=r"^mailto:[^\s@]+@[^\s@]+$")

class ActivityReportSettings(ConfigModel):
    """Activity reports (2.2): read-only scans of the mailbox for one topic."""

    enabled: bool = False
    # A report pauses when one of these limits is reached.
    max_mails: int = Field(default=2000, ge=1, le=20000)
    max_llm_calls: int = Field(default=3000, ge=1, le=50000)
    # Share of limits.llm_calls_per_minute a running report may use.
    max_share_of_llm_budget: float = Field(default=0.5, gt=0, le=1)
    # Excel allows 32,767 characters per cell; the marker "… gekürzt" must fit as well.
    max_fulltext_chars: int = Field(default=30000, ge=1000, le=32000)
    export_mails_without_events: bool = True

class ReanalysisSettings(ConfigModel):
    """5.1: deliberate re-analysis of one mail; never writes to calendars or task lists."""

    enabled: bool = True
    # Router, task and event extraction need three calls; two more allow two retries.
    max_llm_calls_per_job: int = Field(default=5, ge=1, le=10)
    # A failed or interrupted model call is retried at most this often in total.
    max_attempts: int = Field(default=2, ge=1, le=5)
    # Started re-analyses per day across all mails (cost guard).
    max_jobs_per_day: int = Field(default=20, ge=1, le=500)

class WriteVerificationSettings(ConfigModel):
    """5.2: fresh reads after a write; only reads are repeated, never the write."""

    # The first read counts as attempt 1; one delay precedes every further attempt.
    max_attempts: int = Field(default=5, ge=1, le=10)
    retry_delays_seconds: list[int] = Field(default_factory=lambda: [1, 5, 15, 60], max_length=9)
    max_elapsed_seconds: int = Field(default=300, ge=10, le=86400)

    @model_validator(mode="after")
    def bounded(self) -> WriteVerificationSettings:
        if len(self.retry_delays_seconds) != self.max_attempts - 1:
            raise ValueError("write_verification.retry_delays_seconds braucht genau max_attempts - 1 Werte")
        if any(not 1 <= delay <= 3600 for delay in self.retry_delays_seconds):
            raise ValueError("write_verification.retry_delays_seconds: jeder Wert zwischen 1 und 3600 Sekunden")
        if sum(self.retry_delays_seconds) > self.max_elapsed_seconds:
            raise ValueError("write_verification: die Verzögerungen überschreiten max_elapsed_seconds")
        return self

class HelpChatSettings(ConfigModel):
    """5.3: the help chat explains settings with the packaged documentation; it changes nothing."""

    enabled: bool = True
    max_question_chars: int = Field(default=4000, ge=100, le=8000)
    max_context_bytes: int = Field(default=24000, ge=2000, le=48000)
    requests_per_minute_per_session: int = Field(default=6, ge=1, le=20)

class DailyBriefingSettings(ConfigModel):
    enabled: bool = False
    time: str = Field(default="07:30", pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    include_calendar: bool = True
    include_tasks: bool = True
    include_open: bool = True

class BriefingSettings(ConfigModel):
    """Scheduled IMAP briefing drafts, independent of Telegram's daily briefing."""

    enabled: bool = False
    times: list[Annotated[str, Field(pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")]] = Field(
        default_factory=lambda: ["07:00", "13:00", "18:00"], max_length=1440)
    mailbox: Annotated[int, Field(ge=1, le=99)] | Literal["default"] = "default"
    skip_empty: bool = True

    @model_validator(mode="after")
    def unique_times(self) -> BriefingSettings:
        if len(set(self.times)) != len(self.times) or self.enabled and not self.times:
            raise ValueError("Briefings benötigen eindeutige Uhrzeiten; aktiviert mindestens eine")
        self.times = sorted(self.times)
        return self

class LlmConnection(ConfigModel):
    provider: Literal["openrouter", "ollama"] = "openrouter"
    ollama_address: str = "localhost:11434"

    @field_validator("ollama_address")
    @classmethod
    def valid_address(cls, value: str) -> str:
        # Late: against the layer direction, named in tests/unit/test_layers.py.
        from ..llm.ollama import parse_address
        value = value.removeprefix("http://").removesuffix("/")
        parse_address(value)
        return value

def _valid_path(value: Path) -> Path:
    if not str(value).strip() or "\x00" in str(value) or ".." in value.parts:
        raise ValueError("Pfad muss sicher und nicht leer sein")
    return value
