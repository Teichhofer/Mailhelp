"""5.3 (H7): the local reader of the packaged help sections, also without the help chat."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..helpdocs import HelpBase, HelpUnavailable, load
from .auth import WebSession
from .http import Request, Response
from .pages import e, layout, notice

if TYPE_CHECKING:
    from .site import MailhelpSite


class HelpSite:
    def __init__(self, site: MailhelpSite):
        self.site = site
        self._base: HelpBase | None = None
        # The help chat (H9); without it the documentation stays readable.
        self.chat: Any = None
        site.app.route("GET", "/hilfe/dokumentation", site.signed_in(self.index))
        site.app.route("GET", "/hilfe", site.signed_in(self.page))
        site.app.route("POST", "/hilfe/frage", site.signed_in(self.ask))
        site.app.route("POST", "/hilfe/leeren", site.signed_in(self.clear))
        site.app.route("GET", r"/api/hilfe/auftrag/(?P<job_id>[a-f0-9]{32})", site.signed_in(self.status))
        site.app.route("GET", r"/hilfe/dokumentation/(?P<section>[a-z0-9-]{1,80}/[a-z0-9-]{1,160})",
                       site.signed_in(self.section))

    def base(self) -> HelpBase:
        """The packaged help, loaded once; an unusable resource raises HelpUnavailable."""
        if self._base is None:
            self._base = load()
        return self._base

    def _unavailable(self) -> Response:
        return Response.html(503, layout("Hilfe", '<h1>Hilfe</h1>' + notice(
            "Die mitgelieferte Dokumentation ist nicht verfügbar oder gehört zu einer anderen Version. "
            "Einstellungen und Suche funktionieren weiterhin.", "warn")))

    def index(self, request: Request, session: WebSession) -> Response:
        try:
            base = self.base()
        except HelpUnavailable:
            return self._unavailable()
        groups: dict[str, list[str]] = {}
        for item in base.sections:
            label = " › ".join(item.path[1:]) or item.title
            groups.setdefault(item.path[0], []).append(
                f'<li><a href="/hilfe/dokumentation/{e(item.id)}">{e(label)}</a></li>')
        body = "".join(f"<section><h2>{e(title)}</h2><ul>{''.join(links)}</ul></section>"
                       for title, links in groups.items())
        return Response.html(200, layout("Hilfe", f'<h1>Hilfe und Dokumentation</h1>{body}'))

    def section(self, request: Request, session: WebSession, section: str) -> Response:
        try:
            base = self.base()
        except HelpUnavailable:
            return self._unavailable()
        item = base.get(section)
        if item is None:
            return Response.html(404, layout("Hilfe", "<h1>Hilfe</h1>" + notice(
                "Diesen Abschnitt gibt es nicht.", "warn")))
        trail = " › ".join(item.path)
        return Response.html(200, layout(item.title, (
            f'<p class="eyebrow">{e(trail)}</p><h1>{e(item.title)}</h1>'
            f'<pre class="help-text">{e(item.text)}</pre>'
            f'<p class="meta">Quelle: {e(item.source)} · <a href="/hilfe/dokumentation">Alle Abschnitte</a></p>')))


    # --- 5.3 (H10): the visible help chat ---------------------------------------------------------
    def _sources(self, turn: Any) -> str:
        try:
            base = self.base()
        except HelpUnavailable:
            base = None
        links = []
        for source_id in turn.source_ids:
            item = base.get(source_id) if base is not None and base.revision == turn.revision else None
            if item is None:
                # Never label an old answer with a section of another documentation revision.
                links.append(f"<li>{e(source_id)} (frühere Dokumentationsfassung)</li>")
            else:
                links.append(f'<li><a href="/hilfe/dokumentation/{e(item.id)}">{e(" › ".join(item.path))}</a></li>')
        from .settings_search import catalog
        entries = {entry.id: entry for entry in catalog()}
        settings = [f'<li><a href="{e(entries[key].href)}">{e(entries[key].label)}</a></li>'
                    for key in turn.setting_ids if key in entries]
        parts = ""
        if links:
            parts += f'<p class="meta">Quellen</p><ul class="help-sources">{"".join(links)}</ul>'
        if settings:
            parts += f'<p class="meta">Einstellungen</p><ul class="help-sources">{"".join(settings)}</ul>'
        return parts

    def _form(self, csrf: str, version: int, setting: str) -> str:
        from .actions import new_key
        reference = ""
        if setting:
            from .settings_search import catalog
            entry = next((item for item in catalog() if item.key == setting), None)
            if entry is not None:
                reference = (f'<input type="hidden" name="einstellung" value="{e(setting)}">'
                             f'<p class="meta">Bezug: {e(entry.label)} (<code>{e(setting)}</code>)</p>')
        return ('<form method="post" action="/hilfe/frage" class="stack help-form">'
                f'<input type="hidden" name="csrf" value="{e(csrf)}">'
                f'<input type="hidden" name="key" value="{new_key()}">'
                f'<input type="hidden" name="version" value="{version}">{reference}'
                '<label for="help-question">Deine Frage zu Einstellungen und Bedienung</label>'
                '<textarea id="help-question" name="frage" rows="3" maxlength="8000" required></textarea>'
                '<p class="meta">Frage, kurzer Verlauf und passende Abschnitte der Mailhelp-Dokumentation gehen an '
                'den aktiven KI-Anbieter und können Kosten verursachen. Keine Passwörter oder Tokens eingeben. '
                'Der Hilfschat erklärt nur; er ändert keine Einstellungen.</p>'
                '<button class="button primary" type="submit">Frage senden</button></form>')

    def page(self, request: Request, session: WebSession, notice_text: str = "", status: int = 200) -> Response:
        from urllib.parse import parse_qs
        setting = parse_qs(request.query).get("einstellung", [""])[0][:200]
        heading = ('<h1>Hilfe zu Einstellungen</h1><p class="page-intro">Fragen zur Bedienung und Bedeutung von '
                   'Einstellungen; Antworten stützen sich auf die <a href="/hilfe/dokumentation">mitgelieferte '
                   'Dokumentation</a>.</p>')
        if self.chat is None:
            return Response.html(200, layout("Hilfe", heading + notice(
                "Der Hilfschat ist in dieser Installation nicht aktiv. Die Dokumentation bleibt lesbar.", "info")))
        state = self.chat.state(session.id)
        csrf = self.site.auth.csrf_token(session.id)
        turns = "".join(
            f'<article class="help-turn"><p class="help-question"><strong>Frage:</strong> {e(turn.question)}</p>'
            f'<div class="help-answer">{e(turn.answer)}</div>{self._sources(turn)}</article>' for turn in state.turns)
        current = [job for job in state.jobs if job.chat_version == state.version]  # cleared ones stay hidden
        pending = next((job for job in current if job.status in {"queued", "running"}), None)
        last = current[-1] if current else None
        progress, refresh = "", ""
        if pending is not None:
            progress = (f'<p class="notice info" role="status" data-help-job="{e(pending.id)}">'
                        "Antwort wird vorbereitet …</p>")
            refresh = '<meta http-equiv="refresh" content="3">'
        elif last is not None and last.status in {"failed", "interrupted"}:
            from ..helpdocs.chat import MESSAGES
            progress = notice(MESSAGES.get(last.error or "failed", MESSAGES["failed"]), "warn")
        clear = ""
        if state.turns or current:
            clear = ('<form method="post" action="/hilfe/leeren">'
                     f'<input type="hidden" name="csrf" value="{e(csrf)}">'
                     f'<input type="hidden" name="version" value="{state.version}">'
                     '<button class="button" type="submit">Chat leeren</button></form>')
        body = (refresh + heading + (notice(notice_text, "warn") if notice_text else "")
                + f'<section class="help-chat" id="chat" aria-label="Hilfschat">{turns}{progress}</section>'
                + ("" if pending is not None else self._form(csrf, state.version, setting)) + clear)
        return Response.html(status, layout("Hilfe", body))

    def ask(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        from ..helpdocs.chat import ChatRefused
        if self.chat is None:
            return self.page(request, session)
        try:
            version = int(form.get("version", "0"))
            self.chat.submit(session.id, form.get("frage", ""), form.get("key", ""), version,
                             form.get("einstellung") or None)
        except ValueError as error:
            code = error.code if isinstance(error, ChatRefused) else "invalid"
            status = {"rate_limited": 429, "full": 503, "busy": 409, "stale": 409, "conflict": 409}.get(code, 422)
            text = str(error) if isinstance(error, ChatRefused) else "Die Frage ist unvollständig."
            return self.page(request, session, text, status)
        return Response.redirect("/hilfe#chat")

    def clear(self, request: Request, session: WebSession, form: dict[str, str]) -> Response:
        from ..helpdocs.chat import ChatRefused
        if self.chat is not None:
            try:
                self.chat.clear(session.id, int(form.get("version", "0")))
            except (ChatRefused, ValueError):
                pass  # already cleared or stale: the page shows the current state
        return Response.redirect("/hilfe#chat")

    def status(self, request: Request, session: WebSession, job_id: str) -> Response:
        job = None if self.chat is None else self.chat.job(session.id, job_id)
        if job is None:
            return Response.json(404, {"error": "unbekannt"})
        return Response.json(200, {"status": job.status, "error": job.error})
