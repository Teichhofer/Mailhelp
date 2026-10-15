"""The new frame preserves navigation, pairing and data disclosure boundaries."""
from mailhelp.web.pages import layout


def test_signed_in_frame_groups_routes_and_marks_only_the_current_page():
    html = layout("Einstellungen", "<h1>Einstellungen</h1>", active="/einstellungen")
    assert 'class="app-shell"' in html and 'href="#inhalt"' in html
    assert html.count('aria-current="page"') == 1
    assert '<a href="/einstellungen" aria-current="page">' in html
    assert html.count('class="nav-section"') == 3
    for path in ("/mails", "/verlauf", "/status", "/auswertung", "/berichte", "/geraete", "/abgleich"):
        assert html.count(f'href="{path}"') == 1


def test_unpaired_device_gets_a_small_frame_without_private_navigation():
    html = layout('Anmelden <script>unsafe</script>', '<h1>Gerät koppeln</h1>', signed_in=False)
    assert 'class="guest-shell"' in html and 'href="#inhalt"' in html
    assert 'aria-label="Hauptnavigation"' not in html
    assert '/einstellungen' not in html
    assert '<script>unsafe</script>' not in html
    assert 'Anmelden &lt;script&gt;unsafe&lt;/script&gt;' in html
