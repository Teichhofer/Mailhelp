"""A small in-memory CalDAV server for the provider tests (synthetic data only)."""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

import httpx

COLLECTION = "https://dav.example.test/remote.php/dav/calendars/anna/personal/"


def multistatus(*responses: str) -> bytes:
    return ('<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            + "".join(responses) + "</d:multistatus>").encode()


def item(href: str, data: str | None) -> str:
    calendar = f"<c:calendar-data>{escape(data)}</c:calendar-data>" if data is not None else ""
    return f"<d:response><d:href>{href}</d:href><d:propstat><d:prop>{calendar}</d:prop></d:propstat></d:response>"


class FakeDav:
    """Resources by absolute URL with ETags; ``fail`` maps a method to a forced answer."""

    def __init__(self, collection: str = COLLECTION, components: tuple[str, ...] = ("VEVENT", "VTODO"),
                 calendar: bool = True):
        self.collection, self.components, self.calendar = collection, components, calendar
        self.resources: dict[str, bytes] = {}
        self.requests: list[httpx.Request] = []
        self.fail: dict[str, Callable[[httpx.Request], httpx.Response]] = {}
        self.etags = True

    def etag(self, url: str) -> str:
        return '"' + hashlib.sha256(self.resources[url]).hexdigest()[:12] + '"'

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method in self.fail:
            return self.fail[request.method](request)
        url = str(request.url)
        if request.method == "PROPFIND":
            kind = "<c:calendar/>" if self.calendar else ""
            comps = "".join(f'<c:comp name="{name}"/>' for name in self.components)
            return httpx.Response(207, content=multistatus(
                f"<d:response><d:href>{urlsplit(self.collection).path}</d:href><d:propstat><d:prop>"
                f"<d:resourcetype><d:collection/>{kind}</d:resourcetype>"
                f"<c:supported-calendar-component-set>{comps}</c:supported-calendar-component-set>"
                "</d:prop></d:propstat></d:response>"))
        if request.method == "REPORT":
            return httpx.Response(207, content=multistatus(*(
                item(urlsplit(url).path, data.decode()) for url, data in self.resources.items())))
        if request.method == "GET":
            if url not in self.resources:
                return httpx.Response(404)
            headers = {"ETag": self.etag(url)} if self.etags else {}
            return httpx.Response(200, content=self.resources[url], headers=headers)
        if request.method == "PUT":
            if request.headers.get("If-None-Match") == "*" and url in self.resources:
                return httpx.Response(412)
            match = request.headers.get("If-Match")
            if match is not None and (url not in self.resources or match != self.etag(url)):
                return httpx.Response(412)
            created = url not in self.resources
            self.resources[url] = request.content
            return httpx.Response(201 if created else 204)
        return httpx.Response(405)
