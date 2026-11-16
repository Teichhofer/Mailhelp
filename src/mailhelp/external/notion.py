"""7.2: a Notion data source as a task target (Planung 7.2, 5 and 6).

Mailhelp writes one page per confirmed task into the chosen data source. Every property is
addressed by its id, so a renamed column keeps working; a removed column or a changed type stops
new writes until the mapping is confirmed again. The schema is read again right before every
write. The operation key lives in its own rich-text property and is the only way to find an
unclear write again. Notion promises neither idempotency nor an atomic condition for changes, so
a reconciliation that cannot read every result, or finds the key twice, stays unclear; removing a
page is not offered.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date, datetime
from functools import partial
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import Field, ValidationError

from ..config import NotionProperties
from ..domain.proposal import Proposal, ProposalKind
from ..llm.adapter import RetryPolicy, uncertain_write
from ..logging import EventLogger, NullLogger
from .contracts import (
    AuthenticationError,
    ExternalUncertain,
    IntegrationModel,
    PreparedWrite,
    TargetAccessError,
    TodoistTaskResponse,
    validation_path,
)
from .provider import ProviderWriter
from .verification import EntryRead, task_facts

API = "https://api.notion.com/v1"
# Checked against developers.notion.com on 16 November 2026; pinned, changed only with tests.
VERSION = "2026-03-11"
TEXT_CHUNK = 2000
MAX_PAGES = 100
# A field and the property types it may be mapped to.
TYPES: dict[str, tuple[str, ...]] = {
    "title": ("title",), "description": ("rich_text",), "due": ("date",), "source": ("url",),
    "operation_key": ("rich_text",), "status": ("status", "select", "checkbox")}
NO_STATUS_NOTE = ("Ohne Statusfeld kann Mailhelp erledigte Notion-Aufgaben nicht erkennen; "
                  "die Liste offener Aufgaben ist dann nicht verlässlich.")


class SchemaProperty(IntegrationModel):
    id: str = Field(min_length=1)
    name: str = ""
    type: str
    status: dict[str, Any] | None = None
    select: dict[str, Any] | None = None


class DataSource(IntegrationModel):
    id: str = Field(min_length=1)
    properties: dict[str, SchemaProperty]


class NotionPage(IntegrationModel):
    id: str = Field(min_length=1)
    url: str | None = None
    in_trash: bool = False
    properties: dict[str, dict[str, Any]] = Field(default_factory=dict)


def options(item: SchemaProperty) -> list[dict[str, Any]]:
    """The options of a status or select property; a checkbox has none."""
    values = (item.status or item.select or {}).get("options", [])
    return [value for value in values if isinstance(value, dict) and isinstance(value.get("id"), str)]


def check_mapping(source: DataSource, fields: NotionProperties, open_status: str,
                  done_statuses: frozenset[str]) -> dict[str, str]:
    """The type of every mapped property; a missing one, a wrong type or a lost option is refused."""
    by_id = {item.id: item for item in source.properties.values()}
    types: dict[str, str] = {}
    for field, property_id in fields.model_dump().items():
        if not property_id:
            continue
        found = by_id.get(property_id)
        if found is None:
            raise TargetAccessError(f"Notion: Eigenschaft für „{field}“ fehlt in der Datenquelle; "
                                    "Zuordnung neu festlegen", "not_found")
        if found.type not in TYPES[field]:
            raise TargetAccessError(f"Notion: Eigenschaft für „{field}“ hat den Typ {found.type}, "
                                    f"erwartet {' oder '.join(TYPES[field])}", "forbidden")
        types[field] = found.type
        ids = {value["id"] for value in options(found)}
        if field == "status" and found.type != "checkbox" and (open_status not in ids or not done_statuses <= ids):
            raise TargetAccessError("Notion: Statusoption nicht mehr vorhanden; Zuordnung neu festlegen", "not_found")
    return types


def _link(value: str | None) -> str | None:
    if value and re.fullmatch(r"https://(www\.)?notion\.so/[^\s<>\"']*", value):
        return value
    return None


def _chunks(text: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": text[start:start + TEXT_CHUNK]}}
            for start in range(0, len(text), TEXT_CHUNK)]


def _plain(value: dict[str, Any], kind: str) -> str:
    return "".join(str(part.get("plain_text") or (part.get("text") or {}).get("content") or "")
                   for part in value.get(kind) or [])


def _moment(value: str | None) -> date | datetime | None:
    if not value:
        return None
    return date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value)


class NotionTasks(ProviderWriter):
    """Pages in one Notion data source, mapped by property ids."""

    service, label, role = "notion", "Notion", "tasks"

    def __init__(self, token: str, target: str, properties: NotionProperties, open_status: str = "",
                 done_statuses: tuple[str, ...] = (), timeout: float = 30,
                 transport: httpx.BaseTransport | None = None, policy: RetryPolicy | None = None,
                 logger: EventLogger | None = None) -> None:
        self.target, self.fields, self.open_status = target, properties, open_status
        self.done_statuses = frozenset(done_statuses)
        self.client = httpx.Client(base_url=API, timeout=timeout, transport=transport, follow_redirects=False,
                                   headers={"Authorization": f"Bearer {token}", "Notion-Version": VERSION})
        self.policy = policy or RetryPolicy(0, 0, 0, lambda _delay: False)
        self.logger = logger or NullLogger()
        self._read_cache: dict[tuple[Any, ...], tuple[float, Any]] = {}

    def close(self) -> None:
        self.client.close()

    # -- transport -------------------------------------------------------------------------------
    def _send(self, method: str, url: str, *, body: dict[str, Any] | None = None, key: str | None = None,
              allowed: frozenset[int] = frozenset()) -> httpx.Response:
        self.logger.event("DEBUG", self.service, "http_request", method=method, url=url, call_id=key)
        response = self.client.request(method, url, json=body)
        if response.status_code in allowed:
            return response
        code = self._code(response)
        if response.status_code == 401:
            self.logger.event("ERROR", self.service, "authentication_failed", status=401)
            raise AuthenticationError(f"{self.label}: Notion hat das Token abgelehnt; Verbindung erneuern")
        if response.status_code in {403, 404}:
            self.logger.event("ERROR", self.service, "target_access_failed", status=response.status_code, code=code)
            raise TargetAccessError(f"{self.label}: Datenquelle nicht gefunden oder nicht für die Verbindung "
                                    "freigegeben", "forbidden" if response.status_code == 403 else "not_found")
        if response.status_code == 529:
            # Overloaded: retried like 503; a write stays unclear instead of counting as refused.
            raise httpx.HTTPStatusError("overloaded", request=response.request,
                                        response=httpx.Response(503, headers=response.headers,
                                                                request=response.request))
        response.raise_for_status()
        return response

    @staticmethod
    def _code(response: httpx.Response) -> str:
        try:
            body = response.json()
            return str(body.get("code") or "") if isinstance(body, dict) else ""
        except ValueError:
            return ""

    def _json(self, response: httpx.Response) -> dict[str, Any]:
        try:
            value = response.json()
        except ValueError as exc:
            raise ValueError(f"{self.label}: ungültige Antwort am Schlüsselpfad <json>") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{self.label}: ungültige Antwort am Schlüsselpfad <root>")
        return value

    def _model[M: IntegrationModel](self, model: type[M], value: Any) -> M:
        try:
            return model.model_validate(value)
        except ValidationError as exc:
            raise ValueError(f"{self.label}: ungültige Antwort am Schlüsselpfad {validation_path(exc)}") from exc

    # -- schema ----------------------------------------------------------------------------------
    def _source(self) -> DataSource:
        url = f"/data_sources/{quote(self.target, safe='')}"
        return self._model(DataSource, self._json(self.policy.run(partial(self._send, "GET", url))))

    def check_schema(self, source: DataSource) -> dict[str, str]:
        """The type of every mapped property; a missing one or a wrong type stops new writes."""
        return check_mapping(source, self.fields, self.open_status, self.done_statuses)

    def check_access(self) -> None:
        self.check_schema(self._source())

    def account_binding(self) -> str:
        """The data source's own id as Notion returns it."""
        return self._source().id

    # -- queries ---------------------------------------------------------------------------------
    def _query(self, body: dict[str, Any]) -> Iterator[NotionPage]:
        cursor: str | None = None
        url = f"/data_sources/{quote(self.target, safe='')}/query"
        for _page in range(MAX_PAGES):
            request = {**body, "page_size": 100, **({"start_cursor": cursor} if cursor else {})}
            page = self._json(self.policy.run(partial(self._send, "POST", url, body=request)))
            results, more, cursor = page.get("results"), page.get("has_more"), page.get("next_cursor")
            status = (page.get("request_status") or {}).get("type", "complete")
            if not isinstance(results, list) or not isinstance(more, bool) or (more and not isinstance(cursor, str)):
                raise ValueError(f"{self.label}: ungültige Antwort am Schlüsselpfad next_cursor")
            if status != "complete":
                raise ExternalUncertain(f"{self.label}: Abfrage unvollständig")
            yield from (self._model(NotionPage, item) for item in results)
            if not more:
                return
        raise ExternalUncertain(f"{self.label}: Datenquelle zu groß, um sie vollständig zu lesen")

    def reconcile(self, key: str) -> dict[str, Any] | None:
        """The page carrying *key*, also archived; two pages are a conflict, never a reason to write."""
        self.logger.event("INFO", self.service, "reconcile_started", call_id=key)
        filter_ = {"property": self.fields.operation_key, "rich_text": {"equals": key}}
        found = [page for archived in (False, True)
                 for page in self._query({"filter": filter_, "is_archived": archived})]
        if len(found) > 1:
            self.logger.event("ERROR", self.service, "reconcile_conflict", call_id=key, matches=len(found))
            raise ExternalUncertain(f"{self.label}: Vorgang mehrfach gefunden; bitte in Notion prüfen")
        return None if not found else {"id": found[0].id, "url": _link(found[0].url)}

    # -- writing ---------------------------------------------------------------------------------
    def properties(self, proposal: Proposal, key: str, types: dict[str, str]) -> dict[str, Any]:
        fields = self.fields
        values: dict[str, Any] = {
            fields.title: {"title": _chunks(proposal.title)},
            fields.description: {"rich_text": _chunks(proposal.description)},
            fields.operation_key: {"rich_text": _chunks(key)},
            fields.due: {"date": None if proposal.due is None else {"start": proposal.due.isoformat()}},
            fields.source: {"url": proposal.mail_link if proposal.mail_link and
                            proposal.mail_link.startswith("https://") else None},
        }
        if fields.status:
            kind = types["status"]
            values[fields.status] = ({"checkbox": False} if kind == "checkbox"
                                     else {kind: {"id": self.open_status}})
        return values

    def _prepare(self, proposal: Proposal, key: str) -> PreparedWrite:
        if proposal.kind != ProposalKind.TASK:
            raise ValueError(f"{self.label} akzeptiert nur Aufgaben")
        # Read right before the write: a schema changed since the confirmation stops it here.
        types = self.check_schema(self._source())
        body = {"parent": {"type": "data_source_id", "data_source_id": self.target},
                "properties": self.properties(proposal, key, types)}

        def create() -> dict[str, Any]:
            page = self._model(NotionPage, self._json(uncertain_write(
                lambda: self._send("POST", "/pages", body=body, key=key))))
            return {"id": page.id, "url": _link(page.url)}
        return PreparedWrite(lambda: self._logged(proposal, key, create), expected=self.expected_facts(proposal, key))

    def expected_facts(self, proposal: Proposal, key: str) -> dict[str, Any] | None:
        if proposal.kind != ProposalKind.TASK:
            return None
        return task_facts(proposal.title, proposal.description, proposal.due, self.target)

    # -- reading ---------------------------------------------------------------------------------
    def _value(self, page: NotionPage, property_id: str) -> dict[str, Any]:
        return next((value for value in page.properties.values() if value.get("id") == property_id), {})

    def _completed(self, page: NotionPage) -> bool:
        if not self.fields.status:
            return False
        value = self._value(page, self.fields.status)
        if "checkbox" in value:
            return value["checkbox"] is True
        option = value.get("status") or value.get("select") or {}
        return isinstance(option, dict) and option.get("id") in self.done_statuses

    def read_entry(self, external_id: str) -> EntryRead | None:
        """The page read freshly; one in the trash or moved to another data source is gone."""
        response = self._send("GET", f"/pages/{quote(external_id, safe='')}", allowed=frozenset({404}))
        if response.status_code == 404:
            self.check_access()
            return None
        page = self._model(NotionPage, self._json(response))
        if page.in_trash:
            return None
        due = (self._value(page, self.fields.due).get("date") or {}).get("start")
        facts = task_facts(_plain(self._value(page, self.fields.title), "title"),
                           _plain(self._value(page, self.fields.description), "rich_text"), _moment(due), self.target)
        return EntryRead(facts, link=_link(page.url), completed=self._completed(page))

    def fetch_active_tasks(self, *, strict: bool = False) -> list[TodoistTaskResponse]:
        cache_key = (self.service, self.target, "tasks")
        cached = None if strict else self._get_cached(cache_key)
        if cached is not None:
            return cached
        try:
            tasks = [TodoistTaskResponse(
                id=page.id, content=_plain(self._value(page, self.fields.title), "title")[:500],
                description=_plain(self._value(page, self.fields.description), "rich_text")[:4000],
                url=_link(page.url))
                for page in self._query({}) if not page.in_trash and not self._completed(page)]
        except Exception as exc:
            self.logger.event("WARNING", self.service, "fetch_tasks_failed", error=str(exc))
            if strict:
                raise
            return []
        self._set_cached(cache_key, tasks)
        return tasks

    @property
    def limitation(self) -> str | None:
        return None if self.fields.status else NO_STATUS_NOTE

