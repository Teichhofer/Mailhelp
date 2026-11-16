"""6.2.2: the shared page head and the two page widths."""
from mailhelp.web.pages import layout, page_head


def test_the_head_names_section_title_and_intro_and_escapes_them():
    head = page_head("A<b>", "Einblicke & mehr", "Warum <i>", count=' <span class="count">3</span>')
    assert head == ('<div class="page-heading"><p class="eyebrow">Einblicke &amp; mehr</p>'
                    '<h1>A&lt;b&gt; <span class="count">3</span></h1>'
                    '<p class="page-intro">Warum &lt;i&gt;</p></div>')


def test_a_subpage_head_links_back_and_may_omit_the_intro():
    head = page_head("Schritt", "Auswertung", back=("/auswertung?days=7&x=1", "Zurück zur Auswertung"))
    assert head.startswith('<div class="page-heading"><p class="page-back">'
                           '<a href="/auswertung?days=7&amp;x=1">← Zurück zur Auswertung</a></p>')
    assert "page-intro" not in head


def test_wide_pages_mark_main_and_others_keep_the_standard_width():
    assert '<main id="inhalt" class="page-wide">' in layout("T", "<h1>T</h1>", wide=True)
    assert '<main id="inhalt">' in layout("T", "<h1>T</h1>")
