"""Bounded, read-only setup probes; provider response bodies never reach error pages.

6.1: every failure is raised as :class:`SetupProblem` with a catalogue code (setup_messages), so the
browser can say what is wrong and what to do – without any text from a server response.
"""
from __future__ import annotations

import imaplib
import socket
import ssl
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from ..config import PromptConfig, Secrets, Settings
from ..config.loader import imap_secret_values, provider_secret_names
from ..config.models import ImapCredentials, MailboxSettings
from ..external.contracts import (
    AuthenticationError,
    CalendarAccessError,
    ExternalRefused,
    ExternalUnavailable,
    OAuthTokenError,
)
from ..external.providers import build_writers
from ..llm.ollama import LocalLlm, parse_address
from ..mailbox.imap import FolderNotReadable, ImapLoginRejected, ImapReader, StartTlsFailed, reader_arguments
from ..proposals.target_profiles import PROVIDER_FIELDS
from .setup_messages import SetupProblem, classify

TIMEOUT = 15


def setup_secrets(settings: Settings, env: dict[str, str]) -> Secrets:
    imap, missing = imap_secret_values(settings.imap, env)
    required = provider_secret_names(settings.targets)
    if settings.llm.provider == "openrouter":
        required.append("OPENROUTER_API_KEY")
    missing += [name for name in required if not env.get(name)]
    if missing:
        raise SetupProblem("target.secret_missing", detail=", ".join(missing))
    values = {name: env[name.upper()] for name in PROVIDER_FIELDS if env.get(name.upper())}
    return Secrets(imap=imap, openrouter_api_key=env.get("OPENROUTER_API_KEY", ""), **values)


def _mismatch(mailbox: MailboxSettings) -> bool:
    """The well-known pairs: 993 speaks TLS from the start, 143 plain text (optionally STARTTLS)."""
    return (mailbox.port == 993 and mailbox.connection_mode != "ssl") or (
        mailbox.port == 143 and mailbox.connection_mode == "ssl")


def _connect(mailbox: MailboxSettings, credentials: ImapCredentials,
             reader: Callable[..., ImapReader]) -> ImapReader:
    """Open and log in; every failure becomes the most specific catalogue code."""
    address, options = reader_arguments(mailbox, credentials)
    try:
        return reader(*address, timeout=TIMEOUT, **options)
    except ImapLoginRejected:
        raise SetupProblem("imap.auth_failed") from None
    except StartTlsFailed:
        raise SetupProblem("imap.tls_mismatch") from None
    except ssl.SSLCertVerificationError:
        raise SetupProblem("imap.certificate") from None
    except ssl.SSLError:
        raise SetupProblem("imap.tls_mismatch") from None
    except socket.gaierror:
        raise SetupProblem("imap.host_unknown") from None
    except imaplib.IMAP4.error if mailbox.connection_mode == "starttls" else ():
        # imaplib refuses STARTTLS with a plain IMAP4.error when the server does not offer it.
        raise SetupProblem("imap.tls_mismatch") from None
    except (TimeoutError, imaplib.IMAP4.error, EOFError, ConnectionResetError):
        # A TLS greeting on a plain port (or the reverse) looks like silence or garbage.
        raise SetupProblem("imap.tls_mismatch" if _mismatch(mailbox) else "imap.unreachable") from None
    except OSError:
        raise SetupProblem("imap.unreachable") from None


def _status(response: httpx.Response, codes: dict[int, str], default: str = "llm.service") -> None:
    """Raise the catalogue code of an HTTP error status; the body is never read."""
    if response.status_code >= 400:
        raise SetupProblem(codes.get(response.status_code, default))


class SetupChecks:
    def __init__(self, directory: Path, transport: httpx.BaseTransport | None = None,
                 reader: Callable[..., ImapReader] | None = None):
        self.directory, self.transport, self.reader = directory, transport, reader

    def imap(self, settings: Settings, env: dict[str, str]) -> dict[str, Any]:
        credentials, missing = imap_secret_values(settings.imap, env)
        if missing:
            raise SetupProblem("imap.missing", detail=", ".join(missing))
        mailbox = settings.imap.enabled_mailboxes()[0]
        reader = _connect(mailbox, ImapCredentials.model_validate(credentials[mailbox.id]),
                          self.reader or ImapReader)
        try:
            folders = reader.list_folders()
            names = [folder.name for folder in folders]
            inbox = next((folder.name for folder in folders if folder.role == "inbox"), "INBOX")
            primary = mailbox.primary_folder
            known = primary in names or (primary.upper() == "INBOX" and inbox.upper() == "INBOX")
            if not known:
                raise SetupProblem("imap.folder_missing", detail=", ".join(names[:30]))
            try:
                reader.check_access([primary])
            except FolderNotReadable:
                raise SetupProblem("imap.folder_missing", detail=", ".join(names[:30])) from None
            drafts = next((folder.name for folder in folders if folder.role == "drafts"), "")
            return {"server": f"{mailbox.host}:{mailbox.port} ({mailbox.connection_mode})",
                    "folders": names, "inbox": inbox, "drafts": drafts,
                    "drafts_missing": bool(mailbox.drafts_folder and mailbox.drafts_folder not in names)}
        finally:
            reader.close()

    def llm(self, settings: Settings, env: dict[str, str], prompts: PromptConfig) -> dict[str, Any]:
        try:
            with httpx.Client(transport=self.transport, timeout=TIMEOUT, trust_env=False) as client:
                if settings.llm.provider == "ollama":
                    return self._ollama(client, settings)
                return self._openrouter(client, env, prompts)
        except httpx.TransportError as error:
            if settings.llm.provider == "ollama":
                raise SetupProblem("timeout" if isinstance(error, httpx.TimeoutException)
                                   else "llm.ollama_unreachable") from None
            raise SetupProblem(classify(error)) from None

    @staticmethod
    def _ollama(client: httpx.Client, settings: Settings) -> dict[str, Any]:
        host, port = parse_address(settings.llm.ollama_address)
        response = client.get(LocalLlm(host, port, model="").base_url + "/api/tags")
        _status(response, {}, "llm.ollama_unreachable")
        try:
            names = [item["name"] for item in response.json()["models"]]
        except (ValueError, KeyError, TypeError):
            raise SetupProblem("llm.ollama_unreachable") from None
        if not names or any(not isinstance(name, str) or not name for name in names):
            raise SetupProblem("llm.ollama_empty")
        return {"models": names}

    @staticmethod
    def _openrouter(client: httpx.Client, env: dict[str, str], prompts: PromptConfig) -> dict[str, Any]:
        token = env.get("OPENROUTER_API_KEY", "")
        if not token:
            raise SetupProblem("llm.key_missing")
        headers = {"Authorization": "Bearer " + token}
        refused = {401: "llm.key_invalid", 403: "llm.key_invalid", 402: "llm.no_credit"}
        key = client.get("https://openrouter.ai/api/v1/key", headers=headers)
        _status(key, refused)
        data = key.json()["data"]
        models = client.get("https://openrouter.ai/api/v1/models", headers=headers)
        _status(models, refused)
        available = {model["id"] for model in models.json()["data"]}
        required = {route.model for name in prompts.prompts for route in prompts.resolved_routes(name)[0]}
        if not required <= available:
            raise SetupProblem("llm.model_missing", detail=", ".join(sorted(required - available)))
        credits = client.get("https://openrouter.ai/api/v1/credits", headers=headers)
        balance: float | None = None
        if credits.status_code == 200:
            account = credits.json()["data"]
            balance = float(account["total_credits"]) - float(account["total_usage"])
        elif credits.status_code not in {401, 403}:
            _status(credits, refused)
        remaining = data.get("limit_remaining")
        if remaining is not None and not isinstance(remaining, (int, float)):
            raise SetupProblem("llm.service")
        if remaining is not None and remaining <= 0:
            raise SetupProblem("llm.no_credit")
        return {"models": sorted(required), "balance": balance, "key_remaining": remaining}

    def targets(self, settings: Settings, env: dict[str, str]) -> dict[str, Any]:
        writers = build_writers(settings, setup_secrets(settings, env), self.directory,
                                transport=self.transport, timeout_cap=TIMEOUT)
        try:
            for label, provider, writer in (
                    ("Kalender", settings.targets.calendar_provider, writers.calendar),
                    ("Aufgaben", settings.targets.task_provider, writers.tasks)):
                try:
                    writer.check_access()
                except OAuthTokenError:
                    raise SetupProblem("google.token_expired" if provider == "google" else "target.auth_failed",
                                       detail=f"{label}: {provider}") from None
                except AuthenticationError:
                    raise SetupProblem("target.auth_failed", detail=f"{label}: {provider}") from None
                except CalendarAccessError:
                    raise SetupProblem("target.not_found", detail=f"{label}: {provider}") from None
                except ExternalUnavailable:
                    raise SetupProblem("network", detail=f"{label}: {provider}") from None
                except ExternalRefused:
                    raise SetupProblem("target.permission", detail=f"{label}: {provider}") from None
                except (httpx.HTTPError, OSError) as error:
                    raise SetupProblem(classify(error), detail=f"{label}: {provider}") from None
        finally:
            writers.close()
        return {"ready": True, "calendar": settings.targets.calendar_provider,
                "tasks": settings.targets.task_provider}
