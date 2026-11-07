"""4.4.1: the card asks for its result every 0.1 s at first and every 0.5 s later."""
import time

from playwright.sync_api import expect

from conftest import hold, sign_in
from mailhelp.review.commands import CommandKind, CommandSource, ReviewCommand
from tests.scenarios.web_scenario import mail_id

MAIL = mail_id(1)
CARD = f"v-{MAIL}-formular"


def test_a_running_action_is_polled_quickly_first_and_then_less_often(page, mailhelp, monkeypatch):
    if page.device != "desktop":
        return
    sign_in(page, mailhelp)
    release = hold(mailhelp, monkeypatch)
    try:
        session = mailhelp.auth.sessions()[-1].id
        mailhelp.site.commands.submit(ReviewCommand(
            kind=CommandKind.ALREADY_DONE, source=CommandSource.WEB, actor=f"web:{session}",
            mail_id=MAIL, proposal_id="formular", version=1, idempotency_key="synthetic-v441-poll"))
        mailhelp.site.refresh_overview()
        asked = []
        page.on("request", lambda request: "/api/aktion/" in request.url and asked.append(time.monotonic()))
        page.goto(f"{mailhelp.url}/")
        expect(page.locator(f"#{CARD} [data-card-command-status]")).to_have_count(1)
        page.wait_for_timeout(4500)  # Longer than the 30 quick polls.
        release.set()
        result = page.locator(f"#{CARD} [data-command-result]")
        expect(result).to_contain_text("Als schon erledigt erfasst", timeout=15000)
        gaps = [later - earlier for earlier, later in zip(asked, asked[1:], strict=False)]
        assert len(gaps) > 30
        assert sorted(gaps[:20])[10] < 0.3, gaps  # Typical early gap: 0.1 s plus the request.
        assert max(gaps[30:]) >= 0.45, gaps
        assert mailhelp.writer.created == []
        assert page.errors == []
    finally:
        release.set()
