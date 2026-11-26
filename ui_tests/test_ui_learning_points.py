"""8.7.4: a customer session learns from the mailbox in points – estimate, start, pause, review, adoption."""
from datetime import UTC, datetime
from decimal import Decimal

from playwright.sync_api import expect

from checks import audit
from mailhelp.usage.valuations import UsageMeter
from tests.fakes import ui_learning

learning_server = ui_learning.learning_server


def customer_mode(h):
    """Customer mode with a valued, priced instance; only a code issued afterwards signs in a customer."""
    h.auth.enter_customer_mode("kunde")
    h.code = h.auth.issue_code()
    h.site.usage.meter = UsageMeter(h.directory / "usage")
    h.site.usage.meter.valuations.add(Decimal(1), Decimal(900), "operator", datetime(2020, 1, 1, tzinfo=UTC))
    h.site.learning_price = Decimal("0.5")
    h.configuration.restricted = lambda actor: not h.auth.is_operator(actor.removeprefix("web:"))


def test_learning874_customer_run_in_points_with_keyboard(page, learning_server):
    h = learning_server
    customer_mode(h)
    page.goto(h.url + "/lernen/postfach")
    page.get_by_label("Code aus der Mailhelp-Konsole").fill(h.code)
    page.get_by_role("button", name="Gerät koppeln", exact=True).click()
    page.goto(h.url + "/lernen/postfach")
    page.get_by_label("Anzahl Mails", exact=True).fill("2")
    limit = page.get_by_label("Punktegrenze für diesen Lauf", exact=True)
    limit.focus()
    page.keyboard.type("150")
    page.keyboard.press("Enter")  # 8.7.6 bugfix: Enter in the field shows the estimate, not "Ordner laden"
    expect(page.get_by_text("Bitte mindestens 201,00 Punkte angeben.", exact=False)).to_be_visible()
    expect(page.get_by_role("button", name="Lesenden Lernlauf starten (verbraucht Punkte)")).to_have_count(0)
    page.get_by_label("Punktegrenze für diesen Lauf", exact=True).fill("1000")
    page.get_by_role("button", name="Schätzung anzeigen", exact=True).click()
    expect(page.get_by_text("Geschätzter Verbrauch: etwa 200,00 Punkte", exact=False)).to_be_visible()
    assert "USD" not in page.content() and "Tokens" not in page.inner_text("main")
    # 8.7.6 (AP4a): the navigation offers only customer pages; reports are one since 8.7.7
    links = page.locator("nav a[href]").evaluate_all("nodes => nodes.map(node => node.getAttribute('href'))")
    assert {"/verbrauch", "/berichte"} <= set(links) and not {"/status", "/auswertung", "/abgleich"} & set(links)
    assert audit(page, "learning874-estimate-" + page.device, page.mobile) == []
    page.get_by_role("button", name="Lesenden Lernlauf starten (verbraucht Punkte)", exact=True).click()
    expect(page.get_by_text("Reserviert: 0,00 Punkte der Punktegrenze von 1.000,00 Punkte.", exact=False)) \
        .to_be_visible()
    page.get_by_role("button", name="Pausieren", exact=True).click()
    page.get_by_role("button", name="Fortsetzen", exact=True).click()
    while h.worker.tick():
        pass
    page.reload()
    expect(page.get_by_role("heading", name="<Newsletter>", exact=True)).to_be_visible()
    page.get_by_label("Titel", exact=True).fill("Camping-Buchungen")
    page.get_by_label("Übernahme", exact=True).select_option("relevant")
    page.get_by_role("button", name="Auswahl als Entwurf speichern", exact=True).click()
    page.get_by_role("button", name="Ausgewählte Themen, Filter und Ordner ausdrücklich übernehmen",
                     exact=True).click()
    expect(page.get_by_text("Neue Analysen übernehmen die Themen", exact=False)).to_be_visible()
    expect(page.get_by_role("link", name="Konfiguration neu laden", exact=True)).to_have_count(0)
    assert "USD" not in page.content()
    assert audit(page, "learning874-done-" + page.device, page.mobile) == []
    assert h.jobs.state().status == "done" and page.errors == []
