"""Construction of the application: one factory per part (Planung 2.1, A4)."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from threading import Event, Lock
from typing import Any

from ..config import MailboxSettings, PromptConfig, Secrets, Settings, Topic
from ..config.configuration import ConfigurationService, effective_models
from ..external.providers import build_writers, provider_services
from ..external.roles import writer_for
from ..helpdocs.chat import HelpChat, redactor, secret_values
from ..i18n import Locale
from ..llm.adapter import RetryPolicy
from ..llm.decisions import (
    DecisionAnalyzer,
    DecisionClient,
    JevRelevanceAnalyzer,
    load_relevance_prompts,
    relevance_fingerprint,
)
from ..llm.fingerprints import (
    adopt_legacy_configuration,
    legacy_fingerprints,
    legacy_policies,
    proposal_match_policy,
    topic_policy,
)
from ..llm.ollama import LocalLlm, OllamaClient
from ..llm.openrouter import OpenRouterClient
from ..logging import JsonlLogger
from ..mailbox.imap import ImapReader, mailbox_account_id, reader_arguments
from ..mailbox.iserv import IServRunService
from ..mailbox.iserv_runtime import IServRuntime
from ..mailbox.mailbox_run import MailboxSource
from ..mailbox.mailbox_runtime import MailboxRuntime
from ..mailbox.sources import build_iserv_sources, mailbox_labels
from ..notifications.notification_runtime import NotificationRuntime
from ..paths import runtime_path
from ..persistence.storage import JsonStore
from ..processing.analysis import Analyzer
from ..processing.mail_recheck import request_recheck
from ..processing.orchestrator import Orchestrator
from ..processing.vision import VisionExtractor
from ..proposals import profile_binding
from ..proposals.precheck import DuplicatePreCheckService
from ..proposals.target_profiles import build_profile_writers
from ..review.inbox import CommandInbox
from ..review.learning_log import DecisionLearningLog
from ..rule_learning.service import DecisionRuleLearning
from ..runtime import experience
from ..runtime.diagnostics import DiagnosticResult, error_code
from ..runtime.experience import ExperienceRuntime
from ..runtime.instance_mode import InstanceMode, load_instance_mode
from ..runtime.learning_worker import LearningWorker
from ..runtime.lifecycle import Lifecycle
from ..runtime.reanalysis_worker import ReanalysisWorker, mailbox_readers
from ..runtime.standalone import DisabledTelegram
from ..support.connection_health import ConnectionHealthRecorder, used_connections
from ..support.metrics import DECISION_TEST_FILE, PRODUCTION_FILE, MetricsRecorder, adopt_legacy, metrics_directory
from ..telegram import TelegramClient, TelegramDialogController
from ..telegram.receiver import TelegramInbox
from ..usage.valuations import USAGE_DIRECTORY, UsageMeter
from ..web.factory import create_web
from ..web.learning_site import LearningSite
from ..web.reanalysis_site import ReanalysisSite
from ..web.reload_site import ReloadSite
from .application import Application
from .browser_accounts import attach_accounts
from .setup_runtime import SetupRuntime


class _FailedAccessAdapter:
    """Expose an adapter construction failure to the aggregated access check."""

    def __init__(self, error: Exception, mailbox_id: str = "0" * 24) -> None:
        self.error = error
        self.account_id, self.last_uidvalidity = mailbox_id, None

    def check_access(self, *_args: object) -> None:
        raise self.error

    def discover_since(self, *_args: object, **_kwargs: object) -> None:
        raise RuntimeError("IMAP nicht bereit; Zugang unter /diagnose prüfen und Mailhelp neu starten.")

    fetch_uid = discover_since
    list_folders = discover_since
    fetch_since = discover_since
    determine_start_uid = discover_since


def _state_directory(settings: Settings, base_directory: Path) -> Path:
    """Return the fully isolated state namespace for the selected mode."""
    root = runtime_path(settings.data_directory, base_directory)
    return root / ("test" if settings.test_mode else "production")


def build_logger(
    settings: Settings,
    secrets: Secrets,
    base_directory: Path = Path("."),
    *,
    access_diagnostics: bool = False,
    log_directory: Path | None = None,
) -> JsonlLogger:
    """Construct the configured logger with every known secret redacted."""
    log_dir = log_directory if log_directory is not None else settings.logging.directory
    log_dir = runtime_path(log_dir, base_directory)
    known_secrets = secrets.known_values()
    log = settings.logging
    return JsonlLogger(
        log_dir, log.llm.include_requests, log.llm.include_responses,
        "DEBUG" if access_diagnostics else log.file.level,
        {} if access_diagnostics else log.modules,
        known_secrets,
        verbose=access_diagnostics or log.verbose,
        file_enabled=access_diagnostics or log.file.enabled, file_name=log.file.filename,
        file_format=log.file.format, file_max_bytes=log.file.max_bytes,
        file_backup_count=log.file.backup_count, file_retention_days=log.file.retention_days,
        console_enabled=access_diagnostics or log.console.enabled,
        console_level="DEBUG" if access_diagnostics else log.console.level,
        console_format=log.console.format,
        llm_enabled=log.llm.enabled, llm_level=log.llm.level,
        llm_name=log.llm.filename, llm_format=log.llm.format,
        llm_max_bytes=log.llm.max_bytes, llm_backup_count=log.llm.backup_count,
        llm_retention_days=log.llm.retention_days,
        telegram_enabled=log.telegram.enabled,
        telegram_level=log.telegram.level,
        telegram_name=log.telegram.filename,
        telegram_format=log.telegram.format,
        telegram_max_bytes=log.telegram.max_bytes,
        telegram_backup_count=log.telegram.backup_count,
        telegram_retention_days=log.telegram.retention_days,
    )


def _attach_metrics(logger: JsonlLogger, settings: Settings, base_directory: Path, data: Path,
                    store: JsonStore, local_llm: LocalLlm | None) -> None:
    metrics_root = metrics_directory(runtime_path(settings.logging.directory, base_directory))
    production = metrics_root / PRODUCTION_FILE
    comparison = metrics_root / DECISION_TEST_FILE
    adopt_legacy(data / "metrics" / "llm.jsonl", production)
    adopt_legacy(data.parent / "decision-tests" / "metrics" / "llm.jsonl", comparison)
    recorder = MetricsRecorder(production, settings.metrics, "local" if local_llm else "standard")
    recorder.comparison = MetricsRecorder(comparison, settings.metrics, "decision_test")
    recorder.changed = store.touch
    recorder.health = ConnectionHealthRecorder(store)
    logger.metrics = recorder


def _build_imap(mailbox: MailboxSettings, settings: Settings, secrets: Secrets, policy: Callable[[str], RetryPolicy],
                logger: JsonlLogger, access_diagnostics: bool, stack: ExitStack) -> Any:
    credentials = secrets.imap_credentials(mailbox.id)
    address, options = reader_arguments(mailbox, credentials, settings.hosted_auth)
    try:
        imap = ImapReader(*address, settings.timeouts.imap.timeout_seconds, **options,
                          policy=policy("imap"), logger=logger, batch_size=settings.imap.batch_size)
    except Exception as exc:
        if not access_diagnostics and not settings.web.enabled:
            raise
        # IMAP connects and authenticates in its constructor, unlike the
        # HTTP adapters. Preserve that failure as one diagnostic result so
        # constructing the application cannot prevent the other checks.
        return _FailedAccessAdapter(exc, mailbox_account_id(mailbox, credentials))
    stack.callback(imap.close)
    return imap


def _build_llm(settings: Settings, secrets: Secrets, local_llm: LocalLlm | None, llm_budget: dict[str, Any],
               logger: JsonlLogger, stack: ExitStack, meter: UsageMeter | None = None) -> OpenRouterClient:
    openrouter: OpenRouterClient
    if local_llm is None:
        llm_cfg = settings.timeouts.openrouter
        openrouter = OpenRouterClient(secrets.openrouter_api_key.get_secret_value(), llm_cfg.timeout_seconds,
                                      llm_cfg.retries, settings.limits.llm_calls_per_minute,
                                      initial_backoff=llm_cfg.initial_backoff_seconds,
                                      max_backoff=llm_cfg.max_backoff_seconds, meter=meter, **llm_budget)
    else:
        # Experimental: every LLM stage runs on the local Ollama model.
        llm_cfg = settings.timeouts.ollama
        openrouter = OllamaClient(local_llm, llm_cfg.timeout_seconds, llm_cfg.retries,
                                  settings.limits.llm_calls_per_minute, initial_backoff=llm_cfg.initial_backoff_seconds,
                                  max_backoff=llm_cfg.max_backoff_seconds, **llm_budget)
        logger.event("WARNING", "application", "local_llm_experimental",
                     host=local_llm.host, port=local_llm.port, model=local_llm.model,
                     num_ctx=local_llm.num_ctx)
    stack.callback(openrouter.close)
    return openrouter


def _build_telegram(settings: Settings, secrets: Secrets, policy: Callable[[str], RetryPolicy],
                    logger: JsonlLogger, stack: ExitStack) -> Any:
    if settings.telegram.enabled:
        telegram: TelegramClient | DisabledTelegram = TelegramClient(
            secrets.telegram_bot_token.get_secret_value(), settings.timeouts.telegram.timeout_seconds,
            poll_timeout=settings.timeouts.telegram_poll_seconds, policy=policy("telegram"), logger=logger,
            locale=Locale(settings.language))
    else:
        telegram = DisabledTelegram()
    stack.callback(telegram.close)
    return telegram


def _build_analyzer(settings: Settings, secrets: Secrets, prompts: PromptConfig, openrouter: OpenRouterClient,
                    jev_prompts: Any, llm_budget: dict[str, Any], stop_event: Event, stack: ExitStack,
                    meter: UsageMeter | None = None) -> Analyzer:
    analyzer_options: dict[str, Any] = {}
    analyzer_type: Callable[..., Analyzer] = Analyzer
    if jev_prompts is not None:
        llm_cfg = settings.timeouts.openrouter
        decision_client = DecisionClient(
            secrets.openrouter_api_key.get_secret_value(), llm_cfg.timeout_seconds,
            llm_cfg.retries, settings.limits.llm_calls_per_minute,
            initial_backoff=llm_cfg.initial_backoff_seconds,
            max_backoff=llm_cfg.max_backoff_seconds, stopped=stop_event.wait, meter=meter, **llm_budget)
        stack.callback(decision_client.close)
        # Both adapters charge the same durable budget atomically.
        shared_lock = Lock()
        openrouter._state_lock = decision_client._state_lock = shared_lock
        analyzer_options["decisions"] = DecisionAnalyzer(
            decision_client, jev_prompts, settings.limits.max_llm_payload_bytes)
        analyzer_type = JevRelevanceAnalyzer
    return analyzer_type(
        openrouter, prompts,
        provider_retries=settings.retries.provider_retry,
        json_repair_retries=settings.retries.json_repair,
        schema_repair_retries=settings.retries.schema_repair,
        **analyzer_options,
    )


def _build_dialog(settings: Settings, store: JsonStore, telegram: Any, logger: JsonlLogger, writers: dict[str, Any],
                  analyzer: Analyzer, web_enabled: bool) -> TelegramDialogController:
    telegram_inbox = TelegramInbox(store)
    dialog = TelegramDialogController(
        store, telegram, settings.telegram.user_id, settings.telegram.chat_id, logger,
        writers, settings.test_mode,
        settings.timezone,
        analyzer,
        interpretation_attempts=settings.retries.interpretation_attempts,
        interpretation_backoff_seconds=settings.retries.interpretation_backoff_seconds,
        revision_attempts=settings.retries.revision_attempts,
        revision_backoff_seconds=settings.retries.revision_backoff_seconds,
        sequential_questions=settings.telegram.sequential_questions,
        inbox=telegram_inbox,
        commands=CommandInbox(store, wake=telegram_inbox.wake) if web_enabled else None,
        write_verification=settings.write_verification,
    )
    llm_log = logger.llm
    llm_logs = [llm_log, *(llm_log.with_name(f"{llm_log.name}.{number}")
                           for number in range(1, settings.logging.llm.backup_count + 1))]
    dialog.learning = DecisionLearningLog(store, settings.retention.decision_learning_days, logger,
                                          llm_logs=llm_logs if settings.learning.decision_llm_content else ())
    dialog.locale = Locale(settings.language)
    return dialog


@dataclass(frozen=True)
class _AnalysisConfiguration:
    """What decides how mails are analysed; part of every configuration fingerprint."""
    settings: Settings
    prompts: PromptConfig
    topics: list[Topic]
    fingerprint: str
    jev_prompts: Any


def _build_orchestrator(analysis: _AnalysisConfiguration, store: JsonStore, sender_store: JsonStore,
                        logger: JsonlLogger, analyzer: Analyzer, dialog: TelegramDialogController,
                        writers: dict[str, Any], access_diagnostics: bool) -> Orchestrator:
    settings, prompts, topics = analysis.settings, analysis.prompts, analysis.topics
    fingerprint, jev_prompts = analysis.fingerprint, analysis.jev_prompts
    precheck = DuplicatePreCheckService(
        writers=writers,
        ledger=dialog.ledger,
        logger=logger,
    )
    vision = None
    dialog.decision_service.precheck = precheck
    if settings.vision.enabled and "vision_ocr" in prompts.prompts:
        vision = VisionExtractor(analyzer, settings.vision)
    elif settings.vision.enabled:
        # A prompts.yaml from before 1.4: no image is sent anywhere.
        logger.event("WARNING", "application", "vision_prompt_missing")
    orchestrator = Orchestrator(analyzer, store, dialog, settings.telegram.chat_id, topics,
                                settings.limits.max_mail_bytes, logger, mime_limits=settings.limits,
                                config_fingerprint=fingerprint, targets=settings.targets,
                                user_timezone=settings.timezone, sender_store=sender_store, precheck=precheck,
                                vision=vision, event_defaults=settings.event_defaults,
                                reconciliation_settings=settings.proposal_reconciliation,
                                proposal_matcher=(analyzer.open_proposal_match
                                                  if "open_proposal_match" in prompts.prompts else None))
    orchestrator.reconciliation.policy = proposal_match_policy(prompts)
    orchestrator.reconciliation.recover()
    orchestrator.topic_policy = topic_policy(settings, prompts)
    if not access_diagnostics:
        legacy = legacy_fingerprints(settings, prompts, topics)
        if jev_prompts is not None:
            legacy = {relevance_fingerprint(item, jev_prompts) for item in legacy}
        # Mails started through 3.1 with this same analysis configuration continue.
        adopt_legacy_configuration(store, fingerprint, legacy, orchestrator.topic_policy,
                                   legacy_policies(settings, prompts), topics)
    return orchestrator


def _web_components(application: Application, settings: Settings, secrets: Secrets) -> Any:
    """Web server, authentication and site, wired to the Telegram dialog."""
    store, logger, dialog = application.store, application.logger, application.dialog
    # build_application always creates the dialog and its command inbox before the web interface.
    assert dialog is not None and dialog.commands is not None
    telegram = application.telegram
    secret = secrets.mailhelp_web_secret
    if settings.telegram.enabled:
        def notify(text: str) -> None:
            telegram.send(settings.telegram.chat_id, text)
    else:
        # Standalone: pairing codes appear only in the console of the PC, never in a log file.
        def notify(text: str) -> None:
            print(text, flush=True)
    components = create_web(
        settings, secret.get_secret_value() if secret is not None else None, store,
        notify, logger, dialog.commands)
    if not settings.telegram.enabled:
        components.auth.channel = "console"
    dialog.review.web_authorizer = components.authorize
    dialog.web_logout = components.auth.revoke_all
    dialog.web_invite = components.invite
    application.web = components.server
    return components


def _apply_instance_mode(application: Application, components: Any, mode: InstanceMode) -> None:
    """8.7: in customer mode sessions carry roles; Telegram is a customer channel."""
    if not mode.customer_mode:
        return
    revoked = components.auth.enter_customer_mode(mode.instance)
    components.site.learning_price = mode.learning_usd_per_million_tokens
    application.logger.event("INFO", "web", "customer_mode_active", instance=mode.instance,
                             revoked_sessions=revoked)
    assert application.dialog is not None
    application.dialog.web_logout = lambda: components.auth.revoke_all(customers_only=True)


def _attach_configuration(application: Application, components: Any, settings: Settings, base_directory: Path,
                          sender_store: JsonStore) -> ConfigurationService:
    """Confirmed configuration changes and the lifecycle of the running process."""
    store, logger, dialog = application.store, application.logger, application.dialog
    stop_event = application.stop_event
    assert dialog is not None
    configuration = ConfigurationService(base_directory, store, settings, components.authorize,
                                          application.request_settings, application.request_topics,
                                          senders=sender_store)
    application.configuration = configuration
    dialog.review.configuration = configuration
    lifecycle = Lifecycle(
        application.stop, components.authorize_operator,
        lambda state, process: logger.event("INFO", "lifecycle", state, process=process),
        authorize_restart=components.authorize)  # 8.8.3: customers restart, only the operator stops
    components.site.lifecycle = application.lifecycle = components.site.archive.lifecycle = lifecycle
    dialog.stop_requested = lambda: lifecycle.state != "running" or stop_event.is_set()
    components.site.archive.configuration = configuration
    return configuration


def _attach_views(application: Application, components: Any, configuration: ConfigurationService,
                  prompts: PromptConfig, jev_prompts: Any, local_llm: LocalLlm | None) -> None:
    """What the pages show: profiles, mailboxes, metrics and the models in use."""
    dialog, logger = application.dialog, application.logger
    assert dialog is not None
    components.site.views.profile_label = dialog.presenter.profile_of
    components.site.views.profile_available = dialog.presenter.profile_available
    components.site.views.reminder_setting = dialog.presenter.reminder_of
    components.site.views.removal_window_minutes = lambda: configuration.active.targets.removal_window_minutes
    components.site.views.removable = lambda proposal: getattr(
        writer_for(dialog.writers, proposal), "supports_remove", True)
    if len(application.sources) > 1:
        # Labels and the mailbox filter appear only with several mailboxes (3.1).
        labels = {source.account_id: (source.mailbox.id, source.mailbox.label) for source in application.sources}
        components.site.views.mailboxes = components.site.archive.queries.mailboxes = labels
    components.site.archive.metrics = logger.metrics
    # _attach_metrics always gives the recorder its sign-in status (7.9.2).
    assert logger.metrics is not None and logger.metrics.health is not None
    # 7.9.2: a removed or deactivated connection leaves no warning behind.
    iserv = getattr(application, "iserv", None)
    services = [getattr(writer, "service", "") for writer in application._active_writers()]
    logger.metrics.health.retain(*used_connections(
        [service for service in services if service],
        [getattr(source, "account_id", "") for source in application.sources],
        [source.account.id for source in iserv.sources] if iserv else []))
    components.site.archive.models = effective_models(
        prompts, jev_prompts.model if jev_prompts else None, local_llm.model if local_llm else None)


def _attach_workers(application: Application, components: Any, configuration: ConfigurationService,
                    settings: Settings, secrets: Secrets, base_directory: Path) -> None:
    """Setup, learning, rule learning, re-analysis and the help chat, each in its own worker."""
    store, logger, dialog = application.store, application.logger, application.dialog
    assert dialog is not None
    application.experience = ExperienceRuntime(application, components, secrets)
    components.site.setup_page.runtime = SetupRuntime(application, components.site, secrets)
    application.services.diagnostics = components.site.setup_page.runtime.diagnostics
    application.web_site = components.site
    application.services.learning = LearningWorker(application, components.site, secrets)
    LearningSite(components.site, application.services.learning)
    rules = DecisionRuleLearning(configuration, lambda: application.analyzer,
                                 lambda actor: not application.stop_event.is_set() and components.authorize(actor),
                                 redactor(secret_values(secrets)),
                                 payload_limit=lambda: application.settings.limits.max_llm_payload_bytes,
                                 logger=logger)
    application.services.learning.rules = components.site.rule_learning.service = rules
    # 5.1.5: "Aufgabe oder Termin übersehen?" – bounded re-analysis in its own thread.
    application.services.reanalysis = ReanalysisWorker(
        store, settings.reanalysis, application.orchestrator, logger,
        mailbox_readers(settings, secrets, experience._reader), dialog.send_proposal,
        lambda actor: actor.startswith("web:") and components.site.auth.active(actor.removeprefix("web:")))
    ReanalysisSite(components.site, application.services.reanalysis)
    # 5.3: the help chat explains with the packaged documentation over the active model path.
    help_site = components.site.archive.help
    help_site.chat = application.services.help_chat = HelpChat(
        store, lambda: application.settings.help_chat, help_site.base, lambda: application.analyzer,
        components.site.auth.active, redactor(secret_values(secrets)), logger=logger,
        sessions=lambda: [session.id for session in components.site.auth.sessions()],
        cleanup_extra=help_site.window.cleanup,
        customer=lambda session_id: not components.site.auth.is_operator(session_id))
    help_site.chat.recover()
    attach_accounts(application, components.site, base_directory)


def _record_service_health(application: Application, components: Any) -> None:
    """A mailbox that could not connect at start appears as a failed check on the setup page."""
    store = application.store
    health = store.load("service-health", {"schema_version": 1, "version": 0, "errors": {}})
    failed = [source.reader for source in application.sources if isinstance(source.reader, _FailedAccessAdapter)]
    errors: dict[str, Any] = {"imap": error_code(failed[0].error)} if failed else {}
    health["version"] += int(errors != health["errors"])
    health["errors"] = errors
    store.save("service-health", health)
    if errors:
        service = components.site.setup_page.runtime.diagnostics
        state = service.state()
        state.results["imap"] = DiagnosticResult(status="failed", code=errors["imap"], checked_at=service.clock(),
            config_revision=components.site.setup_page.runtime.setup.fingerprint())
        service._save(state)


def _attach_web(application: Application, settings: Settings, secrets: Secrets, prompts: PromptConfig,
                jev_prompts: Any, local_llm: LocalLlm | None, base_directory: Path, sender_store: JsonStore) -> None:
    components = _web_components(application, settings, secrets)
    _apply_instance_mode(application, components, load_instance_mode(base_directory))
    components.site.usage.meter = application.usage_meter
    configuration = _attach_configuration(application, components, settings, base_directory, sender_store)
    configuration.restricted = lambda actor: not components.authorize_operator(actor)
    _attach_views(application, components, configuration, prompts, jev_prompts, local_llm)
    _attach_workers(application, components, configuration, settings, secrets, base_directory)
    _record_service_health(application, components)
    assert application.experience is not None  # set by _attach_workers
    notifications = NotificationRuntime(application, components.site)
    application.experience.notifications = notifications
    components.site.notification_runtime = notifications
    application.notifications = notifications


def _record_write_services(logger: JsonlLogger, settings: Settings, secrets: Secrets,
                           sources: list[MailboxSource]) -> None:
    """Metrics name the write services and the mailbox number of each account."""
    assert logger.metrics is not None  # _attach_metrics above always sets the recorder
    logger.metrics.write_services = provider_services(settings.targets)
    logger.metrics.mailbox_numbers = {
        mailbox_account_id(source.mailbox, secrets.imap_credentials(source.mailbox.id)): source.mailbox.id
        for source in sources}


def _configure_mail_numbers(orchestrator: Orchestrator, settings: Settings, prompts: PromptConfig, secrets: Secrets,
                            sources: list[MailboxSource], iserv: list[Any], jev_prompts: Any) -> None:
    """Each mail is analysed with the settings of the mailbox its account belongs to."""
    numbers = {mailbox_account_id(source.mailbox, secrets.imap_credentials(source.mailbox.id)): source.mailbox.id
               for source in sources}
    # IServ letters use the settings of the mailbox their account names.
    numbers |= {source.reader.account_id: source.account.mailbox for source in iserv}
    orchestrator.configure_mailboxes(settings, prompts, numbers, jev_prompts)
    orchestrator.mailbox_usernames = {source.mailbox.id: secrets.imap_credentials(source.mailbox.id).username
                                      for source in sources}


def _attach_mail_runtimes(application: Application, iserv: list[Any], built: Any, web_enabled: bool,
                          iserv_resources: ExitStack, stack: ExitStack, secrets: Secrets) -> None:
    """IServ letters and mailboxes activated later run beside the configured mailboxes."""
    store, logger, stop_event, orchestrator = (application.store, application.logger, application.stop_event,
                                               application.orchestrator)
    if iserv:
        orchestrator.always_relevant = frozenset(source.reader.account_id for source in iserv)
        application.iserv = IServRunService(store, logger, iserv, application._process_mail, stop_event)
        application.mailbox.resume_readers = application.iserv.readers()
    application.profile_writers = built
    if web_enabled:
        application.iserv_runtime = IServRuntime(application, iserv_resources)
        stack.callback(application.iserv_runtime.close)
        application.mailbox_runtime = MailboxRuntime(application, stack.enter_context(ExitStack()), secrets)


def _wire_profiles(application: Application, dialog: TelegramDialogController, writers: dict[str, Any]) -> None:
    """Proposals show and offer only target profiles that are configured and reachable."""
    dialog.decision_service.profile_available = lambda proposal: profile_binding.available(
        application.settings, writers, proposal)
    dialog.presenter.profile_of = lambda proposal: profile_binding.label(application.settings, proposal)
    dialog.presenter.profile_available = dialog.decision_service.profile_available
    dialog.presenter.reminder_of = lambda proposal: profile_binding.calendar_reminder(application.settings, proposal)
    dialog.presenter.profiles_status = lambda: profile_binding.summary(application.settings, writers)
    dialog.presenter.retarget_choices = lambda proposal: profile_binding.choices(application.settings, proposal)


@dataclass(frozen=True)
class _InterfaceOptions:
    stack: ExitStack
    reload_service: Any
    use_jev_relevance: bool
    web_enabled: bool
    access_diagnostics: bool


def _attach_interfaces(application: Application, settings: Settings, secrets: Secrets, prompts: PromptConfig,
                       jev_prompts: Any, local_llm: LocalLlm | None, base_directory: Path, sender_store: JsonStore,
                       options: _InterfaceOptions) -> None:
    """Web interface with reload, or the notifications of a process without web interface."""
    stack, reload_service, use_jev_relevance = options.stack, options.reload_service, options.use_jev_relevance
    web_enabled, access_diagnostics = options.web_enabled, options.access_diagnostics
    if web_enabled:
        _attach_web(application, settings, secrets, prompts, jev_prompts, local_llm, base_directory, sender_store)
        # Late: reload imports the assembly at load time.
        from .reload import ReloadService
        application.resources = stack
        application.reload = reload_service or ReloadService(
            application, base_directory, secrets, local_llm, use_jev_relevance)
        ReloadSite(application.web_site, application.reload)
    elif not access_diagnostics:
        application.notifications = NotificationRuntime.without_web(application)


@contextmanager
def build_application(
    settings: Settings,
    secrets: Secrets,
    topics: list[Topic],
    prompts: PromptConfig,
    fingerprint: str,
    base_directory: Path = Path("."),
    *,
    access_diagnostics: bool = False,
    logger: JsonlLogger | None = None,
    local_llm: LocalLlm | None = None,
    use_jev_relevance: bool = True,
    shared_store: JsonStore | None = None,
    shared_stop: Event | None = None,
    reload_service: Any = None,
) -> Iterator[Application]:
    """Construct adapters and close every successfully constructed resource."""
    jev_prompts = None
    if use_jev_relevance and local_llm is None and not access_diagnostics:
        jev_prompts = load_relevance_prompts(base_directory)
        fingerprint = relevance_fingerprint(fingerprint, jev_prompts)
    with ExitStack() as lifetime, ExitStack() as stack:
        data = _state_directory(settings, base_directory)
        store = shared_store if shared_store is not None else lifetime.enter_context(JsonStore(data))
        sender_store = JsonStore(base_directory)
        if logger is None or access_diagnostics:
            logger = build_logger(
                settings, secrets, base_directory,
                access_diagnostics=access_diagnostics,
            )
        _attach_metrics(logger, settings, base_directory, data, store, local_llm)
        stop_event = shared_stop if shared_stop is not None else Event()
        def policy(name: str) -> RetryPolicy:
            item = getattr(settings.timeouts, name)
            return RetryPolicy(item.retries, item.initial_backoff_seconds, item.max_backoff_seconds, stop_event.wait)
        # One reader per enabled mailbox; a mailbox that cannot connect does not stop the others.
        sources = [MailboxSource(mailbox, _build_imap(mailbox, settings, secrets, policy, logger,
                                                     access_diagnostics, stack))
                   for mailbox in settings.imap.enabled_mailboxes()]
        imap = sources[0].reader
        llm_budget: dict[str, Any] = dict(
            load_calls=lambda: store.load("llm-budget", {}).get("calls", []),
            save_calls=lambda calls: store.save("llm-budget", {"calls": calls}), logger=logger)
        # 8.7: usage in points is recorded once the operator set the first valuation (--set-valuation).
        meter = UsageMeter(data / USAGE_DIRECTORY)
        openrouter = _build_llm(settings, secrets, local_llm, llm_budget, logger, stack, meter)
        telegram = _build_telegram(settings, secrets, policy, logger, stack)
        analyzer = _build_analyzer(settings, secrets, prompts, openrouter, jev_prompts, llm_budget, stop_event, stack,
                                   meter)
        factory = build_profile_writers if settings.target_profiles else build_writers
        built = factory(settings, secrets, base_directory, policy=policy, logger=logger,
                        calendar_matcher=analyzer.calendar_duplicate)
        stack.callback(built.close)
        _record_write_services(logger, settings, secrets, sources)
        todoist, calendar = built.tasks, built.calendar
        writers = built.slots
        web_enabled = settings.web.enabled and not access_diagnostics
        dialog = _build_dialog(settings, store, telegram, logger, writers, analyzer, web_enabled)
        orchestrator = _build_orchestrator(_AnalysisConfiguration(settings, prompts, topics, fingerprint, jev_prompts),
                                           store, sender_store, logger, analyzer, dialog, writers, access_diagnostics)
        dialog.relevance_handler = orchestrator
        dialog.review.recheck = partial(request_recheck, orchestrator)
        iserv_resources = stack.enter_context(ExitStack())
        iserv = build_iserv_sources(settings, secrets, iserv_resources)
        if len(sources) + len(iserv) > 1:
            dialog.presenter.mailbox_of = mailbox_labels(
                store, sources, {source.reader.account_id: source.account.label for source in iserv})
        orchestrator.original_attachments = settings.attachments
        orchestrator.stop_event = stop_event
        application = Application(settings, store, logger, imap, openrouter, analyzer, telegram, todoist, calendar,
                                  orchestrator, stop_event, dialog, sender_store, sources=sources)
        application.usage_meter = meter
        _configure_mail_numbers(orchestrator, settings, prompts, secrets, sources, iserv, jev_prompts)
        _attach_mail_runtimes(application, iserv, built, web_enabled, iserv_resources, stack, secrets)
        _wire_profiles(application, dialog, writers)
        _attach_interfaces(application, settings, secrets, prompts, jev_prompts, local_llm, base_directory,
                           sender_store, _InterfaceOptions(stack, reload_service, use_jev_relevance, web_enabled,
                                                           access_diagnostics))
        yield application
