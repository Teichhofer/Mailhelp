"""6.2.2: every core page has the same head, one of two widths and the same left edge."""
from __future__ import annotations

from playwright.sync_api import expect

from checks import CORE_PAGES
from conftest import sign_in
from mailhelp.web.pages import NAVIGATION

FRAME = """() => {
  const main = document.querySelector('main'), heads = document.querySelectorAll('main .page-heading');
  const cards = Array.from(document.querySelectorAll('main .card')).filter((card) => card.offsetParent !== null);
  return {
    heads: heads.length,
    titled: heads.length === 1 && !!heads[0].querySelector('h1') && !!heads[0].querySelector('.eyebrow'),
    title: (document.querySelector('main h1') || {}).textContent || '',
    left: Math.round(main.getBoundingClientRect().left),
    limit: getComputedStyle(main).maxWidth,
    spaced: cards.map((card) => card.firstElementChild).filter((first) => first && first.offsetParent !== null
      && parseFloat(getComputedStyle(first).marginTop) > 0).map((first) => first.textContent.trim().slice(0, 30)),
  };
}"""


def test_page_head622_same_frame_on_every_core_page(page, mailhelp):
    if page.device != "desktop":
        return
    labels = dict(NAVIGATION)
    sign_in(page, mailhelp)
    for width in (1366, 1920):
        page.set_viewport_size({"width": width, "height": 900})
        lefts, problems = set(), []
        for path in CORE_PAGES:
            page.goto(mailhelp.url + path)
            expect(page.locator("main")).to_be_visible()
            frame = page.evaluate(FRAME)
            if not frame["titled"]:
                problems.append(f"{path}: {frame['heads']} Seitenköpfe")
            if frame["limit"] not in ("1100px", "1500px"):
                problems.append(f"{path}: Breite {frame['limit']}")
            if frame["spaced"]:
                problems.append(f"{path}: Abstand über dem ersten Kartenelement {frame['spaced']}")
            if path in labels and path != "/" and not frame["title"].startswith(labels[path]):
                problems.append(f"{path}: Titel „{frame['title']}“ statt „{labels[path]}“")
            lefts.add(frame["left"])
        assert problems == []
        assert len(lefts) == 1, lefts  # switching pages never moves the content sideways
    # Rule learning is not set up in this fixture; its page answers 503 on purpose.
    assert [error for error in page.errors if "status of 503" not in error] == []


def test_page_head622_the_frame_check_finds_a_second_head(page, mailhelp):
    """The detector is not vacuous: an added head and a spaced card element are reported."""
    if page.device != "desktop":
        return
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/geraete")
    page.evaluate("""() => {
      const main = document.querySelector('main'), head = document.createElement('div');
      head.className = 'page-heading';
      const card = document.createElement('section'), title = document.createElement('p');
      card.className = 'card';
      title.textContent = 'Abstand';
      title.style.marginTop = '20px';
      card.append(title);
      main.append(head, card);
    }""")
    frame = page.evaluate(FRAME)
    assert frame["heads"] == 2 and not frame["titled"] and frame["spaced"] == ["Abstand"]
