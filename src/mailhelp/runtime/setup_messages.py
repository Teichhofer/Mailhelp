"""6.1: check results of the first setup and a fixed catalogue of helpful messages.

Only catalogue texts and harmless facts reach the browser. Exceptions are classified by their type
and structured attributes (HTTP status, socket and TLS error classes, own exception classes) – never
by text from a provider response, which may contain credentials.
"""
from __future__ import annotations

import imaplib
import socket
import ssl
from datetime import UTC, datetime
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field


class Message(BaseModel):
    model_config = ConfigDict(frozen=True)
    cause: str
    steps: tuple[str, ...] = ()
    field: str | None = None


# code -> cause, steps to a solution and the form field concerned.
CATALOGUE: dict[str, Message] = {
    # Step 1 – web access and time zone
    "zone.unknown": Message(cause="Die Zeitzone ist nicht bekannt.", field="timezone", steps=(
        "Schreibweise wie „Europe/Berlin“ oder „Europe/Vienna“ verwenden (englisch, mit Schrägstrich).",)),
    "password.too_short": Message(cause="Das Web-Passwort ist zu kurz.", field="password", steps=(
        "Mindestens 12 Zeichen verwenden; ein Satz aus mehreren Wörtern ist leicht zu merken.",)),
    "password.invalid": Message(cause="Das Web-Passwort enthält Tabulatoren oder Zeilenumbrüche.",
                                field="password", steps=("Nur druckbare Zeichen verwenden.",)),
    "password.missing": Message(cause="Es ist noch kein Web-Passwort gespeichert.", field="password", steps=(
        "Ein Passwort mit mindestens 12 Zeichen eingeben.",)),
    "password.kept": Message(cause="Das gespeicherte Web-Passwort bleibt erhalten."),
    "step1.ok": Message(cause="Zeitzone und Web-Passwort sind in Ordnung."),
    # Step 2 – mailbox
    "imap.missing": Message(cause="Für das Postfach fehlen Angaben.", steps=(
        "Server, Port, Verschlüsselung, Posteingang, Benutzername und Passwort ausfüllen.",)),
    "imap.host_unknown": Message(cause="Der IMAP-Server ist unter diesem Namen nicht bekannt.", field="imap.host",
                                 steps=("Schreibweise prüfen, zum Beispiel „imap.gmx.net“ oder "
                                        "„outlook.office365.com“.",
                                        "Nur den Servernamen eintragen, ohne „https://“ oder Port.")),
    "imap.unreachable": Message(cause="Der IMAP-Server antwortet auf diesem Port nicht.", field="imap.port", steps=(
        "Übliche Ports: 993 mit „SSL“ oder 143 mit „STARTTLS“.",
        "Eine Firewall oder ein Netzwerk ohne Internetzugang kann die Verbindung blockieren.")),
    "imap.tls_mismatch": Message(cause="Port und Verschlüsselung passen nicht zusammen.",
                                 field="imap.connection_mode", steps=(
        "Port 993 erwartet „SSL“, Port 143 erwartet „STARTTLS“.",
        "Die Angaben des Mailanbieters zu IMAP verwenden.")),
    "imap.certificate": Message(cause="Das TLS-Zertifikat des Servers ist nicht gültig.", field="imap.host", steps=(
        "Den Servernamen genau so eintragen, wie ihn der Anbieter angibt.",
        "Datum und Uhrzeit dieses Rechners prüfen.")),
    "imap.auth_failed": Message(cause="Der Server hat die Anmeldung abgelehnt.", field="IMAP_PASSWORD", steps=(
        "Als Benutzername meist die vollständige E-Mail-Adresse verwenden, keinen Alias.",
        "Bei Gmail, Outlook, iCloud, GMX oder Web.de mit Zwei-Faktor-Anmeldung ein App-Passwort erzeugen.",
        "Im Webmail prüfen, ob IMAP für dieses Postfach freigeschaltet ist.")),
    "imap.folder_missing": Message(cause="Der angegebene Posteingang wurde nicht gefunden.",
                                   field="imap.primary_folder", steps=(
        "Einen der gefundenen Ordner wählen; der Posteingang heißt meist „INBOX“.",)),
    "imap.drafts_missing": Message(cause="Der Entwurfsordner wurde nicht gefunden.", field="imap.drafts_folder",
                                   steps=("Den vorgeschlagenen Ordner wählen oder das Feld leer lassen; "
                                          "ohne Entwurfsordner legt Mailhelp keine Antwortentwürfe ab.",)),
    "imap.ok": Message(cause="Das Postfach ist erreichbar und lesbar."),
    # Step 3 – AI provider
    "llm.key_missing": Message(cause="Der OpenRouter-Schlüssel fehlt.", field="OPENROUTER_API_KEY", steps=(
        "Unter openrouter.ai bei „Keys“ einen Schlüssel anlegen und hier einfügen.",)),
    "llm.key_invalid": Message(cause="OpenRouter hat den Schlüssel nicht angenommen.", field="OPENROUTER_API_KEY",
                               steps=("Den Schlüssel vollständig kopieren; er beginnt mit „sk-or-“.",
                                      "Prüfen, ob der Schlüssel widerrufen oder abgelaufen ist.")),
    "llm.no_credit": Message(cause="Für diesen Schlüssel ist kein Guthaben oder Limit mehr übrig.", steps=(
        "Guthaben bei OpenRouter aufladen oder das Limit des Schlüssels erhöhen.",)),
    "llm.model_missing": Message(cause="Mindestens ein konfiguriertes Modell ist bei OpenRouter nicht verfügbar.",
                                 steps=("Die genannten Modelle in prompts.yaml durch verfügbare ersetzen.",)),
    "llm.service": Message(cause="Der KI-Anbieter ist gerade überlastet oder nicht erreichbar.", steps=(
        "Später erneut prüfen; die Eingaben bleiben erhalten.",)),
    "llm.ollama_unreachable": Message(cause="Ollama antwortet unter dieser Adresse nicht.",
                                      field="llm.ollama_address", steps=(
        "Prüfen, ob Ollama läuft („ollama serve“).",
        "Adresse im Format „http://rechner:11434“; aus Docker heraus „http://host.docker.internal:11434“.")),
    "llm.ollama_empty": Message(cause="In Ollama ist noch kein Modell installiert.", field="model", steps=(
        "Ein Modell laden, zum Beispiel „ollama pull qwen3:8b“, und erneut prüfen.",)),
    "llm.ollama_model_missing": Message(cause="Das gewählte Ollama-Modell ist nicht installiert.", field="model",
                                       steps=("Eines der installierten Modelle wählen.",)),
    "llm.ok": Message(cause="Der KI-Anbieter ist erreichbar."),
    # Step 4 – calendar and tasks
    "target.secret_missing": Message(cause="Für ein Ziel fehlen Zugangsdaten.", steps=(
        "Die genannten Felder ausfüllen oder das Ziel abwählen.",)),
    "target.auth_failed": Message(cause="Der Anbieter hat die Zugangsdaten abgelehnt.", steps=(
        "Token oder Passwort neu erzeugen und eintragen.",
        "Bei Google oder Microsoft die Verbindung über „verbinden“ neu herstellen.")),
    "target.not_found": Message(cause="Kalender, Liste oder Projekt wurde nicht gefunden.", steps=(
        "Die Auswahl des Kalenders beziehungsweise Projekts prüfen.",
        "Bei CalDAV die vollständige Kalender-URL eintragen.")),
    "target.permission": Message(cause="Der Zugang hat keine Berechtigung für dieses Ziel.", steps=(
        "Beim Verbinden alle angefragten Berechtigungen erteilen.",)),
    "google.token_expired": Message(cause="Die Google-Freigabe ist abgelaufen oder wurde widerrufen.",
                                    field="GOOGLE_OAUTH_REFRESH_TOKEN", steps=(
        "„Google verbinden“ erneut ausführen.",
        "Solange die Google-App im Testmodus ist, laufen Freigaben nach 7 Tagen ab.")),
    "target.ok": Message(cause="Kalender und Aufgabenziel sind erreichbar."),
    # General causes, used by every step
    "network": Message(cause="Der Dienst ist über das Netzwerk nicht erreichbar.", steps=(
        "Internetverbindung, Proxy und Firewall prüfen.",)),
    "tls": Message(cause="Die verschlüsselte Verbindung kam nicht zustande.", steps=(
        "Datum und Uhrzeit dieses Rechners prüfen.",)),
    "timeout": Message(cause="Die Prüfung hat das Zeitlimit von 15 Sekunden überschritten.", steps=(
        "Verbindung prüfen und erneut versuchen.",)),
    "service": Message(cause="Der Dienst hat mit einem Fehler geantwortet.", steps=("Später erneut prüfen.",)),
    "invalid": Message(cause="Eine Eingabe hat ein ungültiges Format.", steps=(
        "Die markierten Felder korrigieren.",)),
    "limit": Message(cause="Zu viele Prüfungen in kurzer Zeit.", steps=(
        "Eine Minute warten; so werden Kontosperren beim Mailanbieter vermieden.",)),
    "conflict": Message(cause="Die Einrichtung wurde inzwischen geändert.", steps=("Die Seite neu laden.",)),
    "unknown": Message(cause="Unerwarteter Fehler bei der Prüfung.", steps=(
        "Erneut prüfen; bleibt der Fehler, steht die Kennung im Protokoll.",)),
}


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    severity: Literal["error", "warning", "ok"] = "error"
    field: str | None = None
    # Harmless details that belong to the message, e.g. missing field names or model names.
    detail: str = Field(default="", max_length=500)


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step: int
    ok: bool
    findings: list[Finding] = Field(default_factory=list)
    facts: dict[str, str] = Field(default_factory=dict)
    # Lists the form offers as choices after a check, e.g. folders or installed models.
    choices: dict[str, list[str]] = Field(default_factory=dict)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def warnings(self) -> bool:
        return any(item.severity == "warning" for item in self.findings)


def finding(code: str, *, severity: Literal["error", "warning", "ok"] = "error", detail: str = "",
            field: str | None = None) -> Finding:
    """A finding with the catalogue's field unless a more specific one is given."""
    return Finding(code=code, severity=severity, detail=detail, field=field or CATALOGUE[code].field)


class SetupProblem(ValueError):
    """A classified problem of a check; carries only a catalogue code and harmless detail.

    A ValueError, so callers that reject invalid setup input keep working unchanged.
    """

    def __init__(self, code: str, detail: str = "", field: str | None = None):
        super().__init__(code)
        self.code, self.detail, self.field = code, detail, field


def classify(error: BaseException) -> str:
    """A general code for an exception, from its type and structured attributes only."""
    if isinstance(error, SetupProblem):
        return error.code
    if isinstance(error, (httpx.TimeoutException, TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(error, (ssl.SSLError, ssl.CertificateError)):
        return "tls"
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        return {401: "target.auth_failed", 403: "target.permission", 404: "target.not_found"}.get(
            status, "service")
    if isinstance(error, (httpx.TransportError, socket.gaierror, ConnectionError, imaplib.IMAP4.abort)):
        return "network"
    if isinstance(error, OSError):
        return "network"
    return "unknown"


__all__ = ["CATALOGUE", "CheckResult", "Finding", "Message", "SetupProblem", "classify", "finding"]
