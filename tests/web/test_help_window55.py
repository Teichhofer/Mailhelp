"""5.5: the tidier help window (cost notice, short answers)."""
import re

from tests.fakes.shared_web_actions import web as web  # noqa: F401


def test_window55_cost_notice_is_folded_behind_one_word(web):
    page = web.browser.request("GET", "/einstellungen").body.decode()
    folded = re.search(r'<details class="help-cost-hint"><summary>Kostenpflichtig</summary>(.*?)</details>', page)
    assert folded is not None
    # The complete warning is still there, only collapsed; never open by default.
    assert "können Kosten verursachen" in folded.group(1)
    assert "Keine Passwörter oder Tokens eingeben" in folded.group(1)
    assert '<details class="help-cost-hint" open' not in page
    assert page.count("können Kosten verursachen") == 1


def _turns(web, *turns):
    from datetime import UTC, datetime

    from mailhelp.helpdocs import load
    from mailhelp.helpdocs.chat import ChatState

    class Chat:
        def state(self, session_id):
            return ChatState(turns=list(turns), updated_at=datetime.now(UTC))

    web.site.archive.help.chat = Chat()
    web.site.archive.help._base = load()
    return web.browser.request("GET", "/einstellungen").body.decode()


def test_window55_short_answer_first_and_the_full_one_closed_behind_it(web):
    from mailhelp.helpdocs import load
    from mailhelp.helpdocs.chat import Turn

    revision = load().revision
    page = _turns(web, Turn(question="Frage?", answer="Lang <b>eins</b>. 1. Schritt. 2. Schritt.",
                            short_answer="Kurz <i>und</i> knapp.", revision=revision))
    assert '<div class="help-answer help-answer-short"><p>Kurz &lt;i&gt;und&lt;/i&gt; knapp.</p></div>' in page
    assert ('<details class="help-answer-full"><summary>Ausführliche Antwort anzeigen</summary>'
            '<div class="help-answer-text"><p>Lang &lt;b&gt;eins&lt;/b&gt;. 1. Schritt. 2. Schritt.</p></div>'
            '</details>') in page
    assert "<details class=\"help-answer-full\" open" not in page and "<b>eins" not in page


def test_window55_markdown_answers_are_rendered_as_safe_markup(web):
    from mailhelp.helpdocs import load
    from mailhelp.helpdocs.chat import Turn

    answer = "So geht es:\n\n1. **Einstellungen** öffnen\n2. `poll_interval_seconds` ändern\n\n[x](https://evil.test)"
    page = _turns(web, Turn(question="Wie?", answer=answer, short_answer="Über **Einstellungen**.",
                            revision=load().revision))
    assert '<div class="help-answer help-answer-short"><p>Über <strong>Einstellungen</strong>.</p></div>' in page
    assert ('<div class="help-answer-text"><p>So geht es:</p><ol><li><strong>Einstellungen</strong> öffnen</li>'
            '<li><code>poll_interval_seconds</code> ändern</li></ol><p>x</p></div>') in page
    assert "evil.test" not in page


def test_window55_an_answer_without_more_detail_is_shown_once(web):
    from mailhelp.helpdocs import load
    from mailhelp.helpdocs.chat import MESSAGES, Turn

    revision = load().revision
    page = _turns(web, Turn(question="Frage?", answer="Nur ein Satz.", revision=revision),
                  Turn(question="Unklar?", answer=MESSAGES["not_found"], revision=revision, local=True))
    assert '<div class="help-answer"><p>Nur ein Satz.</p></div>' in page
    # Mailhelp's own two-sentence notice is never split behind "Ausführliche Antwort anzeigen".
    assert "help-answer-full" not in page and "Bitte die Frage genauer fassen" in page
    # A turn from before 5.5.4 (no short answer) gets a derived one.
    page = _turns(web, Turn(question="Alt?", answer="Erster Satz der alten Antwort. Zweiter Satz.", revision=revision))
    assert '<div class="help-answer help-answer-short"><p>Erster Satz der alten Antwort.</p></div>' in page
