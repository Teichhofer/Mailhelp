"""7.2.4: read the data sources shared with a Notion connection and the schema of one of them.

Only reads: Mailhelp never creates a data source, a property or a status option. A listing that
cannot be read completely is refused instead of offering a partial choice.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from ..config.loader import _dotenv
from ..external.notion import API, VERSION, DataSource, _plain
from ..external.notion_oauth import NotionTokenFile, token_path
from ..proposals.target_profiles import secret_name

MAX_PAGES = 20


def notion_token(directory: Path, profile: int) -> str:
    """The internal connection's token, else the access token of the saved OAuth grant; empty if neither."""
    env = {**_dotenv(directory / ".env"), **os.environ}
    token = env.get("NOTION_TOKEN" if profile == 1 else secret_name("NOTION_TOKEN", profile), "")
    grant = None if token else NotionTokenFile(token_path(directory, profile)).load()
    return token or (grant.access_token if grant is not None else "")


def _client(token: str, transport: httpx.BaseTransport | None) -> httpx.Client:
    if not token:
        raise ValueError("Notion-Token fehlt.")
    return httpx.Client(base_url=API, timeout=15, transport=transport, trust_env=False, follow_redirects=False,
                        headers={"Authorization": f"Bearer {token}", "Notion-Version": VERSION})


def data_sources(token: str, transport: httpx.BaseTransport | None = None) -> list[tuple[str, str]]:
    """Every data source shared with the connection as (id, title), read over all pages."""
    with _client(token, transport) as client:
        choices: list[tuple[str, str]] = []
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            body: dict[str, Any] = {"filter": {"property": "object", "value": "data_source"}, "page_size": 100,
                                    **({"start_cursor": cursor} if cursor else {})}
            response = client.post("/search", json=body)
            response.raise_for_status()
            page = response.json()
            for item in page["results"]:
                if not isinstance(item["id"], str) or not item["id"]:
                    raise ValueError("Ungültige Datenquellenliste.")
                choices.append((item["id"], _plain(item, "title") or item["id"]))
            if not page["has_more"]:
                return choices
            cursor = page["next_cursor"]
            if not isinstance(cursor, str):
                raise ValueError("Ungültige Datenquellenliste.")
        raise ValueError("Datenquellenliste unvollständig.")


def schema(token: str, source: str, transport: httpx.BaseTransport | None = None) -> DataSource:
    """The properties of *source*, read freshly."""
    with _client(token, transport) as client:
        response = client.get(f"/data_sources/{quote(source, safe='')}")
        response.raise_for_status()
        return DataSource.model_validate(response.json())
