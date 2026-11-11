"""5.5.6: help answers in a small Markdown subset, rendered without any markup of the model."""
import pytest

from mailhelp.helpdocs import concise, derive_short_answer, same_text
from mailhelp.helpdocs.markdown import plain, render


@pytest.mark.parametrize(("text", "html"), [
    ("Ein Satz.", "<p>Ein Satz.</p>"),
    ("Erster Absatz.\n\nZweiter Absatz.", "<p>Erster Absatz.</p><p>Zweiter Absatz.</p>"),
    ("Zeile eins\nZeile zwei", "<p>Zeile eins<br>Zeile zwei</p>"),
    ("Wähle **Speichern** und *dann* `poll_interval_seconds`.",
     "<p>Wähle <strong>Speichern</strong> und <em>dann</em> <code>poll_interval_seconds</code>.</p>"),
    ("1. Öffnen\n2. **Prüfen**\n3. Speichern",
     "<ol><li>Öffnen</li><li><strong>Prüfen</strong></li><li>Speichern</li></ol>"),
    ("3) Weiter\n4) Fertig", '<ol start="3"><li>Weiter</li><li>Fertig</li></ol>'),
    ("- eins\n* zwei\n• drei", "<ul><li>eins</li><li>zwei</li><li>drei</li></ul>"),
    ("Vorher:\n- a\n- b\nNachher.", "<p>Vorher:</p><ul><li>a</li><li>b</li></ul><p>Nachher.</p>"),
    ("1. Schritt\n   mit Fortsetzung\n- Punkt", "<ol><li>Schritt<br>mit Fortsetzung</li></ol><ul><li>Punkt</li></ul>"),
    ("### Einstellungen ###\nText", '<p class="help-md-heading"><strong>Einstellungen</strong></p><p>Text</p>'),
    ("```\nmailhelp --learn 20\n**nicht fett**\n```", "<pre><code>mailhelp --learn 20\n**nicht fett**</code></pre>"),
    ("```sh\noffen bis zum Ende", "<pre><code>offen bis zum Ende</code></pre>"),
    ("Oben\n\n---\n\nUnten", "<p>Oben</p><p>Unten</p>"),
    ("`**kein fett**` bleibt", "<p><code>**kein fett**</code> bleibt</p>"),
    ("2 * 3 * 4 und **offen", "<p>2 * 3 * 4 und **offen</p>"),
    ("", ""),
])
def test_the_subset_is_rendered(text, html):
    assert render(text) == html


@pytest.mark.parametrize("text", [
    "<script>alert(1)</script>", "**<img src=x onerror=alert(1)>**", "`<b>`", "[klick](javascript:alert(1))",
    "![Bild](https://evil.test/x.png)", '<a href="https://evil.test">Link</a>', "### <i>Titel</i>",
])
def test_no_markup_and_no_link_of_the_model_reaches_the_page(text):
    import re
    rendered = render(text)
    # Only the renderer's own elements, without attributes from the text; the rest is escaped.
    tags = re.findall(r"<(/?[a-z0-9]+)([^>]*)>", rendered)
    assert {name.lstrip("/") for name, _ in tags} <= {"p", "br", "strong", "em", "code", "pre", "ol", "ul", "li"}
    assert {attributes for _, attributes in tags} <= {"", ' class="help-md-heading"'}
    assert "javascript:" not in rendered and "x.png" not in rendered


def test_links_show_only_their_text():
    assert render("Siehe [Mailabruf](https://evil.test/a) und ![Bild](x.png).") == "<p>Siehe Mailabruf und Bild.</p>"


def test_underscores_never_format():
    assert render("_nicht kursiv_ und retention.decision_learning_days") == (
        "<p>_nicht kursiv_ und retention.decision_learning_days</p>")


def test_plain_text_drops_the_marks():
    text = "### Titel\n\n**Fett**, *kursiv*, `code` und [Link](x).\n- Punkt\n```\nBefehl\n```\n---"
    assert plain(text) == "Titel\n\nFett, kursiv, code und Link.\nPunkt\nBefehl"


def test_short_answers_work_on_the_visible_text():
    answer = "**Das Intervall** steuert den Abruf. 1. Öffnen. 2. Speichern."
    assert derive_short_answer(answer) == "Das Intervall steuert den Abruf."
    assert derive_short_answer("### Abruf\n\n**Kurz:** Das Intervall steuert den Mailabruf.") == (
        "Abruf Kurz: Das Intervall steuert den Mailabruf.")
    # Inline marks do not count towards the 300 characters and are kept for the window.
    marked = "**" + "Fett " * 59 + "Ende.**"
    assert concise(answer, marked) == marked
    assert same_text("**Nur** ein `Satz`.", "Nur  ein Satz.")
    assert not same_text("Kurz.", "Kurz. Und mehr.")
