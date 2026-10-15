"""An undo countdown must keep the original, connected action form."""
import re
from urllib.parse import parse_qs

import pytest
from playwright.sync_api import expect
from web_scenario import mail_id

from conftest import item, sign_in
from mailhelp.models import Proposal

MASTER, PANE = ".master-pane", ".detail-pane"


@pytest.mark.parametrize("kind,result", [("reject", "Vorschlag verworfen."), ("confirm", "Angelegt.")])
def test_mouse_selection_during_undo_keeps_original_action_and_sends_it_once(page, mailhelp, kind, result):
    if page.device != "desktop":
        return
    # Allow enough time for real mouse clicks during the production undo window.
    def real_delay(route):
        response = route.fetch()
        route.fulfill(response=response, body=response.text().replace(' data-undo-ms="1000"', ''))

    page.route("**/", real_delay)
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/")
    original = f"v-{mail_id(1)}-elternabend"
    other = page.locator(f"{MASTER} #v-{mail_id(1)}-formular")
    item(page, "#" + original)
    posts, detail_requests = [], []
    page.on("request", lambda request: posts.append(parse_qs(request.post_data))
            if request.method == "POST" and request.url.endswith("/aktion") else None)
    page.on("request", lambda request: detail_requests.append(request.url)
            if "/vorschlag/" in request.url else None)
    form = page.locator(f'{PANE} form:has(input[name="kind"][value="{kind}"])')
    form.get_by_role("button").click()
    expect(page.locator(".undo-toast")).to_contain_text("Rückgängig")
    # Selecting another card must leave the original action form intact.
    other.click(position={"x": 12, "y": 12})
    expect(page.locator(f"{MASTER} article.selected")).to_have_attribute("id", original)
    expect(page.locator(f"{MASTER} article.selected")).to_have_class(re.compile("leaving"))
    assert form.evaluate("node => node.isConnected")
    assert posts == [] and detail_requests == []
    assert mailhelp.store.load_model(f"proposal-{mail_id(1)}-elternabend", Proposal).status == "pending_confirmation"
    page.wait_for_url("**/?ergebnis=*", timeout=15000)
    expect(page.locator("main > .notice").first).to_contain_text(result)
    assert len(posts) == 1
    assert posts[0]["kind"] == [kind] and posts[0]["proposal_id"] == ["elternabend"]
    assert posts[0]["mail_id"] == [mail_id(1)] and posts[0]["version"] == ["1"]
    assert posts[0]["csrf"] and posts[0]["key"]
    assert mailhelp.writer.created == (["Elternabend Klasse 4b"] if kind == "confirm" else [])
    assert page.errors == []


def test_undo_releases_mouse_selection_without_submitting_a_command(page, mailhelp):
    if page.device != "desktop":
        return
    sign_in(page, mailhelp)
    original = f"v-{mail_id(1)}-elternabend"
    item(page, "#" + original).get_by_role("button", name="Verwerfen").click()
    other = page.locator(f"{MASTER} #v-{mail_id(1)}-formular")
    other.click(position={"x": 12, "y": 12})
    expect(page.locator(f"{MASTER} article.selected")).to_have_attribute("id", original)
    page.locator(".undo-toast").get_by_role("button", name="Rückgängig").click()
    expect(page.locator(f"{MASTER} article.selected")).not_to_have_class(re.compile("leaving"))
    other.click(position={"x": 12, "y": 12})
    expect(page.locator(f"{MASTER} article.selected")).to_have_attribute("id", f"v-{mail_id(1)}-formular")
    expect(page.locator(f"{PANE} #detail-v-{mail_id(1)}-formular")).to_be_visible()
    page.wait_for_timeout(1300)
    assert mailhelp.site.commands.queued() == []
    assert mailhelp.store.load_model(f"proposal-{mail_id(1)}-elternabend", Proposal).status == "pending_confirmation"
    assert mailhelp.writer.created == [] and page.errors == []
