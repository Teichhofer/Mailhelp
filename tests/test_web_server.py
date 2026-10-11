"""Web server skeleton: request checks, security headers, limits, start and stop."""
from __future__ import annotations

import http.client
import socket
from pathlib import Path
from threading import Event

import pytest

from mailhelp.application import Application, build_application
from mailhelp.config import Secrets, Topic, WebSettings, load_all
from mailhelp.web import Request, Response, WebApp, WebServer, WebServerError
from mailhelp.web import server as server_module
from mailhelp.web.http import CONTENT_SECURITY_POLICY, MAX_BODY_BYTES
from test_application import Log, Orch, settings as app_settings
from test_core import prompt_config

HOST = "127.0.0.1:8765"


def get(app, path, host=HOST, method="GET", **headers):
    return app(Request(method, path, {"host": host, **headers}))


# --- in-process checks -----------------------------------------------------------

def test_health_needs_no_login_and_reveals_no_data():
    response = get(WebApp([HOST]), "/health")
    assert (response.status, response.body) == (200, b'{"status": "ok"}')
    headers = dict(response.all_headers())
    assert headers["Content-Security-Policy"] == CONTENT_SECURITY_POLICY
    assert "unsafe-inline" not in CONTENT_SECURITY_POLICY
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Cache-Control"] == "no-store"
    assert not any(name.lower().startswith("access-control") for name in headers)


@pytest.mark.parametrize("host", ["evil.test:8765", "127.0.0.1:9999", "", "localhost"])
def test_foreign_host_headers_are_refused(host):
    """DNS rebinding: a foreign name that resolves to 127.0.0.1 must not reach a route."""
    assert get(WebApp([HOST, "localhost:8765"]), "/health", host=host).status == 421


def test_host_comparison_ignores_case_and_surrounding_space():
    assert get(WebApp([HOST, "mailhelp-pc.tail.ts.net"]), "/health",
               host=" Mailhelp-PC.tail.ts.net ").status == 200


@pytest.mark.parametrize(("method", "path", "status"), [
    ("PUT", "/health", 405), ("DELETE", "/health", 405), ("OPTIONS", "/health", 405),
    ("POST", "/health", 405), ("GET", "/unbekannt", 404), ("GET", "/../health", 400),
    ("GET", "//evil.test/health", 400), ("GET", "/a\\b", 400), ("GET", "health", 400),
    ("GET", "/static/./x", 400),
])
def test_methods_and_paths_outside_the_routes(method, path, status):
    response = get(WebApp([HOST]), path, method=method)
    assert response.status == status
    if status == 405:
        assert response.headers["Allow"] in {"GET, POST", "GET"}


def test_request_helpers_parse_cookies_forms_and_accept():
    request = Request("POST", "/x", {"cookie": "a=1; broken; a=2; b=x=y", "accept": "application/json"},
                      body=b"name=Ada&name=Eve&leer=")
    assert request.cookies() == {"a": "1", "b": "x=y"}
    assert request.form() == {"name": "Ada", "leer": ""}
    assert request.wants_json() and not Request("GET", "/").wants_json()
    assert Request("GET", "/").cookies() == {}
    with pytest.raises(ValueError):
        Request("POST", "/", body=b"&".join(b"f%d=1" % index for index in range(30))).form()
    with pytest.raises(UnicodeDecodeError):
        Request("POST", "/", body=b"x=\xff").form()


def test_responses_only_redirect_inside_the_application():
    assert Response.redirect("/status").headers == {"Location": "/status"}
    for target in ("https://evil.test/", "//evil.test/", "status"):
        with pytest.raises(ValueError):
            Response.redirect(target)
    page = Response.html(200, "<p>ü</p>")
    page.cookies.append("a=1")
    assert page.body == "<p>ü</p>".encode() and ("Set-Cookie", "a=1") in page.all_headers()
    assert Response.text(200, "x").content_type.startswith("text/plain")


# --- real sockets ----------------------------------------------------------------

class Logger:
    def __init__(self):
        self.events = []

    def event(self, level, module, event, **fields):
        self.events.append((level, module, event, fields))


@pytest.fixture
def running():
    servers = []

    def start(handler=None, **kwargs):
        logger = Logger()
        server = WebServer("127.0.0.1", 0, handler or WebApp([HOST]), logger, **kwargs)
        server.start()
        servers.append(server)
        return server, logger

    yield start
    for server in servers:
        server.stop()


def call(server, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection(*server.address, timeout=5)
    try:
        connection.request(method, path, body=body, headers={"Host": HOST, **(headers or {})})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def test_server_answers_and_logs_without_query_strings(running):
    server, logger = running()
    status, headers, body = call(server, "GET", "/health?token=geheim")
    assert (status, body) == (200, b'{"status": "ok"}')
    # No Server header: the version is not disclosed.
    assert "Server" not in headers and headers["X-Frame-Options"] == "DENY"
    status, _, body = call(server, "HEAD", "/health")
    assert (status, body) == (405, b"")
    for method in ("PUT", "DELETE", "OPTIONS"):
        assert call(server, method, "/health", body=b"")[0] == 405
    request_events = [fields for _, _, event, fields in logger.events if event == "request"]
    assert request_events[0]["path"] == "/health" and "geheim" not in str(logger.events)
    assert request_events[0]["status"] == 200


def test_server_limits_request_bodies(running):
    server, _ = running(lambda request: Response.text(200, str(len(request.body))))
    assert call(server, "POST", "/", body=b"x=1")[2] == b"3"
    assert call(server, "POST", "/", body=b"x" * (MAX_BODY_BYTES + 1))[0] == 413
    assert call(server, "POST", "/", headers={"Content-Length": "zehn"})[0] == 400
    connection = http.client.HTTPConnection(*server.address, timeout=5)
    connection.putrequest("POST", "/")
    connection.putheader("Host", HOST)
    connection.endheaders()
    assert connection.getresponse().status == 411
    connection.close()


def test_a_failing_route_is_an_internal_error_without_details(running):
    def broken(_request):
        raise RuntimeError("geheime Einzelheit")

    server, logger = running(broken)
    status, _, body = call(server, "GET", "/")
    assert (status, body) == (500, "Interner Fehler.".encode())
    failure = next(fields for _, _, event, fields in logger.events if event == "request_failed")
    assert failure == {"method": "GET", "error_class": "RuntimeError"}


def test_a_busy_port_is_reported_and_stop_is_idempotent(running):
    server, _ = running()
    second = WebServer("127.0.0.1", server.address[1], WebApp([HOST]), Logger())
    with pytest.raises(WebServerError, match="Port belegt"):
        second.start()
    second.stop()
    server.stop()
    server.stop()


def test_bind_without_exclusive_option(running, monkeypatch):
    monkeypatch.setattr(server_module._Server, "exclusive_bind", None)
    server, _ = running()
    assert call(server, "GET", "/health")[0] == 200


def test_bind_with_exclusive_option(running, monkeypatch):
    # Any valid socket option exercises the exclusive-bind path on every platform.
    monkeypatch.setattr(server_module._Server, "exclusive_bind", socket.SO_KEEPALIVE)
    server, _ = running()
    assert call(server, "GET", "/health")[0] == 200


# --- configuration -----------------------------------------------------------

def test_web_settings_defaults_and_validation():
    assert WebSettings().model_dump() == {
        "enabled": False, "host": "127.0.0.1", "port": 8765,
        "allowed_hosts": ["127.0.0.1:8765", "localhost:8765"], "session_days": 30}
    WebSettings(host="0.0.0.0", allowed_hosts=["mailhelp-pc.tail-1.ts.net", "127.0.0.1:8765"])
    for invalid in ({"host": "localhost"}, {"allowed_hosts": ["https://x.test"]},
                    {"allowed_hosts": ["Upper.test"]}, {"allowed_hosts": []}, {"port": 0}):
        with pytest.raises(ValueError):
            WebSettings(**invalid)


def write_config(directory: Path) -> dict[str, str]:
    for name in ("config.yaml", "prompts.yaml", "topics.yaml", "irrelevant_topics.yaml"):
        source = Path("config.example.yaml" if name == "config.yaml" else name)
        (directory / name).write_text(source.read_text(encoding="utf8"), encoding="utf8")
    return {name: "secret" for name in [
        "IMAP_USERNAME", "IMAP_PASSWORD", "OPENROUTER_API_KEY", "TELEGRAM_BOT_TOKEN", "TODOIST_TOKEN",
        "TODOIST_CLIENT_ID", "TODOIST_CLIENT_SECRET", "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN"]}


def test_web_secret_is_required_only_when_enabled_and_never_changes_the_fingerprint(tmp_path):
    env = write_config(tmp_path)
    settings, secrets, *_, fingerprint = load_all(tmp_path, env)
    assert not settings.web.enabled and secrets.mailhelp_web_secret is None
    text = (tmp_path / "config.yaml").read_text(encoding="utf8")
    marker = "  enabled: false\n  # Nur lokal"
    assert text.count(marker) == 1
    (tmp_path / "config.yaml").write_text(
        text.replace(marker, "  enabled: true\n  # Nur lokal"), encoding="utf8")
    with pytest.raises(ValueError, match="MAILHELP_WEB_SECRET"):
        load_all(tmp_path, env)
    with pytest.raises(ValueError, match="mindestens 32"):
        load_all(tmp_path, {**env, "MAILHELP_WEB_SECRET": "kurz"})
    enabled, secrets, *_, enabled_fingerprint = load_all(tmp_path, {**env, "MAILHELP_WEB_SECRET": "s" * 32})
    assert enabled.web.enabled and secrets.mailhelp_web_secret.get_secret_value() == "s" * 32
    assert "s" * 32 not in repr(secrets)
    assert enabled_fingerprint == fingerprint


# --- application lifecycle -------------------------------------------------------

class Telegram:
    def __init__(self, error=None):
        self.sent, self.error = [], error

    def send(self, chat_id, text):
        if self.error:
            raise self.error
        self.sent.append(text)


class FakeWeb:
    def __init__(self, error=None):
        self.error, self.calls = error, []

    def start(self):
        self.calls.append("start")
        if self.error:
            raise self.error

    def stop(self):
        self.calls.append("stop")


def lifecycle_app(tmp_path, web, telegram):
    return Application(app_settings(tmp_path), object(), Log(), object(), object(), object(),
                       telegram, object(), object(), Orch(), Event(), web=web)


def test_web_start_failure_keeps_mail_processing_running(tmp_path):
    web, telegram = FakeWeb(WebServerError("Weboberfläche konnte nicht starten")), Telegram()
    service = lifecycle_app(tmp_path, web, telegram)
    service._start_web()
    assert service.web is None
    assert telegram.sent == ["⚠️ Weboberfläche konnte nicht starten. Mailhelp läuft ohne Weboberfläche weiter."]
    assert service.logger.events[0][0][2] == "server_start_failed"
    service._stop_web()
    assert web.calls == ["start"]


def test_web_start_notice_failure_is_only_logged(tmp_path):
    service = lifecycle_app(tmp_path, FakeWeb(WebServerError("x")), Telegram(RuntimeError("down")))
    service._start_web()
    assert [event[0][2] for event in service.logger.events] == [
        "server_start_failed", "web_start_notice_failed"]


def test_web_runs_with_the_application_and_stops_with_it(tmp_path):
    web = FakeWeb()
    service = lifecycle_app(tmp_path, web, Telegram())
    service._start_web()
    service._stop_web()
    service._stop_web()
    assert web.calls == ["start", "stop"]
    lifecycle_app(tmp_path, None, Telegram())._start_web()


@pytest.mark.parametrize("enabled", [True, False])
def test_build_application_creates_the_web_server_only_when_enabled(tmp_path, monkeypatch, enabled):
    class Resource:
        def __init__(self, *args, **kwargs): pass
        def close(self): pass
        def send(self, *args): pass

    for name in ("ImapReader", "OpenRouterClient", "DecisionClient", "TelegramClient",
                 "HttpWriter", "GoogleOAuthTokenProvider"):
        monkeypatch.setattr(f"mailhelp.application.{name}", Resource)
    cfg = app_settings(tmp_path)
    cfg.logging.file.enabled = cfg.logging.console.enabled = False
    cfg.web.enabled = enabled
    secrets = Secrets(imap_username="u", imap_password="p", openrouter_api_key="o", telegram_bot_token="t",
                      todoist_token="d", todoist_client_id="ti", todoist_client_secret="ts",
                      google_oauth_client_id="i", google_oauth_client_secret="s",
                      google_oauth_refresh_token="r", mailhelp_web_secret="w" * 32)
    with build_application(cfg, secrets, [Topic(id="x", name="x", enabled=True, description="x")],
                           prompt_config(), "f" * 64, base_directory=tmp_path) as made:
        assert isinstance(made.web, WebServer) is enabled
        assert (made.dialog.commands is not None) is enabled
        if enabled:
            assert (made.web.host, made.web.port) == ("127.0.0.1", 8765)


@pytest.mark.parametrize("name", ["app.css", "app.js", "icon-192.png", "icon-512.png",
                                  "icon-maskable-512.png"])
def test_static_application_files_are_served_from_the_package(name):
    response = get(WebApp([HOST]), f"/static/{name}")
    assert response.status == 200 and response.cache == "no-cache" and response.body
    assert response.body == (Path("src/mailhelp/web/static") / name).read_bytes()


@pytest.mark.parametrize("path", ["/static/unbekannt.css", "/static/..", "/static/pages.py",
                                  "/static/APP.CSS"])
def test_only_listed_static_files_are_readable(path):
    assert get(WebApp([HOST]), path).status in {400, 404}


def test_aborted_connections_are_logged_without_traceback(running, capsys):
    server, logger = running()
    try:
        raise ConnectionAbortedError("client gone")
    except ConnectionAbortedError:
        server._server.handle_error(None, ("127.0.0.1", 1))
    assert logger.events[-1][2:] == ("connection_error", {"error_class": "ConnectionAbortedError"})
    assert capsys.readouterr().err == ""


def test_pwa_files_are_served_at_the_root_without_login():
    import json as json_module
    from mailhelp.web.app import ROOT_FILES, STATIC_FILES
    app = WebApp([HOST])
    manifest = get(app, "/manifest.webmanifest")
    assert manifest.content_type.startswith("application/manifest+json")
    data = json_module.loads(manifest.body)
    assert (data["display"], data["start_url"], data["scope"], data["lang"]) == ("standalone", "/", "/", "de")
    assert {icon["src"].removeprefix("/static/") for icon in data["icons"]} <= set(STATIC_FILES)
    assert any(icon.get("purpose") == "maskable" for icon in data["icons"])
    worker = get(app, "/sw.js")
    assert worker.status == 200 and worker.content_type.startswith("text/javascript")
    offline = get(app, "/offline.html")
    assert "PC nicht erreichbar".encode() in offline.body and b"<script" not in offline.body
    assert set(ROOT_FILES) == {"manifest.webmanifest", "sw.js", "offline.html"}


def test_service_worker_caches_only_the_shell():
    source = (Path("src/mailhelp/web/static") / "sw.js").read_text(encoding="utf-8")
    shell = source.split("var SHELL = [", 1)[1].split("]", 1)[0]
    assert shell == '"/offline.html", "/static/app.css", "/static/icon-192.png", "/static/icon-512.png"'
    # No API, page or data URL is ever put into the cache, and nothing is replayed later.
    assert "cache.put" not in source and "sync" not in source and "/api" not in source


def test_compose_publishes_the_web_port_only_on_localhost():
    import yaml
    service = yaml.safe_load(Path("compose.yaml").read_text(encoding="utf-8"))["services"]["mailhelp"]
    assert service["ports"] == ["127.0.0.1:8765:8765"]
    assert "EXPOSE 8765" in Path("Dockerfile").read_text(encoding="utf-8")
