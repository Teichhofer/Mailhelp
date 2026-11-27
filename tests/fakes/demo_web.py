"""Requests and visitor starts against the demo site (synthetic only)."""
import re
from urllib.parse import urlencode

from mailhelp.web.http import Request

HOST = "localhost:8765"
FORM = "application/x-www-form-urlencoded"


class Log:
    def __init__(self):
        self.events = []

    def event(self, level, area, name, **fields):
        self.events.append(name)


def request(method, path, cookies=None, form=None):
    headers = {"host": HOST}
    if cookies:
        headers["cookie"] = "; ".join(f"{name}={value}" for name, value in cookies.items())
    body = b""
    if form is not None:
        headers["content-type"] = FORM
        body = urlencode(form).encode("utf-8")
    return Request(method, path, headers, body=body)


def cookies_of(response, jar):
    for header in response.cookies:
        name, _, rest = header.partition("=")
        jar[name] = rest.split(";", 1)[0]
    return jar


def open_login(site, jar):
    page = site(request("GET", "/anmelden", jar))
    cookies_of(page, jar)
    text = page.body.decode("utf-8")
    return page, re.search(r'name="csrf" value="([^"]+)"', text).group(1), re.search(r'name="key" value="([^"]+)"',
                                                                                    text).group(1)


def start(site, jar=None):
    jar = {} if jar is None else jar
    _page, csrf, key = open_login(site, jar)
    response = site(request("POST", "/demo/starten", jar, {"csrf": csrf, "key": key}))
    cookies_of(response, jar)
    return response, jar
