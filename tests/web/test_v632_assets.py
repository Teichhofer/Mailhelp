"""Each application's page references the exact stylesheet and script it serves."""
import hashlib

from mailhelp.web import Request, WebApp
from mailhelp.web.app import static_file
from mailhelp.web.http import Response
from mailhelp.web.pages import PAGE_SCRIPTS, layout


def test_asset_versions_follow_startup_content_and_are_scoped_to_the_request(monkeypatch):
    def app():
        instance = WebApp(["localhost"])
        instance.route("GET", "/", lambda _: Response.html(200, layout("Synthetic", "Synthetic")))
        return instance

    first = app()
    modified = static_file("app.css") + b"\n/* Synthetic changed stylesheet */"
    monkeypatch.setattr("mailhelp.web.app.static_file", lambda name: modified if name == "app.css" else static_file(name))
    second = app()
    for instance in (first, second, first):
        html = instance(Request("GET", "/", {"host": "localhost"})).body.decode()
        for name in ("app.css", *PAGE_SCRIPTS):
            version = hashlib.sha256(instance.assets[name]).hexdigest()[:16]
            assert f'/static/{name}?v={version}' in html
            plain = instance(Request("GET", "/static/" + name, {"host": "localhost"})).body
            hashed = instance(Request("GET", "/static/" + name, {"host": "localhost"}, query="v=" + version)).body
            assert plain == hashed == instance.assets[name]
    assert first.asset_urls["app.css"] != second.asset_urls["app.css"]
    assert first.asset_urls["app.js"] == second.asset_urls["app.js"]
    assert '/static/app.css"' in layout("Synthetic", "Synthetic")


def test_page_scripts_load_deferred_in_their_fixed_order():
    """7.0.12: the area scripts share state and DOM order, so they must run exactly in this order."""
    html = layout("Synthetic", "Synthetic")
    positions = [html.index(f'<script src="/static/{name}" defer></script>') for name in PAGE_SCRIPTS]
    assert positions == sorted(positions)
    assert PAGE_SCRIPTS == ("app.js", "open-list.js", "dialogs.js", "push.js", "settings.js", "help.js")
    assert html.count("<script ") == len(PAGE_SCRIPTS)
