"""Page objects of the browser tests (Planung 2.1, T7): each screen keeps its selectors in one place."""
from __future__ import annotations

from playwright.sync_api import expect

MASTER, PANE = ".master-pane", ".detail-pane"


class Overview:
    """Open decisions: master list, undo toast and result notices."""

    def __init__(self, page):
        self.page = page

    def item(self, selector: str):
        """An open item with its actions.

        On the desktop the item is selected in the master list and operated in the
        detail pane, whose ids carry the prefix ``detail-``; on phones it is the card.
        """
        if self.page.device != "desktop":
            return self.page.locator(selector)
        self.page.locator(f"{MASTER} {selector}").click(position={"x": 12, "y": 12})
        shown = DetailPane(self.page).entry(selector)
        expect(shown).to_be_visible()
        return shown

    @property
    def selected(self):
        return self.page.locator(f"{MASTER} article.selected")

    @property
    def toast(self):
        return self.page.locator(".undo-toast")

    @property
    def notice(self):
        return self.page.locator("main > .notice").first


class DetailPane:
    """The right-hand pane of the split view on the desktop."""

    def __init__(self, page):
        self.page = page

    @property
    def root(self):
        return self.page.locator(PANE)

    def entry(self, selector: str):
        """The pane's copy of a master entry (``#v-…`` becomes ``#detail-v-…``)."""
        return self.page.locator(f"{PANE} #detail-{selector.removeprefix('#')}")


class SettingsPage:
    """Settings with their explicit two-step confirmation."""

    def __init__(self, page, url: str):
        self.page, self.url = page, url

    def open(self) -> SettingsPage:
        self.page.goto(f"{self.url}/einstellungen")
        return self

    def expand(self, label: str):
        setting = self.page.locator("details.setting").filter(has_text=label)
        setting.locator("summary").click()
        return setting

    def propose(self, setting, value: str) -> None:
        """Fill in a new value and reach the confirmation page."""
        setting.get_by_label("Neuer Wert").fill(value)
        setting.get_by_role("button", name="Prüfen").click()
        expect(self.page.get_by_role("heading", name="Änderung bestätigen")).to_be_visible()

    def confirm(self) -> None:
        self.page.get_by_role("button", name="Änderung ausdrücklich speichern").click()


__all__ = ["MASTER", "PANE", "DetailPane", "Overview", "SettingsPage"]
