"""5.3.12: a floating chat button at the bottom right of the settings pages opens the help chat."""
from pathlib import Path

import pytest

from mailhelp.web import pages
from mailhelp.web.pages import HELP_BUTTON, layout, shows_help_button

BUTTON = '<a class="help-fab" href="/hilfe" aria-label="Hilfschat öffnen" title="Hilfschat öffnen">'


@pytest.mark.parametrize("path", ["/einstellungen", "/einstellungen/postfaecher", "/einstellungen/postfaecher/2",
                                  "/einstellungen/zielprofile", "/einstellungen/ignorierte-absender",
                                  "/einstellungen/web-passwort", "/themen", "/themen/speichern"])
def test_settings_paths_show_the_button(path):
    assert shows_help_button(path)


@pytest.mark.parametrize("path", ["/", "/mails", "/hilfe", "/hilfe/dokumentation", "/einstellungenx",
                                  "/status"])
def test_other_paths_do_not_show_the_button(path):
    assert not shows_help_button(path)


def test_the_layout_shows_the_button_only_when_requested_and_signed_in():
    assert "help-fab" not in layout("Status", "<h1>x</h1>")
    token = HELP_BUTTON.set(True)
    try:
        signed_in = layout("Einstellungen", "<h1>x</h1>", active="/einstellungen")
        guest = layout("Anmelden", "<h1>x</h1>", signed_in=False)
    finally:
        HELP_BUTTON.reset(token)
    assert signed_in.count(BUTTON) == 1
    # Outside the main content, after it, with a hidden icon and a spoken name.
    assert signed_in.index("</main>") < signed_in.index(BUTTON) < signed_in.index("</body>")
    assert 'aria-hidden="true"' in signed_in[signed_in.index(BUTTON):]
    assert "help-fab" not in guest


def test_signed_in_settings_pages_carry_the_button_and_other_pages_do_not(web):
    response = web.browser.request("GET", "/einstellungen")
    assert response.status == 200 and 'id="help-widget"' in response.body.decode()
    # Subpages keep the button, also when their service is unavailable in this setup.
    for path in ("/einstellungen/ignorierte-absender", "/themen"):
        assert 'id="help-widget"' in web.browser.request("GET", path).body.decode(), path
    for path in ("/", "/mails", "/hilfe"):
        assert "help-fab" not in web.browser.request("GET", path).body.decode(), path
    # The button belongs to one request only.
    assert HELP_BUTTON.get() is False


def test_the_button_sits_above_the_phone_bar_and_is_large_enough():
    css = Path(pages.__file__).with_name("static").joinpath("app.css").read_text(encoding="utf-8")
    rules = css[css.index(".help-fab {"):]
    assert "position: fixed;" in rules and "width: 56px; height: 56px;" in rules
    phone = rules[rules.index("@media (max-width: 899px) {"):]
    assert ".help-fab { bottom: calc(76px + env(safe-area-inset-bottom));" in phone
    assert "@media print { .help-fab { display: none; } }" in rules
