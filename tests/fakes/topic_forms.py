"""5.7.2: the two web steps of a topic change (preview, then explicit confirmation)."""
from __future__ import annotations

import re
from html import unescape

FORM = re.compile(r'<form method="post" action="([^"]+)"[^>]*>(.*?)</form>', re.S)
HIDDEN = re.compile(r'<input type="hidden" name="([^"]+)" value="([^"]*)">')


def hidden(html: str, action: str) -> dict[str, str]:
    """The hidden fields of the first form posting to *action*."""
    for target, block in FORM.findall(html):
        if target == action:
            return {name: unescape(value) for name, value in HIDDEN.findall(block)}
    raise AssertionError(f"Formular {action} fehlt")


def preview(web, route: str, **values: str):
    """Open *route*, fill the editor and ask for the preview; returns the response."""
    form = hidden(web.browser.request("GET", route).body.decode(), "/themen/pruefen")
    current = {"name": "", "description": "", "examples": "", "exclusions": "", "enabled": "yes"}
    return web.browser.request("POST", "/themen/pruefen", {**form, **current, **values})


def confirmation(response) -> dict[str, str]:
    """The confirmation fields of a preview page, already confirmed."""
    assert response.status == 200, response.body.decode()[-400:]
    return {**hidden(response.body.decode(), "/themen/speichern"), "confirm": "yes"}


def save(web, route: str, **values: str):
    """Preview and confirm; returns the confirmation response (a redirect to the action)."""
    return web.browser.request("POST", "/themen/speichern", confirmation(preview(web, route, **values)))
