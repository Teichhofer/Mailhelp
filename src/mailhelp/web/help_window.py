"""Session-owned UI fallback for the non-modal help window; never an authorization token."""
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Literal
from urllib.parse import parse_qs, urlencode, urlsplit

from pydantic import BaseModel, ConfigDict, Field

from ..storage import CorruptState
from .actions import new_key
from .auth import WebSession
from .pages import e, shows_help_button

if TYPE_CHECKING:
    from .help_site import HelpSite


class WindowState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    version: int = Field(default=1, ge=1)
    opened: bool = False
    draft: str = Field(default="", max_length=8000)
    setting: str = Field(default="", max_length=200)
    corner: Literal["top-left", "top-right", "bottom-left", "bottom-right"] = "bottom-right"
    expires: float = 0
    receipts: dict[str, str] = Field(default_factory=dict)


def window_name(session_id: str) -> str:
    return "help-window-" + hashlib.sha256(session_id.encode()).hexdigest()[:32]


def return_path(value: str) -> str:
    """Only local settings GET targets, never provider URLs or POST actions."""
    try:
        parts = urlsplit(value)
    except ValueError:
        return "/einstellungen"
    if (parts.scheme or parts.netloc or "\\" in value or any(ord(c) < 32 for c in value)
            or not shows_help_button(parts.path) or len(value) > 1000):
        return "/einstellungen"
    params = {key: values for key, values in parse_qs(parts.query).items() if key in {"bereich", "suche"}}
    return parts.path + ("?" + urlencode(params, doseq=True) if params else "")


class HelpWindow:
    def __init__(self, help_site: HelpSite):
        self.help, self.site = help_site, help_site.site

    def target(self, value: str) -> str:
        """A real GET route, also when the current HTML came from a POST handler."""
        value = return_path(value)
        parts = urlsplit(value)
        path = parts.path
        while path and not any(method == "GET" and pattern.fullmatch(path)
                               for method, pattern, _ in self.site.app._routes):
            path = path.rpartition("/")[0]
        return value if path == parts.path else path or "/einstellungen"

    def state(self, session: WebSession) -> WindowState:
        try:
            state = self.site.views.store.load_model(window_name(session.id), WindowState)
        except CorruptState:
            state = None
        if state is not None and state.expires > self.site.clock().timestamp():
            return state
        if state is not None:
            self.site.views.store.delete(window_name(session.id))
        return WindowState(expires=min(session.expires_at.timestamp(), self.site.clock().timestamp() + 86400))

    def cleanup(self) -> None:
        """Called by the existing chat worker on startup and during its periodic cleanup."""
        keep = {window_name(session.id) for session in self.site.auth.sessions()}
        with self.site.views.store.locked():
            for name in self.site.views.store.names("help-window-"):
                try:
                    state = self.site.views.store.load_model(name, WindowState)
                except CorruptState:
                    continue
                if name not in keep or state is None or state.expires <= self.site.clock().timestamp():
                    self.site.views.store.delete(name)

    def change(self, session: WebSession, form: dict[str, str]) -> WindowState:
        """Idempotent, versioned fallback for no-JS forms and blocked browser storage."""
        with self.site.views.store.locked():
            state = self.state(session)
            key = form.get("key", "")
            action = form.get("window_action", "")
            digest = hashlib.sha256(repr(sorted(form.items())).encode()).hexdigest()
            if key in state.receipts:
                if state.receipts[key] != digest:
                    raise ValueError("Schlüssel bereits anders verwendet.")
                return state
            if (action not in {"open", "close", "save", "move"} or len(key) != 32
                    or int(form.get("window_version", "0")) != state.version):
                raise ValueError("Fensterstand veraltet. Bitte erneut versuchen.")
            draft = form.get("draft", form.get("frage", state.draft))
            if self.help.chat is not None:
                draft = self.help.chat.redact(draft)
            values = {**state.model_dump(), "version": state.version + 1, "draft": draft,
                      "expires": min(session.expires_at.timestamp(), self.site.clock().timestamp() + 86400),
                      "setting": self.help.setting(form.get("einstellung", state.setting)),
                      "opened": action != "close", "receipts": dict([*state.receipts.items(), (key, digest)][-32:])}
            if action == "move":
                vertical, horizontal = state.corner.split("-")
                direction = form.get("direction", "")
                if direction not in {"up", "down", "left", "right"}:
                    raise ValueError("Ungültige Position.")
                vertical = {"up": "top", "down": "bottom"}.get(direction, vertical)
                horizontal = direction if direction in {"left", "right"} else horizontal
                values["corner"] = vertical + "-" + horizontal
            result = WindowState.model_validate(values)
            if not self.site.auth.active(session.id):
                raise PermissionError("Sitzung abgelaufen.")
            self.site.views.store.save(window_name(session.id), result.model_dump(mode="json"))
            return result

    def fields(self, session: WebSession, state: WindowState, target: str) -> str:
        return (f'<input type="hidden" name="csrf" value="{e(self.site.auth.csrf_token(session.id))}">'
                f'<input type="hidden" name="key" value="{new_key()}">'
                f'<input type="hidden" name="window_version" value="{state.version}">'
                f'<input type="hidden" name="return_to" value="{e(target)}">')

    def frame(self, session: WebSession, path: str, query: str) -> str:
        state = self.state(session)
        params = parse_qs(query)
        opened = params.get("hilfe") == ["offen"] or state.opened
        setting = self.help.setting(params.get("einstellung", [state.setting])[0])
        target = self.target(path + ("?" + query if query else ""))
        scope = self.site.auth.csrf_token("help-window:" + session.id)
        fields = self.fields(session, state, target)
        hidden = "" if opened else " hidden"
        return (f'<div id="help-widget" data-scope="{e(scope)}" data-expires="{state.expires}" '
                f'data-session-expires="{session.expires_at.timestamp()}" '
                f'data-setting="{e(setting)}" data-return="{e(target)}">'
                '<form method="post" action="/hilfe/fenster" class="help-launch">' + fields
                + '<button class="help-fab" name="window_action" value="open" aria-label="Hilfschat öffnen" '
                'title="Hilfschat öffnen" aria-controls="help-window">'
                '<svg viewBox="0 0 24 24" aria-hidden="true" class="nav-icon">'
                '<path d="M4 5h16v11H9l-5 4z M8 9h8 M8 12h5"/></svg></button></form>'
                f'<section id="help-window" class="help-{state.corner}" '
                f'role="region" aria-label="Hilfe zu Einstellungen"{hidden}>'
                '<header class="help-window-head"><h2>Hilfe zu Einstellungen</h2>'
                '<form method="post" action="/hilfe/fenster">' + fields
                + '<button name="window_action" value="close" aria-label="Hilfschat schließen">×</button>'
                '</form></header><form method="post" action="/hilfe/fenster" class="help-move" '
                'aria-label="Chatfenster verschieben">' + fields
                + '<input type="hidden" name="window_action" value="move">'
                '<button name="direction" value="left" data-move="left" aria-label="Chatfenster nach links">←</button>'
                '<button name="direction" value="right" data-move="right" '
                'aria-label="Chatfenster nach rechts">→</button>'
                '<button name="direction" value="up" data-move="up" aria-label="Chatfenster nach oben">↑</button>'
                '<button name="direction" value="down" data-move="down" '
                'aria-label="Chatfenster nach unten">↓</button></form>'
                '<div id="help-window-content">' + self.help.conversation(session, setting, state.draft, target)
                + '</div><p id="help-window-status" role="status" aria-live="polite"></p>'
                '<div id="help-document" hidden><button type="button" data-help-back>Zurück zum Gespräch</button>'
                '<div class="help-document-text"></div></div></section></div>')
