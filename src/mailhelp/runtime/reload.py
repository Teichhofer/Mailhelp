"""Prepare and swap complete runtime generations at a mail-cycle boundary."""

from __future__ import annotations

import hashlib
import re
from contextlib import ExitStack
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..config import load_all
from ..configuration import file_hash
from ..models import MailRunState, MailState
from ..state_names import mail_state_names


class ReloadState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    version: int = 0
    status: Literal["idle", "pending", "running", "done", "failed"] = "idle"
    actor: str = ""
    revision: str = ""
    message: str = ""
    operations: dict[str, str] = Field(default_factory=dict)


class ReloadService:
    def __init__(self, app, directory, secrets, local_llm=None, use_jev=True):
        self.current, self.directory, self.secrets = app, directory, secrets
        self.store = app.store
        self.active = lambda actor: actor.startswith("web:") and self.current.web_site.auth.active(
            actor.removeprefix("web:")
        )
        self.local_llm, self.use_jev = local_llm, use_jev
        self.resources = ExitStack()

    def state(self):
        return self.store.load_model("runtime-reload", ReloadState, ReloadState())

    def save(self, state):
        self.store.save("runtime-reload", state.model_dump(mode="json"))

    def revision(self):
        names = (
            "config.yaml",
            "prompts.yaml",
            "topics.yaml",
            "irrelevant_topics.yaml",
            ".env",
            "decisions_prompts.yaml",
        )
        return hashlib.sha256(
            "".join(
                file_hash(self.directory / name) if (self.directory / name).exists() else "missing" for name in names
            ).encode()
        ).hexdigest()

    def request(self, actor, version, key, revision):
        with self.store._thread_lock:
            if not self.active(actor) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", key):
                raise ValueError("Ungültige Sitzung oder Anforderung")
            state = self.state()
            signature = f"{actor}:{version}:{revision}"
            if key in state.operations:
                if state.operations[key] != signature:
                    raise ValueError("Idempotenzkonflikt")
                return
            if version != state.version or revision != self.revision() or state.status in {"pending", "running"}:
                raise ValueError("Stand geändert oder Neuladen läuft")
            state.operations[key] = signature
            state.operations = dict(list(state.operations.items())[-200:])
            state.actor, state.revision, state.status = actor, revision, "pending"
            state.version += 1
            state.message = "Wartet auf den nächsten sicheren Mailzyklus."
            self.save(state)

    def _guard(self, state):
        if not self.active(state.actor) or state.revision != self.revision():
            raise ValueError("Sitzung oder Konfiguration inzwischen geändert")

    @staticmethod
    def helpers(app, start):
        if start:
            app._start_receiver()
            app._start_operator()
            if app.services.oauth is not None:
                app.services.oauth.start_worker()
            if app.services.learning is not None:
                app.services.learning.start()
            if app.experience is not None:
                app.experience.start()
        else:
            if app.services.diagnostics is not None:
                app.services.diagnostics.stop()
            app.services.stop_operator()
            app.services.stop_receiver()
            if app.services.oauth is not None:
                app.services.oauth.stop()
            if app.services.learning is not None:
                app.services.learning.stop()
            if app.experience is not None:
                app.experience.stop()
                app.experience.wait_stopped()

    def _build(self, old, stack):
        from ..llm.ollama import LocalLlm, parse_address
        from .composition import build_application

        settings, secrets, topics, _, prompts, fingerprint = load_all(self.directory)
        # A changed persistence namespace or listening/authentication boundary needs a process restart.
        if (
            settings.data_directory != old.settings.data_directory
            or settings.test_mode != old.settings.test_mode
            or settings.web != old.settings.web
            or secrets.mailhelp_web_secret != self.secrets.mailhelp_web_secret
        ):
            raise ValueError("Datenverzeichnis, Betriebsmodus oder Web-Zugang erfordern einen Neustart")
        local = self.local_llm
        if settings.llm.provider == "ollama":
            if prompts.ollama is None:
                raise ValueError("Ollama-Modell fehlt")
            host, port = parse_address(settings.llm.ollama_address)
            local = LocalLlm(host, port, **prompts.ollama.model_dump())
        new = stack.enter_context(
            build_application(
                settings,
                secrets,
                topics,
                prompts,
                fingerprint,
                self.directory,
                local_llm=local,
                use_jev_relevance=self.use_jev,
                shared_store=old.store,
                shared_stop=old.stop_event,
                reload_service=self,
            )
        )
        if any(type(source.reader).__name__ == "_FailedAccessAdapter" for source in new.sources):
            raise ValueError("Ein neues Postfach ist nicht erreichbar; bisheriger Betrieb bleibt aktiv")
        for client in [new.openrouter, new.telegram, *new._active_writers()]:
            client.check_access()
        return new, secrets

    def advance(self):
        state = self.state()
        if state.status not in {"pending", "running"}:
            return
        old = self.current
        suspended = False
        try:
            self._guard(state)
            pending = [self.store.load_model(name, MailState) for name in mail_state_names(self.store)]
            runs = [self.store.load_model(name, MailRunState) for name in self.store.names("mail-run-")]
            if (any(mail.steps.completion == "pending" or mail.steps.action_detection == "failed" for mail in pending)
                    or any(not run.run_complete for run in runs)):
                state.message = (
                    "Unfertige Mailanalysen zuerst abschließen oder erneut prüfen; bisheriger Betrieb bleibt aktiv."
                )
                self.save(state)
                return
            state.status, state.message = "running", "Neue Verbindungen werden vorbereitet."
            self.save(state)
            old.lifecycle.state = "reloading"
            self.helpers(old, False)
            suspended = True
            with ExitStack() as stack:
                new, secrets = self._build(old, stack)
                new._wait_for_user = old._wait_for_user
                with self.store._thread_lock:
                    self._guard(state)
                    server = old.web
                    assert server is not None and new.web is not None
                    server.replace_handler(new.web.handler)
                    new.web = server
                    self.current, self.secrets = new, secrets
                    self.resources.enter_context(stack.pop_all())
                    state.status, state.message = (
                        "done",
                        "Themen, Prompts, Postfächer, Zugangsdaten und Ziele neu geladen.",
                    )
                    state.version += 1
                    self.save(state)
            try:
                old.resources.close()
            except Exception as exc:
                old.logger.event("WARNING", "reload", "old_cleanup_failed", error_class=type(exc).__name__)
            self.helpers(new, True)
        except Exception as exc:
            # Only fixed messages and exception classes; never credentials or provider text.
            state.status = "failed"
            state.message = ("Neuladen fehlgeschlagen; bisherige Konfiguration bleibt aktiv." if self.current is old
                             else "Neue Konfiguration aktiv; Hintergrunddienst fehlgeschlagen. Dienst neu starten.")
            state.version += 1
            self.save(state)
            old.logger.event("WARNING", "reload", "reload_failed", error_class=type(exc).__name__)
            if self.current is old:
                old.lifecycle.state = "running"
            if self.current is old and suspended:
                self.helpers(old, True)

    def close(self):
        self.resources.close()
