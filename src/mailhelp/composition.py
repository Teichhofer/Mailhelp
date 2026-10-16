"""Construction of the application: one factory per part (Planung 2.1, A4)."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from threading import Event, Lock
from typing import Any

from .adapter import RetryPolicy
from .analysis import Analyzer
from .application import Application
from .config import MailboxSettings, PromptConfig, Secrets, Settings, Topic
from .decisions import (
    DecisionAnalyzer,
    DecisionClient,
    JevRelevanceAnalyzer,
    load_relevance_prompts,
    relevance_fingerprint,
)
from .external.providers import build_writers, provider_services
from .imap import ImapReader, mailbox_account_id, reader_arguments
from .logging import JsonlLogger
from .mailbox_run import MailboxSource
from .ollama import LocalLlm, OllamaClient
from .openrouter import OpenRouterClient
from .orchestrator import Orchestrator
from .paths import runtime_path
from .review.inbox import CommandInbox
from .storage import JsonStore
from .telegram import TelegramClient, TelegramDialogController
from .telegram.receiver import TelegramInbox
from .vision import VisionExtractor
from .web.factory import create_web


class _FailedAccessAdapter:
    """Expose an adapter construction failure to the aggregated access check."""

    def __init__(self, error: Exception, mailbox_id: str = "0" * 24):
        self.error = error
        self.account_id, self.last_uidvalidity = mailbox_id, None

    def check_access(self, *_args: object) -> None:
        raise self.error

    def discover_since(self, *_args, **_kwargs):
        raise RuntimeError("IMAP nicht bereit; Zugang unter /diagnose prüfen und Mailhelp neu starten.")

    fetch_uid = discover_since
    fetch_since = discover_since
    determine_start_uid = discover_since


def _mailbox_labels(store: JsonStore, sources: list[MailboxSource],
                    further: dict[str, str] | None = None) -> Callable[[Any], str]:
    """The label of the mailbox (or IServ account) a proposal's mail came from (3.1)."""
    from . import state_names
    from .models import MailState
    labels = {source.account_id: source.mailbox.label for source in sources} | (further or {})

    def label(proposal: Any) -> str:
        mail = store.peek_model(state_names.mail(proposal.source_mail_id), MailState)
        return labels.get(mail.imap.account_id, "Entferntes Postfach") if mail is not None else ""
    return label


def _build_iserv(settings: Settings, secrets: Secrets, stack: ExitStack) -> list[Any]:
    """One reader per enabled IServ account (3.3.7); it signs in on first use, not here."""
    from .iserv import IServReader, IServSource
    result = []
    for account in settings.iserv.enabled_accounts():
        reader = IServReader(account, secrets.iserv[account.id], settings.timezone, settings.limits.max_mail_bytes,
                             max_attachment_bytes=settings.limits.max_attachment_bytes)
        stack.callback(reader.close)
        mailbox = settings.imap.mailbox(account.mailbox)
        assert mailbox is not None  # Settings validates that the mailbox is enabled
        result.append(IServSource(account, reader, account.historical_start or mailbox.historical_start))
    return result


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
    from .metrics import DECISION_TEST_FILE, PRODUCTION_FILE, MetricsRecorder, adopt_legacy, metrics_directory
    metrics_root = metrics_directory(runtime_path(settings.logging.directory, base_directory))
    production = metrics_root / PRODUCTION_FILE
    comparison = metrics_root / DECISION_TEST_FILE
    adopt_legacy(data / "metrics" / "llm.jsonl", production)
    adopt_legacy(data.parent / "decision-tests" / "metrics" / "llm.jsonl", comparison)
    recorder = MetricsRecorder(production, settings.metrics, "local" if local_llm else "standard")
    recorder.comparison = MetricsRecorder(comparison, settings.metrics, "decision_test")
    recorder.changed = store.touch
    logger.metrics = recorder


def _build_imap(mailbox: MailboxSettings, settings: Settings, secrets: Secrets, policy: Callable[[str], RetryPolicy],
                logger: JsonlLogger, access_diagnostics: bool, stack: ExitStack) -> Any:
    credentials = secrets.imap_credentials(mailbox.id)
    address, options = reader_arguments(mailbox, credentials)
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
               logger: JsonlLogger, stack: ExitStack) -> OpenRouterClient:
    openrouter: OpenRouterClient
    if local_llm is None:
        llm_cfg = settings.timeouts.openrouter
        openrouter = OpenRouterClient(secrets.openrouter_api_key.get_secret_value(), llm_cfg.timeout_seconds,
                                      llm_cfg.retries, settings.limits.llm_calls_per_minute,
                                      initial_backoff=llm_cfg.initial_backoff_seconds,
                                      max_backoff=llm_cfg.max_backoff_seconds, **llm_budget)
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
            poll_timeout=settings.timeouts.telegram_poll_seconds, policy=policy("telegram"), logger=logger)
    else:
        from .standalone import DisabledTelegram
        telegram = DisabledTelegram()
    stack.callback(telegram.close)
    return telegram


def _build_analyzer(settings: Settings, secrets: Secrets, prompts: PromptConfig, openrouter: OpenRouterClient,
                    jev_prompts: Any, llm_budget: dict[str, Any], stop_event: Event, stack: ExitStack) -> Analyzer:
    analyzer_options: dict[str, Any] = {}
    analyzer_type: Callable[..., Analyzer] = Analyzer
    if jev_prompts is not None:
        llm_cfg = settings.timeouts.openrouter
        decision_client = DecisionClient(
            secrets.openrouter_api_key.get_secret_value(), llm_cfg.timeout_seconds,
            llm_cfg.retries, settings.limits.llm_calls_per_minute,
            initial_backoff=llm_cfg.initial_backoff_seconds,
            max_backoff=llm_cfg.max_backoff_seconds, stopped=stop_event.wait, **llm_budget)
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
    return TelegramDialogController(
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
    )


def _build_orchestrator(settings: Settings, prompts: PromptConfig, topics: list[Topic], fingerprint: str,
                        jev_prompts: Any, store: JsonStore, sender_store: JsonStore, logger: JsonlLogger,
                        analyzer: Analyzer, dialog: TelegramDialogController, writers: dict[str, Any],
                        access_diagnostics: bool) -> Orchestrator:
    from .precheck import DuplicatePreCheckService
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
    from .fingerprints import (
        adopt_legacy_configuration,
        legacy_fingerprints,
        legacy_policies,
        proposal_match_policy,
        topic_policy,
    )
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


def _attach_web(application: Application, settings: Settings, secrets: Secrets, prompts: PromptConfig,
                jev_prompts: Any, local_llm: LocalLlm | None, base_directory: Path, sender_store: JsonStore) -> None:
    store, logger, dialog = application.store, application.logger, application.dialog
    # build_application always creates the dialog and its command inbox before the web interface.
    assert dialog is not None and dialog.commands is not None
    telegram, orchestrator, stop_event = application.telegram, application.orchestrator, application.stop_event
    secret = secrets.mailhelp_web_secret
    if settings.telegram.enabled:
        def notify(text):
            telegram.send(settings.telegram.chat_id, text)
    else:
        # Standalone: pairing codes appear only in the console of the PC, never in a log file.
        def notify(text):
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
    from .configuration import ConfigurationService
    from .lifecycle import Lifecycle
    configuration = ConfigurationService(base_directory, store, settings, components.authorize,
                                          application.apply_settings, orchestrator.change_topics,
                                          senders=sender_store)
    application.configuration = configuration
    dialog.review.configuration = configuration
    components.site.lifecycle = Lifecycle(
        application.stop, components.authorize,
        lambda state, process: logger.event("INFO", "lifecycle", state, process=process))
    application.lifecycle = components.site.lifecycle
    components.site.archive.lifecycle = components.site.lifecycle
    dialog.stop_requested = lambda: components.site.lifecycle.state != "running" or stop_event.is_set()
    components.site.archive.configuration = configuration
    components.site.views.profile_label = dialog.presenter.profile_of
    components.site.views.profile_available = dialog.presenter.profile_available
    if len(application.sources) > 1:
        # Labels and the mailbox filter appear only with several mailboxes (3.1).
        labels = {source.account_id: (source.mailbox.id, source.mailbox.label) for source in application.sources}
        components.site.views.mailboxes = components.site.archive.queries.mailboxes = labels
    components.site.archive.metrics = logger.metrics
    from .configuration import effective_models
    components.site.archive.models = effective_models(
        prompts, jev_prompts.model if jev_prompts else None, local_llm.model if local_llm else None)
    from .experience import ExperienceRuntime
    application.experience = ExperienceRuntime(application, components, secrets)
    from .notification_runtime import NotificationRuntime
    from .setup_runtime import SetupRuntime
    components.site.setup_page.runtime = SetupRuntime(application, components.site, secrets)
    from .diagnostics import DiagnosticResult, error_code
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
    notifications = NotificationRuntime(application, components.site)
    application.experience.notifications = notifications
    components.site.notification_runtime = notifications
    application.notifications = notifications


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
) -> Iterator[Application]:
    """Construct adapters and close every successfully constructed resource."""
    jev_prompts = None
    if use_jev_relevance and local_llm is None and not access_diagnostics:
        jev_prompts = load_relevance_prompts(base_directory)
        fingerprint = relevance_fingerprint(fingerprint, jev_prompts)
    with ExitStack() as stack:
        data = _state_directory(settings, base_directory)
        store = stack.enter_context(JsonStore(data))
        sender_store = JsonStore(base_directory)
        if logger is None or access_diagnostics:
            logger = build_logger(
                settings, secrets, base_directory,
                access_diagnostics=access_diagnostics,
            )
        _attach_metrics(logger, settings, base_directory, data, store, local_llm)
        stop_event = Event()
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
        openrouter = _build_llm(settings, secrets, local_llm, llm_budget, logger, stack)
        telegram = _build_telegram(settings, secrets, policy, logger, stack)
        analyzer = _build_analyzer(settings, secrets, prompts, openrouter, jev_prompts, llm_budget, stop_event, stack)
        from .target_profiles import build_profile_writers
        factory = build_profile_writers if settings.target_profiles else build_writers
        built = factory(settings, secrets, base_directory, policy=policy, logger=logger,
                        calendar_matcher=analyzer.calendar_duplicate)
        stack.callback(built.close)
        assert logger.metrics is not None  # _attach_metrics above always sets the recorder
        logger.metrics.write_services = provider_services(settings.targets)
        logger.metrics.mailbox_numbers = {
            mailbox_account_id(source.mailbox, secrets.imap_credentials(source.mailbox.id)): source.mailbox.id
            for source in sources}
        todoist, calendar = built.tasks, built.calendar
        writers = built.slots
        web_enabled = settings.web.enabled and not access_diagnostics
        dialog = _build_dialog(settings, store, telegram, logger, writers, analyzer, web_enabled)
        orchestrator = _build_orchestrator(settings, prompts, topics, fingerprint, jev_prompts, store, sender_store,
                                           logger, analyzer, dialog, writers, access_diagnostics)
        dialog.relevance_handler = orchestrator
        iserv = _build_iserv(settings, secrets, stack)
        if len(sources) + len(iserv) > 1:
            dialog.presenter.mailbox_of = _mailbox_labels(
                store, sources, {source.reader.account_id: source.account.label for source in iserv})
        orchestrator.original_attachments = settings.attachments
        orchestrator.stop_event = stop_event
        application = Application(settings, store, logger, imap, openrouter, analyzer, telegram, todoist, calendar,
                                  orchestrator, stop_event, dialog, sender_store, sources=sources)
        numbers = {mailbox_account_id(source.mailbox, secrets.imap_credentials(source.mailbox.id)): source.mailbox.id
                   for source in sources}
        # IServ letters use the settings of the mailbox their account names.
        numbers |= {source.reader.account_id: source.account.mailbox for source in iserv}
        orchestrator.configure_mailboxes(settings, prompts, numbers, jev_prompts)
        if iserv:
            from .iserv import IServRunService
            orchestrator.always_relevant = frozenset(source.reader.account_id for source in iserv)
            application.iserv = IServRunService(store, logger, iserv, application._process_mail, stop_event)
            application.mailbox.resume_readers = application.iserv.readers()
        application.profile_writers = built
        from . import profile_binding
        dialog.decision_service.profile_available = lambda proposal: profile_binding.available(
            application.settings, writers, proposal)
        dialog.presenter.profile_of = lambda proposal: profile_binding.label(application.settings, proposal)
        dialog.presenter.profile_available = dialog.decision_service.profile_available
        dialog.presenter.profiles_status = lambda: profile_binding.summary(application.settings, writers)
        dialog.presenter.retarget_choices = lambda proposal: profile_binding.choices(application.settings, proposal)
        if web_enabled:
            _attach_web(application, settings, secrets, prompts, jev_prompts, local_llm, base_directory, sender_store)
        elif not access_diagnostics:
            from .notification_runtime import NotificationRuntime
            application.notifications = NotificationRuntime.without_web(application)
        yield application
