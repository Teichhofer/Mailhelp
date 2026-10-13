"""Browser tests of the web interface: real server, synthetic state, Chrome.

Run with ``python -m pytest ui_tests --no-cov``.  Every page is opened on a
desktop and an iPhone-sized viewport, screenshots are written to
``.test-tmp/ui-screens`` and the JavaScript coverage of ``app.js`` and
``sw.js`` is measured through the Chrome DevTools protocol; the run fails
unless every block was executed.
"""
from __future__ import annotations

import re
import socket
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ui_tests"))
# Synthetic scenarios and shared helpers of the Python suite (tests/<area>/).
for _folder in sorted((ROOT / "tests").iterdir()):
    if _folder.is_dir() and _folder.name not in {"fixtures", "__pycache__"}:
        sys.path.insert(0, str(_folder))

from web_scenario import Revisions, populate  # noqa: E402

from mailhelp.config import WebSettings  # noqa: E402
from mailhelp.review.inbox import CommandInbox  # noqa: E402
from mailhelp.review.views import ReviewViews  # noqa: E402
from mailhelp.storage import JsonStore  # noqa: E402
from mailhelp.telegram import TelegramDialogController  # noqa: E402
from mailhelp.web import WebApp, WebServer  # noqa: E402
from mailhelp.web.auth import WebAuth  # noqa: E402
from mailhelp.web.site import MailhelpSite  # noqa: E402

STATIC = ROOT / "src/mailhelp/web/static"
COVERED_SCRIPTS = tuple(name for name in ("app.js", "sw.js") if (STATIC / name).exists())
DEVICES = {
    "desktop": dict(viewport={"width": 1366, "height": 900}),
    "mobile": dict(viewport={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True,
                   has_touch=True,
                   user_agent=("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
                               "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
                               "Mobile/15E148 Safari/604.1")),
    # Small phones (e.g. iPhone SE first generation) and large zoom levels.
    "narrow": dict(viewport={"width": 320, "height": 640}, device_scale_factor=2, is_mobile=True,
                   has_touch=True),
}


class Telegram:
    """Records what Mailhelp would send to Telegram."""

    def __init__(self):
        self.sent: list[str] = []

    def send(self, chat_id, text, reply_markup=None):
        self.sent.append(text)

    def poll(self, offset, timeout=None):
        return []

    def answer_callback(self, callback_id, text):
        pass

    def remove_inline_keyboard(self, chat_id, message_id):
        pass

    def send_document(self, *args, **kwargs):
        pass


class Writer:
    def __init__(self):
        self.created: list[str] = []

    def reconcile(self, key):
        return None

    def create(self, item, key):
        self.created.append(item.title)
        return {"id": f"external-{len(self.created)}", "url": "https://calendar.test/neu"}


class Logger:
    def event(self, *args, **fields):
        pass


@dataclass
class Mailhelp:
    """A running web interface on synthetic state, with a simulated main thread."""

    url: str
    store: JsonStore
    telegram: Telegram
    writer: Writer
    dialog: TelegramDialogController
    stop: threading.Event = field(default_factory=threading.Event)

    def pairing_code(self) -> str:
        message = next(text for text in reversed(self.telegram.sent) if "Code " in text)
        return re.search(r"\bCode (\d{4})\b", message).group(1)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def mailhelp(tmp_path):
    port = _free_port()
    settings = WebSettings(enabled=True, port=port, allowed_hosts=[f"127.0.0.1:{port}"])
    telegram, writer, logger = Telegram(), Writer(), Logger()
    with JsonStore(tmp_path / "data") as store:
        populate(store)
        commands = CommandInbox(store)
        dialog = TelegramDialogController(
            store, telegram, 1, 2, logger, {"todoist": writer, "google_calendar": writer},
            False, "Europe/Berlin", Revisions(), commands=commands)
        auth = WebAuth(store, "u" * 40, 30, lambda text: telegram.send(2, text))
        dialog.review.web_authorizer = lambda actor: auth.active(actor.removeprefix("web:"))
        app = WebApp(settings.allowed_hosts)
        site = MailhelpSite(app, auth, settings, "Europe/Berlin", logger,
                     ReviewViews(store, "Europe/Berlin"), commands)
        def test_app(request):
            response = app(request)
            if response.content_type.startswith("text/html"):
                response.body = response.body.replace(b"<body", b'<body data-undo-ms="1000"', 1)
            return response
        server = WebServer("127.0.0.1", port, test_app, logger)
        server.start()
        instance = Mailhelp(f"http://127.0.0.1:{port}", store, telegram, writer, dialog)
        instance.auth = auth
        instance.site = site
        import yaml
        from shared_application import settings as application_settings

        from mailhelp.configuration import ConfigurationService
        from mailhelp.lifecycle import Lifecycle
        from mailhelp.metrics import MetricsRecorder, MetricsSettings
        cfg = application_settings(tmp_path)
        (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
        (tmp_path / "topics.yaml").write_text(
            "topics:\n- id: school\n  name: Schule\n  description: Schule\n  enabled: true\n"
            "  examples: []\n  exclusions: []\n", encoding="utf-8")
        (tmp_path / "irrelevant_topics.yaml").write_text("topics: []\n", encoding="utf-8")
        configuration = ConfigurationService(tmp_path, store, cfg, dialog.review.web_authorizer, lambda value: None)
        dialog.review.configuration = site.archive.configuration = configuration
        site.archive.metrics = MetricsRecorder(tmp_path / "metrics.jsonl", MetricsSettings())
        site.lifecycle = site.archive.lifecycle = Lifecycle(instance.stop.set, dialog.review.web_authorizer)

        def main_thread():
            # Mailhelp's main thread executes web commands between mails.
            while not instance.stop.wait(0.1):
                # This synthetic Telegram port never receives updates. Execute
                # real queued web commands, but keep idle rendering tests idle.
                # Production recovery rewrites projections on every poll and
                # would invalidate a fingerprint even without a new decision.
                if commands.queued():
                    dialog.poll_once()

        # Finish startup recovery before the first browser reads a fingerprint.
        # Otherwise a foreground check can legitimately reload during the test.
        dialog.poll_once()
        worker = threading.Thread(target=main_thread, daemon=True)
        worker.start()
        try:
            yield instance
        finally:
            instance.stop.set()
            worker.join(timeout=5)
            server.stop()


class Coverage:
    """Block coverage of the application scripts, merged over all pages."""

    def __init__(self):
        self.counts: dict[str, list[int]] = {}

    def add(self, result: dict) -> None:
        for script in result["result"]:
            name = script["url"].rsplit("/", 1)[-1]
            if name not in COVERED_SCRIPTS or not script["url"].startswith("http"):
                continue
            source = (STATIC / name).read_bytes().decode("utf-8")
            counts = [0] * len(source)
            ranges = sorted((item for function in script["functions"] for item in function["ranges"]),
                            key=lambda item: (item["startOffset"], -item["endOffset"]))
            for item in ranges:
                for offset in range(item["startOffset"], min(item["endOffset"], len(source))):
                    counts[offset] = item["count"]
            merged = self.counts.setdefault(name, [0] * len(source))
            self.counts[name] = [max(a, b) for a, b in zip(merged, counts, strict=False)]

    def uncovered(self) -> dict[str, list[int]]:
        report = {}
        for name in COVERED_SCRIPTS:
            source = (STATIC / name).read_bytes().decode("utf-8")
            counts = self.counts.get(name)
            if counts is None:
                report[name] = ["nie geladen"]
                continue
            lines = sorted({source.count("\n", 0, offset) + 1 for offset, count in enumerate(counts)
                            if count == 0 and not source[offset].isspace()})
            if lines:
                report[name] = lines
        return report


COVERAGE = Coverage()


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        # Without the compilation cache every load gets fresh block counters.
        instance = playwright.chromium.launch(channel="chrome", args=["--js-flags=--no-compilation-cache"])
        yield instance
        instance.close()


class MeasuredContext:
    """Collect before a manually owned context destroys its pages and counters."""

    def __init__(self, context, collect):
        self.context, self.collect = context, collect

    def close(self):
        self.collect()
        self.context.close()

    def __getattr__(self, name):
        return getattr(self.context, name)


class Page:
    """A Playwright page that records console errors and script coverage."""

    def __init__(self, page, device: str):
        self.page, self.device, self.errors = page, device, []
        self.mobile = device != "desktop"
        page.on("console", lambda message: self.errors.append(message.text)
                if message.type == "error" else None)
        page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.cdp = page.context.new_cdp_session(page)
        # Cached bytecode carries no block counters; without the HTTP cache
        # every load compiles app.js afresh with block coverage.
        self.cdp.send("Network.enable")
        self.cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
        self.cdp.send("Page.enable")
        self.cdp.send("Profiler.enable")
        self.cdp.on("Profiler.preciseCoverageDeltaUpdate", COVERAGE.add)
        self.cdp.send("Profiler.startPreciseCoverage", {
            "callCount": True, "detailed": True, "allowTriggeredUpdates": True})
        self.cdp.on("Page.frameRequestedNavigation", lambda event: self.collect())
        self.cdp.on("Page.frameStartedLoading", lambda event: self.collect())
        self.context = MeasuredContext(page.context, self.collect)

    def collect(self) -> None:
        COVERAGE.add(self.cdp.send("Profiler.takePreciseCoverage"))

    def goto(self, url: str, **kwargs):
        # Coverage of the current document is lost once it is replaced.
        self.collect()
        return self.page.goto(url, **kwargs)

    def reload(self, **kwargs):
        self.collect()
        return self.page.reload(**kwargs)

    def go_back(self, **kwargs):
        self.collect()
        return self.page.go_back(**kwargs)

    def __getattr__(self, name):
        return getattr(self.page, name)


@pytest.fixture(params=list(DEVICES))
def page(request, browser):
    # Service workers are tested separately (test_ui_pwa.py); here they would
    # hide requests from page.route.
    context = browser.new_context(locale="de-DE", timezone_id="Europe/Berlin",
                                  service_workers="block", **DEVICES[request.param])
    wrapped = Page(context.new_page(), request.param)
    try:
        yield wrapped
    finally:
        wrapped.collect()
        context.close()


def sign_in(page: Page, mailhelp: Mailhelp, device_label: str = "") -> None:
    """Pair the browser through the login pages, exactly as a user would."""
    page.goto(f"{mailhelp.url}/anmelden")
    page.get_by_role("button", name="Code per Telegram senden").click()
    page.get_by_label("Code aus Telegram").fill(mailhelp.pairing_code())
    if device_label:
        page.get_by_label("Gerätename").fill(device_label)
    page.get_by_role("button", name="Gerät koppeln").click()
    page.wait_for_url(f"{mailhelp.url}/")


def item(page: Page, selector: str):
    """An open item with its actions.

    On the desktop the item is selected in the master list and operated in the
    detail pane, whose ids carry the prefix ``detail-``; on phones it is the card.
    """
    if page.device != "desktop":
        return page.locator(selector)
    page.locator(".master-pane " + selector).click(position={"x": 12, "y": 12})
    shown = page.locator(".detail-pane #detail-" + selector.removeprefix("#"))
    expect(shown).to_be_visible()
    return shown


def act(page: Page, control, text: str) -> None:
    """Click and wait for the next result page (confirm and reject after the undo time)."""
    with page.expect_event("framenavigated", timeout=20000,
                           predicate=lambda frame: frame == page.main_frame and "?ergebnis=" in frame.url):
        control.click()
    expect(page.get_by_role("heading", name="Offene Entscheidungen")).to_be_visible(timeout=10000)
    expect(page.locator("main > .notice").first).to_contain_text(text)


def pytest_sessionfinish(session, exitstatus):
    """Fail the run if a block of the application scripts never ran."""
    if exitstatus != 0 or session.config.option.keyword or session.config.option.markexpr:
        return
    if session.testscollected == 0 or getattr(session.config.option, "lf", False):
        return
    uncovered = COVERAGE.uncovered()
    if uncovered:
        print(f"\nJavaScript nicht vollständig abgedeckt (Zeilen): {uncovered}")
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
    else:
        print("\nJavaScript-Abdeckung: 100 % der Blöcke in " + ", ".join(COVERED_SCRIPTS))


__all__ = ["DEVICES", "Mailhelp", "Page", "act", "item", "sign_in"]
