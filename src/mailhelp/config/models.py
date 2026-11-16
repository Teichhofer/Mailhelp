"""Configuration models and their validation rules (no file or environment access)."""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from ..support.metrics import MetricsSettings
from .base import ConfigModel
from .mail_settings import DraftSettings, ImapSettings, IServSettings
from .notifications import NotificationSettings
from .runtime_settings import (
    ActivityReportSettings,
    BriefingSettings,
    DailyBriefingSettings,
    HelpChatSettings,
    LearningSettings,
    LimitSettings,
    LlmConnection,
    LoggingSettings,
    PushSettings,
    ReanalysisSettings,
    RetentionSettings,
    RetrySettings,
    TelegramSettings,
    TimeoutSettings,
    VisionSettings,
    WebSettings,
    WriteVerificationSettings,
    _valid_path,
)
from .target_settings import (
    EventDefaultsSettings,
    OriginalAttachmentSettings,
    ProposalReconciliationSettings,
    TargetProfileSettings,
    TargetSettings,
)


class Settings(ConfigModel):
    llm: LlmConnection = Field(default_factory=LlmConnection)
    notifications: NotificationSettings | None = None
    timezone: str
    poll_interval_seconds: int = Field(ge=5, le=86400)
    test_mode: bool = False
    data_directory: Path
    imap: ImapSettings
    telegram: TelegramSettings
    targets: TargetSettings
    target_profiles: list[TargetProfileSettings] = Field(default_factory=list, max_length=98)
    limits: LimitSettings
    retries: RetrySettings
    timeouts: TimeoutSettings
    logging: LoggingSettings
    retention: RetentionSettings = Field(default_factory=RetentionSettings)
    learning: LearningSettings = Field(default_factory=LearningSettings)
    web: WebSettings = Field(default_factory=WebSettings)
    metrics: MetricsSettings = Field(default_factory=MetricsSettings)
    vision: VisionSettings = Field(default_factory=VisionSettings)
    push: PushSettings = Field(default_factory=lambda: PushSettings())
    daily_briefing: DailyBriefingSettings = Field(default_factory=lambda: DailyBriefingSettings())
    briefings: BriefingSettings = Field(default_factory=BriefingSettings)
    smart_reply: bool = False
    drafts: DraftSettings = Field(default_factory=DraftSettings)
    # 4.8: with smart_reply, a mail that expects a written answer gets a draft in the drafts
    # folder without a click. Off by default (user decision of 8 November 2026).
    auto_draft: bool = False
    # Name, role, signature and similar facts the user wants in reply drafts.
    # Trusted context for draft_reply only; tab and line breaks are the only control characters.
    personal_info: str = Field(default="", max_length=2000, pattern=r"^[^\x00-\x08\x0b-\x1f\x7f]*$")
    activity_report: ActivityReportSettings = Field(default_factory=lambda: ActivityReportSettings())
    reanalysis: ReanalysisSettings = Field(default_factory=lambda: ReanalysisSettings())
    write_verification: WriteVerificationSettings = Field(default_factory=lambda: WriteVerificationSettings())
    help_chat: HelpChatSettings = Field(default_factory=lambda: HelpChatSettings())
    attachments: OriginalAttachmentSettings = Field(default_factory=lambda: OriginalAttachmentSettings())
    event_defaults: EventDefaultsSettings = Field(default_factory=EventDefaultsSettings)
    proposal_reconciliation: ProposalReconciliationSettings = Field(default_factory=ProposalReconciliationSettings)
    iserv: IServSettings = Field(default_factory=IServSettings)

    @model_validator(mode="after")
    def iserv_uses_enabled_mailboxes(self) -> Settings:
        enabled = {mailbox.id for mailbox in self.imap.enabled_mailboxes()}
        for account in self.iserv.enabled_accounts():
            if account.mailbox not in enabled:
                raise ValueError(f"iserv.accounts: Konto {account.id} verweist auf kein aktives Postfach")
        return self

    @model_validator(mode="after")
    def valid_mailbox_policies(self) -> Settings:
        # Late: against the layer direction, named in tests/unit/test_layers.py.
        from ..mailbox.mailbox_settings import validate_policies
        validate_policies(self)
        return self

    @model_validator(mode="after")
    def briefing_uses_enabled_mailbox(self) -> Settings:
        if (self.briefings.enabled and self.briefings.mailbox != "default"
                and self.briefings.mailbox not in {box.id for box in self.imap.enabled_mailboxes()}):
            raise ValueError("briefings.mailbox verweist auf kein aktives Postfach")
        return self

    @model_validator(mode="after")
    def standalone_needs_web(self) -> Settings:
        if not self.telegram.enabled and not self.web.enabled:
            raise ValueError("Ohne Telegram muss web.enabled aktiviert sein")
        return self

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try: ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc: raise ValueError("unbekannte IANA-Zeitzone") from exc
        return value

    @field_validator("data_directory", mode="before")
    @classmethod
    def valid_data_directory(cls, value: object) -> Path:
        if not isinstance(value, (str, Path)): raise ValueError("Pfad muss eine Zeichenkette sein")
        return _valid_path(Path(value))

class ImapCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1)
    password: SecretStr

class Secrets(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Credentials of every enabled mailbox by its stable number (3.1).
    imap: dict[int, ImapCredentials] = Field(min_length=1)
    openrouter_api_key: SecretStr
    telegram_bot_token: SecretStr = SecretStr("")
    # Each provider's secrets are only required while it is configured (2.3).
    todoist_token: SecretStr = SecretStr("")
    todoist_client_id: SecretStr = SecretStr("")
    todoist_client_secret: SecretStr = SecretStr("")
    google_oauth_client_id: SecretStr = SecretStr("")
    google_oauth_client_secret: SecretStr = SecretStr("")
    google_oauth_refresh_token: SecretStr = SecretStr("")
    caldav_username: SecretStr = SecretStr("")
    caldav_password: SecretStr = SecretStr("")
    microsoft_client_id: SecretStr = SecretStr("")
    microsoft_client_secret: SecretStr = SecretStr("")
    # Optional seed; a rotated token from ``mailhelp --microsoft-login`` takes precedence.
    microsoft_refresh_token: SecretStr = SecretStr("")
    # Signs web sessions and CSRF tokens; required only with web.enabled.
    mailhelp_web_secret: SecretStr | None = None
    profiles: dict[int, dict[str, SecretStr]] = Field(default_factory=dict)
    # Credentials of every enabled IServ account by its number.
    iserv: dict[int, ImapCredentials] = Field(default_factory=dict)

    def imap_credentials(self, mailbox_id: int) -> ImapCredentials:
        return self.imap[mailbox_id]

    def for_profile(self, profile_id: int) -> Secrets:
        # Late: against the layer direction, named in tests/unit/test_layers.py.
        from ..proposals.target_profiles import profile_secrets
        return profile_secrets(self, profile_id)

    def known_values(self) -> tuple[str, ...]:
        """Every secret value, for redaction in logs."""
        values = [credentials.password.get_secret_value()
                  for credentials in (*self.imap.values(), *self.iserv.values())]
        values += [value.get_secret_value() for name, value in self if isinstance(value, SecretStr)]
        values += [value.get_secret_value() for profile in self.profiles.values() for value in profile.values()]
        return tuple(value for value in values if value)

__all__ = ["ImapCredentials", "Secrets", "Settings"]
