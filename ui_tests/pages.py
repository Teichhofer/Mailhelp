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
        return self.page.locator("[data-command-result] .notice:visible, main > .notice").first


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
    """Settings in section forms (8.5) with their explicit review and confirmation."""

    def __init__(self, page, url: str):
        self.page, self.url = page, url

    def open(self, area: str = "allgemein") -> SettingsPage:
        self.page.goto(f"{self.url}/einstellungen?bereich={area}")
        return self

    def expand(self, label: str):
        """The field of the setting whose label starts with *label*, found by its anchor."""
        from mailhelp.config.configuration import SETTINGS_FIELDS
        from mailhelp.web.settings_pages import setting_label
        from mailhelp.web.settings_search import anchor
        (name,) = [name for name in SETTINGS_FIELDS if str(setting_label(name)).startswith(label)]
        return self.page.locator("#" + anchor(name))

    @staticmethod
    def control(setting):
        return setting.locator("input:not([type=hidden]), textarea, select").first

    def propose(self, setting, value: str) -> None:
        """Change one value and reach the review page of its section."""
        control = self.control(setting)
        if control.evaluate("element => element.tagName") == "SELECT":
            control.select_option(value)
        else:
            control.fill(value)
        setting.locator("xpath=ancestor::form").get_by_role("button", name="Änderungen prüfen").click()
        expect(self.page.get_by_role("heading", name="Änderungen prüfen")).to_be_visible()

    def confirm(self) -> None:
        self.page.get_by_role("button", name="Änderungen ausdrücklich speichern").click()


__all__ = ["MASTER", "PANE", "DetailPane", "Overview", "SettingsPage"]
