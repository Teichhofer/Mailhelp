"""Overview, proposal detail and status pages in the browser (desktop and iPhone)."""
from __future__ import annotations

from playwright.sync_api import expect

from checks import audit
from conftest import sign_in
from web_scenario import mail_id, proposal, save_mail


def test_overview_is_readable_and_mail_content_stays_inert(page, mailhelp):
    dialogs = []
    page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
    sign_in(page, mailhelp)
    cards = page.locator("article.card")
    expect(cards.first).to_contain_text("Vereinsnachrichten Oktober")
    expect(page.locator("article.current")).to_contain_text("Elternabend Klasse 4b")
    assert audit(page, f"uebersicht-{page.device}", page.mobile) == []
    # Script and link in mail content are shown as text, never executed or clickable.
    malicious = page.locator(f"#v-{mail_id(4)}-boese")
    expect(malicious).to_contain_text('Rechnung <script>alert("x")</script> prüfen')
    assert malicious.locator("a[href^='https://evil']").count() == 0
    long_card = page.locator(f"#v-{mail_id(1)}-elternabend")
    long_card.get_by_text("Beleg vollständig anzeigen").click()
    expect(long_card.locator("details .full")).to_be_visible()
    assert dialogs == [] and page.errors == []


def test_detail_and_status_pages(page, mailhelp):
    sign_in(page, mailhelp)
    page.get_by_role("link", name="Elternabend Klasse 4b").click()
    expect(page.get_by_role("heading", name="Termin")).to_be_visible()
    page.get_by_text("Beleg vollständig anzeigen").click()
    assert audit(page, f"detail-{page.device}", page.mobile) == []
    page.get_by_role("link", name="Status").click()
    expect(page.locator(".stat").filter(has_text="Warten auf dich")).to_contain_text("4")
    assert audit(page, f"status-{page.device}", page.mobile) == []
    page.goto(f"{mailhelp.url}/vorschlag/{mail_id(5)}/turnen")
    expect(page.get_by_role("link", name="Im Kalender öffnen")).to_be_visible()
    assert audit(page, f"detail-angelegt-{page.device}", page.mobile) == []
    assert page.errors == []


def refresh(page):
    """What app.js does when the app returns to the foreground."""
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")


def test_overview_refreshes_itself_but_never_discards_typed_text(page, mailhelp):
    sign_in(page, mailhelp)
    badge = page.locator("#verbindung")
    # Unchanged state: nothing happens.
    refresh(page)
    expect(badge).to_have_text("● Verbunden")
    # A failing or refused state request does not reload.
    page.route("**/api/stand", lambda route: route.abort())
    refresh(page)
    expect(badge).to_have_text("PC nicht erreichbar")
    page.unroute("**/api/stand")
    assert page.errors == ["Failed to load resource: net::ERR_FAILED"]  # the abort above
    page.errors.clear()
    page.route("**/api/stand", lambda route: route.fulfill(status=401, body="{}"))
    with page.expect_response("**/api/stand"):
        refresh(page)
    expect(badge).to_have_text("● Verbunden")
    page.unroute("**/api/stand")
    assert page.errors == [
        "Failed to load resource: the server responded with a status of 401 (Unauthorized)"]
    page.errors.clear()
    # In the background nothing is checked.
    page.evaluate("Object.defineProperty(document, 'visibilityState', {value: 'hidden', configurable: true})")
    refresh(page)
    page.evaluate("Object.defineProperty(document, 'visibilityState', {value: 'visible', configurable: true})")
    save_mail(mailhelp.store, 9, "Hort <hort@x.test>", "Ferienbetreuung",
              [proposal(9, "hort", title="Anmeldung Ferienbetreuung abgeben", due="2026-10-24")])
    # Typed text is kept: only a hint appears.
    page.evaluate("""() => { const field = document.createElement('textarea');
        field.setAttribute('aria-label', 'Notiz'); field.value = 'nicht verlieren';
        document.querySelector('main').append(field); }""")
    refresh(page)
    expect(badge).to_have_text("Neue Daten – bitte neu laden")
    assert audit(page, f"neue-daten-{page.device}", page.mobile) == []
    page.evaluate("document.querySelector('textarea[aria-label=Notiz]').value = ''")

    # The automatic reload is answered once with 204 so the document stays and
    # its script coverage can be read; then the page is loaded normally.
    reloads = []

    def hold(route):
        reloads.append(route.request.url)
        route.fulfill(status=204)

    page.route(f"{mailhelp.url}/", hold)
    refresh(page)
    expect(page.get_by_label("Notiz")).to_have_count(1)
    page.wait_for_timeout(300)
    assert reloads == [f"{mailhelp.url}/"]
    page.unroute(f"{mailhelp.url}/")
    page.collect()
    page.reload()
    expect(page.get_by_text("Anmeldung Ferienbetreuung abgeben")).to_be_visible()
    assert page.errors == []
