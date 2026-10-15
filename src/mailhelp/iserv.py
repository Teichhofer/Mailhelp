"""IServ parent letters as an always relevant mail source (3.3.7).

IServ offers no documented API for parent letters.  Like a browser, the reader signs in to the
web interface with a cookie session and reads the letter overview, the letter pages and their
attachments.  Each letter becomes an ordinary MIME message, so the rest of Mailhelp (attachments,
proposals, archive, retention) treats it like a mail; only the relevance check is skipped.

Pages and attachments are untrusted input.  Requests never leave the configured HTTPS origin, the
password is only sent in the sign-in form, and neither URLs (they may carry short-lived sign-in
codes) nor provider texts are logged.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from email.headerregistry import Address
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime
from html.parser import HTMLParser
from threading import Event
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

import httpx
from pydantic import Field

from .config import ImapCredentials, IServAccountSettings
from .domain._base import StrictModel
from .imap import FetchedMail
from .logging import EventLogger
from .orchestrator import ProcessingOutcome, ProcessingResult
from .storage import JsonStore

FOLDER = "Elternbriefe"
UIDVALIDITY = 1
INDEX_PATH = "iserv/parentletter/parent/index"
TIMEOUT_SECONDS = 45.0
MAX_REDIRECTS = 15
_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track",
                   "wbr"})
_PUBLISHED = re.compile(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}")


class IServError(RuntimeError):
    """A sign-in, page or attachment problem; the message never contains URLs or provider text."""


@dataclass
class Node:
    """A minimal, tolerant HTML element tree built with the standard library parser."""

    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[Node | str] = field(default_factory=list)
    parent: Node | None = None

    def elements(self) -> Iterator[Node]:
        """Every element below this one, in document order."""
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.elements()

    def find_all(self, tag: str, **attrs: str) -> list[Node]:
        return [node for node in self.elements()
                if node.tag == tag and all(node.attrs.get(key) == value for key, value in attrs.items())]

    def text(self, separator: str = " ") -> str:
        """The stripped text pieces, joined like BeautifulSoup's ``get_text(separator, strip=True)``."""
        pieces: list[str] = []

        def collect(node: Node) -> None:
            for child in node.children:
                if isinstance(child, str):
                    if child.strip():
                        pieces.append(child.strip())
                elif child.tag not in {"script", "style"}:
                    collect(child)

        collect(self)
        return separator.join(pieces)

    def ancestor(self, tag: str) -> Node | None:
        node = self.parent
        while node is not None and node.tag != tag:
            node = node.parent
        return node

    def has_class(self, name: str) -> bool:
        return name in self.attrs.get("class", "").split()


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self._current = self.root

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, {name: value or "" for name, value in attrs}, parent=self._current)
        self._current.children.append(node)
        if tag not in _VOID:
            self._current = node

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._current.children.append(Node(tag, {name: value or "" for name, value in attrs}, parent=self._current))

    def handle_endtag(self, tag: str) -> None:
        # Close the nearest open element of this name; a stray end tag is ignored.
        node: Node | None = self._current
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self._current = node.parent

    def handle_data(self, data: str) -> None:
        self._current.children.append(data)


def parse_html(content: bytes | str) -> Node:
    builder = _TreeBuilder()
    builder.feed(content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content)
    builder.close()
    return builder.root


def _password_input(page: Node) -> Node | None:
    return next((node for node in page.find_all("input") if node.attrs.get("type", "").lower() == "password"), None)


def _is_html(response: httpx.Response) -> bool:
    return "text/html" in response.headers.get("Content-Type", "")


@dataclass(frozen=True)
class Letter:
    """One parent letter of the overview; ``key`` holds the two ids of its page address."""

    key: str
    title: str
    child: str
    published: datetime
    url: str

    @property
    def uid(self) -> int:
        """A stable positive number standing in for an IMAP UID."""
        return int(hashlib.sha256(self.key.encode()).hexdigest()[:12], 16)


def account_id(server: str, username: str) -> str:
    """A stable, non-secret identity; it cannot collide with an IMAP account id of the same user."""
    normalized = f"iserv\n{server.lower()}\n{username.strip().lower()}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def _one_line(value: str, limit: int = 200) -> str:
    return " ".join(value.split())[:limit] or "Elternbrief"


class IServReader:
    """Sign in to one IServ account and read its parent letters."""

    def __init__(self, account: IServAccountSettings, credentials: ImapCredentials, timezone: str, max_bytes: int,
                 *, transport: httpx.BaseTransport | None = None):
        self.account, self.timezone, self.max_bytes = account, ZoneInfo(timezone), max_bytes
        self._username, self._password = credentials.username, credentials.password
        self.base = account.server + "/"
        self.origin = urlsplit(self.base)[:2]
        self.account_id = account_id(account.server, credentials.username)
        self.last_uidvalidity = UIDVALIDITY
        self.client = httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False, transport=transport,
                                   headers={"User-Agent": "Mailhelp-IServ-Elternbriefe"})

    def close(self) -> None:
        self.client.close()

    def _checked(self, url: str, relative_to: str | None = None) -> str:
        target = urljoin(relative_to or self.base, url)
        parts = urlsplit(target)
        if parts[:2] != self.origin or parts.username or parts.password:
            raise IServError("IServ leitete auf einen anderen Server um; Abruf abgebrochen")
        return target

    def _request(self, method: str, url: str, data: dict[str, str] | None = None) -> httpx.Response:
        """Follow redirects and meta refreshes by hand, each checked before cookies or data go along."""
        for _ in range(MAX_REDIRECTS):
            url = self._checked(url)
            response = self.client.request(method, url, data=data)
            if response.is_redirect:
                url = self._checked(response.headers.get("Location", ""), str(response.url))
                if response.status_code in (301, 302, 303):
                    method, data = "GET", None
                continue
            if response.status_code >= 400:
                raise IServError(f"IServ antwortete mit HTTP-Status {response.status_code}")
            if len(response.content) > self.max_bytes:
                raise IServError("IServ-Antwort überschreitet limits.max_mail_bytes")
            refresh = self._refresh_target(response)
            if refresh is not None:
                url, method, data = self._checked(refresh, str(response.url)), "GET", None
                continue
            return response
        raise IServError("Zu viele Weiterleitungen beim IServ-Abruf")

    @staticmethod
    def _refresh_target(response: httpx.Response) -> str | None:
        if not _is_html(response):
            return None
        for meta in parse_html(response.content).find_all("meta"):
            if meta.attrs.get("http-equiv", "").lower() == "refresh":
                match = re.search(r"url\s*=\s*(.+)", meta.attrs.get("content", ""), re.IGNORECASE)
                if match:
                    return match[1].strip().strip("\"'")
        return None

    def _sign_in(self, response: httpx.Response, page: Node) -> None:
        password = _password_input(page)
        assert password is not None
        form = password.ancestor("form")
        username = next((node for node in form.find_all("input") if node.attrs.get("name") == "_username"),
                        None) if form is not None else None
        if form is None or username is None or not password.attrs.get("name"):
            raise IServError("Unbekanntes IServ-Anmeldeformular")
        data = {node.attrs["name"]: node.attrs.get("value", "") for node in form.find_all("input")
                if node.attrs.get("name") and node.attrs.get("type", "").lower() == "hidden"}
        data[username.attrs["name"]] = self._username
        data[password.attrs["name"]] = self._password.get_secret_value()
        self._request("POST", self._checked(form.attrs.get("action") or str(response.url), str(response.url)), data)

    def _index(self) -> tuple[httpx.Response, Node]:
        """The letter overview; signs in first when the session is new or has expired."""
        target = self._checked(INDEX_PATH)
        response = self._request("GET", target)
        page = parse_html(response.content)
        if _password_input(page) is not None:
            self._sign_in(response, page)
            # Only access to the protected module proves the sign-in.
            response = self._request("GET", target)
            page = parse_html(response.content)
            if _password_input(page) is not None:
                raise IServError("IServ-Anmeldung fehlgeschlagen oder weiterer Anmeldeschritt erforderlich")
        if not page.find_all("table", id="crud-table"):
            raise IServError("Kein Elternbrief-Postfach gefunden; Berechtigung oder Seitenstruktur prüfen")
        return response, page

    def check_access(self) -> None:
        self._index()

    def letters(self) -> list[Letter]:
        """Every letter of the overview, oldest first."""
        response, page = self._index()
        table = page.find_all("table", id="crud-table")[0]
        letters: dict[str, Letter] = {}
        for row in table.find_all("tr"):
            link = next((node for node in row.find_all("a")
                         if "/parentletter/parent/show/" in node.attrs.get("href", "")), None)
            if link is None:
                continue
            url = self._checked(link.attrs["href"], str(response.url))
            key = "_".join(urlsplit(url).path.rstrip("/").split("/")[-2:])
            if key in letters:
                continue
            cells = [child for child in row.children if isinstance(child, Node) and child.tag == "td"]
            published = next((cell.text() for cell in cells if _PUBLISHED.fullmatch(cell.text())), None)
            if published is None:
                raise IServError("Veröffentlichungsdatum eines Elternbriefs nicht erkannt")
            when = datetime.strptime(published, "%d.%m.%Y %H:%M").replace(tzinfo=self.timezone)
            letters[key] = Letter(key=key, title=_one_line(link.text()),
                                  child=cells[2].text() if len(cells) > 2 else "", published=when, url=url)
        # Never process only part of the overview without noticing.
        count = re.search(r"von\s+([\d.]+)\s+Eintr", page.text())
        if count and int(count[1].replace(".", "")) != len(letters):
            raise IServError("IServ verteilt die Elternbriefe auf mehrere Seiten; das wird noch nicht unterstützt")
        return sorted(letters.values(), key=lambda letter: (letter.published, letter.key))

    def fetch(self, letter: Letter) -> FetchedMail:
        """The letter as a MIME message with its text and attachments."""
        response = self._request("GET", letter.url)
        page = parse_html(response.content)
        if _password_input(page) is not None:
            raise IServError("IServ-Sitzung abgelaufen")
        body = next((node for node in page.elements() if node.has_class("parent-letter-body")), None)
        if body is None:
            raise IServError("Inhaltsbereich des Elternbriefs nicht gefunden")
        attachments = [(node.text(), self._checked(node.attrs["href"], str(response.url)))
                       for node in page.find_all("a") if "/parentletter/attachment/" in node.attrs.get("href", "")]
        message = EmailMessage(policy=SMTP)
        host = urlsplit(self.base).hostname or "iserv"
        message["From"] = Address(display_name=self.account.label, addr_spec=f"elternbriefe@{host}")
        message["Subject"] = letter.title
        message["Date"] = format_datetime(letter.published)
        message["Message-ID"] = f"<{re.sub(r'[^A-Za-z0-9._-]', '-', letter.key)}.parentletter@{host}>"
        intro = f"Elternbrief vom {letter.published:%d.%m.%Y %H:%M}"
        message.set_content(intro + (f"\nKind: {letter.child}" if letter.child else "") + "\n\n" + body.text("\n"))
        total = len(response.content)
        for number, (name, url) in enumerate(attachments, 1):
            data = self._request("GET", url)
            if _is_html(data):
                raise IServError("IServ lieferte anstelle eines Anhangs eine HTML-Seite")
            total += len(data.content)
            if total > self.max_bytes:
                raise IServError("Elternbrief mit Anhängen überschreitet limits.max_mail_bytes")
            maintype, _, subtype = (data.headers.get("Content-Type", "application/octet-stream")
                                    .split(";")[0].strip().lower().partition("/"))
            if not maintype or not subtype or maintype in {"text", "multipart", "message"}:
                maintype, subtype = "application", "octet-stream"
            message.add_attachment(data.content, maintype=maintype, subtype=subtype,
                                   filename=_one_line(name, 120) if name.strip() else f"anhang-{number}")
        return FetchedMail(FOLDER, UIDVALIDITY, letter.uid, message.as_bytes(), self.account_id, letter.published)

    def fetch_uid(self, folder: str, uid: int, uidvalidity: int) -> FetchedMail:
        """A letter again by its stand-in UID, for the resumption of unfinished processing."""
        letter = next((item for item in self.letters() if item.uid == uid), None)
        if folder != FOLDER or uidvalidity != UIDVALIDITY or letter is None:
            raise IServError("Elternbrief ist in IServ nicht mehr vorhanden")
        return self.fetch(letter)


class IServState(StrictModel):
    schema_version: Literal[1] = 1
    # Keys of letters whose processing produced a durable mail state.
    processed: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class IServSource:
    account: IServAccountSettings
    reader: IServReader
    # Letters published earlier are not processed.
    start: datetime | None


def state_name(account: str) -> str:
    return f"iserv-{account}"


class IServRunService:
    """Process new parent letters of every IServ account, oldest first."""

    def __init__(self, store: JsonStore, logger: EventLogger, sources: list[IServSource],
                 process_mail: Callable[[FetchedMail], ProcessingResult], stop_event: Event):
        self.store, self.logger, self.sources = store, logger, sources
        self.process_mail, self.stop_event = process_mail, stop_event

    def readers(self) -> dict[str, Any]:
        """Readers by account id, so unfinished letters resume like unfinished mail."""
        return {source.reader.account_id: source.reader for source in self.sources}

    def poll(self, limit: int | None = None) -> list[ProcessingResult]:
        results: list[ProcessingResult] = []
        for source in self.sources:
            if self.stop_event.is_set() or (limit is not None and len(results) >= limit):
                break
            try:
                self._poll_source(source, limit, results)
            except Exception as exc:
                # One unreachable school must not stop the others or the mail cycle.
                self.logger.event("ERROR", "iserv", "poll_failed", account=source.account.id,
                                  error=str(exc) if isinstance(exc, IServError) else type(exc).__name__)
        return results

    def _poll_source(self, source: IServSource, limit: int | None, results: list[ProcessingResult]) -> None:
        name = state_name(source.reader.account_id)
        state = self.store.load_model(name, IServState, IServState())
        letters = source.reader.letters()
        self.logger.event("INFO", "iserv", "letters_listed", account=source.account.id, count=len(letters))
        for letter in letters:
            if letter.key in state.processed or (source.start is not None and letter.published < source.start):
                continue
            if self.stop_event.is_set() or (limit is not None and len(results) >= limit):
                return
            result = self.process_mail(source.reader.fetch(letter))
            results.append(result)
            if result.outcome is ProcessingOutcome.FAILED:
                # Not recorded: the durable failure state is retried like a failed mail.
                self.logger.event("ERROR", "iserv", "letter_failed", account=source.account.id,
                                  mail_id=result.state.get("id"))
                continue
            state.processed.append(letter.key)
            self.store.save(name, state.model_dump(mode="json"))


__all__ = ["FOLDER", "IServError", "IServReader", "IServRunService", "IServSource", "IServState", "Letter",
           "Node", "UIDVALIDITY", "account_id", "parse_html", "state_name"]
