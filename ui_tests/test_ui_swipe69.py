"""6.9: finger tracking, release, counters and first-use demonstration."""

import math
import re

import pytest
from playwright.sync_api import expect

from conftest import hold, sign_in
from swipe_fakes69 import EVENT, QUESTION, RELEVANCE, Touch, actions, grab, matrix


@pytest.fixture
def phone(page):
    if page.device != "mobile":
        pytest.skip("Native touch acceptance on the phone")
    page.add_init_script('localStorage.setItem("mailhelp-swipe-hint","1")')
    return page


def test_regression_40_degree_swipe_tracks_both_axes(phone, mailhelp):
    sign_in(phone, mailhelp)
    touch = grab(phone).move(100, -100 * math.tan(math.radians(40)))
    state = matrix(phone)
    assert abs(state["x"] - 100) < 2 and abs(state["y"] + 100 * math.tan(math.radians(40))) < 2
    touch.cancel()


def test_regression_no_braking_or_horizontal_document_overflow(phone, mailhelp):
    sign_in(phone, mailhelp)
    touch = grab(phone).move(210, 0)
    assert abs(matrix(phone)["x"] - 210) < 2
    assert phone.evaluate("document.documentElement.scrollWidth === document.documentElement.clientWidth")
    touch.cancel()


def test_regression_document_does_not_expand_during_or_after_swipe(phone, mailhelp):
    sign_in(phone, mailhelp)
    touch = grab(phone).move(210)
    assert phone.evaluate("document.documentElement.scrollWidth === document.documentElement.clientWidth")
    touch.cancel()
    expect(phone.locator(".swipe-backdrop")).to_have_count(0)
    assert phone.evaluate("document.documentElement.scrollWidth === document.documentElement.clientWidth")


def test_regression_count_updates_without_reload(phone, mailhelp):
    sign_in(phone, mailhelp)
    count = phone.locator(".page-heading h1 .count")
    before = int(count.inner_text())
    phone.locator(EVENT).get_by_role("button", name="Verwerfen", exact=True).click()
    expect(count).to_have_text(str(before - 1))
    expect(phone.locator('.tab-bar a[href="/"] .nav-count')).to_have_text(str(before - 1))


@pytest.mark.parametrize("degrees", [20, 35, 44, 60])
def test_native_pan_y_arbitration(phone, mailhelp, degrees):
    sign_in(phone, mailhelp)
    sent = actions(phone)
    phone.evaluate('window.__cancels=0;document.addEventListener("pointercancel",()=>window.__cancels++)')
    touch = grab(phone).move(180, -180 * math.tan(math.radians(degrees)))
    if degrees < 45:
        assert abs(matrix(phone)["x"] - 180) < 2
        touch.end()
        expect(phone.locator(EVENT + " [data-command-result]")).to_be_attached(timeout=10000)
        assert len(sent) == 1
    else:
        touch.end()
        assert phone.evaluate("window.__cancels") >= 1
        assert sent == []


def test_grip_origin_and_height_limited_tilt(phone, mailhelp):
    sign_in(phone, mailhelp)
    touch = grab(phone)
    box = phone.locator(EVENT).bounding_box()
    point = {"x": touch.x - box["x"], "y": touch.y - box["y"]}
    touch.move(210, -40)
    result = phone.locator(EVENT).evaluate(
        """(card, point) => {
      const m=new DOMMatrix(getComputedStyle(card).transform);
      const origin=getComputedStyle(card).transformOrigin.split(" ").map(parseFloat);
      const p=new DOMPoint(point.x-origin[0],point.y-origin[1]).matrixTransform(m);
      return {x:p.x+origin[0],y:p.y+origin[1],
        angle:Math.atan2(m.b,m.a)*180/Math.PI,height:card.offsetHeight};
    }""",
        point,
    )
    assert abs(result["x"] - (point["x"] + 210)) < 2
    assert abs(result["y"] - (point["y"] - 40)) < 2
    expected = min(10 * min(1, 400 / result["height"]), 210 / box["width"] * 10)
    assert abs(result["angle"] - expected) < 0.05
    touch.cancel()
    expect(phone.locator(EVENT)).not_to_have_class(re.compile(".*swipe-card.*"))
    assert phone.locator(EVENT).evaluate("card=>card.style.transform") == ""


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_flight_placeholder_exactly_one_post_and_server_replacement(phone, mailhelp, monkeypatch, theme):
    from checks import SCREENSHOTS

    phone.emulate_media(color_scheme=theme)
    sign_in(phone, mailhelp)
    release = hold(mailhelp, monkeypatch)
    sent = actions(phone)
    try:
        touch = grab(phone).move(180, -30)
        touch.end()
        expect(phone.locator(EVENT)).to_have_class(re.compile(".*swipe-flying.*"))
        phone.screenshot(path=str(SCREENSHOTS / ("swipe69-flight-" + theme + ".png")))
        expect(phone.locator(".swipe-result")).to_contain_text("Im Kalender anlegen")
        expect(phone.locator(EVENT)).to_be_hidden()
        expect(phone.locator(".swipe-result")).to_have_css("height", "56px")
        assert len(sent) == 1
        release.set()
        expect(phone.locator(EVENT + " [data-command-result]")).to_be_attached(timeout=10000)
        expect(phone.locator(".swipe-result")).to_have_count(0)
        assert len(sent) == 1 and phone.errors == []
    finally:
        release.set()


@pytest.mark.parametrize("mode", ["rejected", "interrupted"])
def test_flight_errors_preserve_result_and_never_repeat(phone, mailhelp, mode):
    sign_in(phone, mailhelp)
    sent = actions(phone)
    phone.route(
        "**/aktion",
        lambda route: route.fulfill(status=409, json={"error": "Synthetic refusal"})
        if mode == "rejected"
        else route.abort(),
    )
    touch = grab(phone).move(180)
    touch.end()
    if mode == "rejected":
        expect(phone.locator(EVENT)).to_be_visible()
        expect(phone.locator(EVENT + " [role=alert]")).to_have_text("Synthetic refusal")
        expect(phone.locator(".swipe-result")).to_have_count(0)
        expect(phone.locator(EVENT).get_by_role("button", name="Verwerfen", exact=True)).to_be_enabled()
    else:
        expect(phone.locator(".swipe-result")).to_contain_text("Antwort unterbrochen")
        phone.wait_for_timeout(1200)
    assert len(sent) == 1


@pytest.mark.parametrize("distance,reverse,expected", [(80, False, True), (45, False, False), (120, True, False)])
def test_bounded_momentum(phone, mailhelp, distance, reverse, expected):
    sign_in(phone, mailhelp)
    sent = actions(phone)
    touch = grab(phone)
    if reverse:
        touch.move(distance)
        phone.wait_for_timeout(150)
        touch.move(-40, steps=2, duration=1)
    else:
        touch.move(distance, steps=2, duration=1)
    touch.end()
    if expected:
        expect(phone.locator(EVENT + " [data-command-result]")).to_be_attached(timeout=10000)
        assert len(sent) == 1
    else:
        expect(phone.locator(EVENT)).not_to_have_class(re.compile(".*swipe-card.*"))
        assert sent == []


def test_reduced_motion_tracks_without_tilt_or_flight(phone, mailhelp):
    phone.emulate_media(reduced_motion="reduce")
    sign_in(phone, mailhelp)
    touch = grab(phone).move(180, -30)
    assert matrix(phone)["angle"] == 0 and abs(matrix(phone)["y"] + 30) < 2
    before = matrix(phone)["x"]
    touch.end()
    assert before == 180
    expect(phone.locator(EVENT + " [data-command-result]")).to_be_attached(timeout=10000)


def test_blocked_elastic_progress_and_one_threshold_pulse(phone, mailhelp):
    sign_in(phone, mailhelp)
    sent = actions(phone)
    touch = grab(phone, QUESTION).move(180, -20)
    state = matrix(phone, QUESTION)
    assert 0 < state["x"] < 32 and abs(state["y"] + 20) < 2 and state["angle"] == 0
    expect(phone.locator(".swipe-symbol")).to_have_text("🔒")
    touch.end()
    expect(phone.locator(".undo-toast")).to_contain_text("Rückfrage")
    assert sent == []
    phone.evaluate("window.__vibrations=[];navigator.vibrate=n=>window.__vibrations.push(n);void 0")
    touch = grab(phone).move(80)
    progress = float(phone.locator(".swipe-backdrop").evaluate("e=>e.style.getPropertyValue('--swipe-progress')"))
    assert 0 < progress < 1
    touch.move(90).move(-80).move(80)
    assert phone.evaluate("window.__vibrations") == [10]
    touch.cancel()


def test_last_decision_shows_empty_state_and_removes_badge(phone, mailhelp):
    from tests.fakes.shared_telegram_dialog import RelevanceHandler

    mailhelp.dialog.relevance_handler = RelevanceHandler(mailhelp.store)
    sign_in(phone, mailhelp)
    phone.evaluate("""() => {
      const old=document.createElement("section");old.className="inbox-zero";old.textContent="Synthetic stale state";
      document.querySelector("main").prepend(old);
      const recent=document.querySelector(".recent");recent.previousElementSibling.remove();recent.remove();
    }""")
    count = phone.locator(".page-heading h1 .count")
    remaining = int(count.inner_text())
    while remaining:
        reject = phone.locator('.open-items input[name="kind"][value="reject"]').first
        if reject.count():
            reject.locator("xpath=..").get_by_role("button", name="Verwerfen", exact=True).click()
        else:
            phone.locator(".open-items").get_by_role("button", name="Irrelevant", exact=True).click()
        remaining -= 1
        expect(count).to_have_text(str(remaining))
    expect(phone.get_by_role("heading", name="Alles erledigt! Keine offenen Entscheidungen.")).to_be_visible()
    expect(phone.locator('.tab-bar a[href="/"] .nav-count')).to_have_count(0)
    expect(phone.locator(".recent")).to_be_visible()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_hint_nudges_once_and_never_submits(page, mailhelp, theme):
    if page.device != "mobile":
        return
    from checks import SCREENSHOTS

    page.emulate_media(color_scheme=theme)
    sign_in(page, mailhelp)
    sent = actions(page)
    # Put the first eligible card fully below the header and above the tab bar.
    page.locator(RELEVANCE).evaluate('e=>e.scrollIntoView({block:"center"})')
    expect(page.locator("[data-swipe-hint]")).to_be_visible()
    page.wait_for_function(
        """selector => {
      const card = document.querySelector(selector);
      return new DOMMatrix(getComputedStyle(card).transform).m41>5;
    }""",
        arg=RELEVANCE,
        timeout=2500,
    )
    shift = matrix(page, RELEVANCE)
    assert 0 < shift["x"] <= 110
    assert phone_width(page) >= page.evaluate("document.documentElement.scrollWidth")
    expect(page.locator(".swipe-backdrop .swipe-text")).to_have_text("Relevant")
    page.screenshot(path=str(SCREENSHOTS / ("swipe69-nudge-" + theme + ".png")))
    expect(page.locator(RELEVANCE)).not_to_have_class(re.compile(".*swipe-card.*"))
    page.evaluate('document.dispatchEvent(new Event("scroll"))')
    page.wait_for_timeout(900)
    assert sent == []
    expect(page.locator(RELEVANCE)).not_to_have_class(re.compile(".*swipe-card.*"))
    page.get_by_role("button", name="Hinweis schließen").click()
    assert page.evaluate('localStorage.getItem("mailhelp-swipe-hint")') == "1"
    page.reload()
    expect(page.locator("[data-swipe-hint]")).to_be_hidden()


def phone_width(page):
    return page.evaluate("document.documentElement.clientWidth")


@pytest.mark.parametrize("mode", ["reduced", "stale", "storage"])
def test_hint_respects_motion_stale_and_storage(page, mailhelp, mode):
    if page.device != "mobile":
        return
    if mode == "reduced":
        page.emulate_media(reduced_motion="reduce")
    if mode == "storage":
        page.add_init_script(
            'Storage.prototype.getItem=()=>{throw Error("synthetic")};'
            'Storage.prototype.setItem=()=>{throw Error("synthetic")}'
        )
    sign_in(page, mailhelp)
    sent = actions(page)
    if mode == "stale":
        page.evaluate('document.dispatchEvent(new Event("mailhelp:stale",{cancelable:true}))')
    page.locator(RELEVANCE).evaluate('e=>e.scrollIntoView({block:"center"})')
    page.wait_for_timeout(1200)
    if mode != "storage":
        assert matrix(page, RELEVANCE)["x"] == 0
    assert sent == []
    page.get_by_role("button", name="Hinweis schließen").click()
    expect(page.locator("[data-swipe-hint]")).to_be_hidden()


def test_hint_waits_while_the_card_is_partly_hidden_and_nudges_once_it_is_whole(page, mailhelp):
    if page.device != "mobile":
        return
    sign_in(page, mailhelp)
    sent = actions(page)
    # A window lower than the card plus tab bar: after 600 ms of quiet the card is still not whole, no nudge.
    size = page.viewport_size
    page.set_viewport_size({"width": size["width"], "height": 420})
    page.locator(RELEVANCE).evaluate('e=>e.scrollIntoView({block:"start"})')
    page.wait_for_timeout(1000)
    assert matrix(page, RELEVANCE)["x"] == 0
    page.set_viewport_size(size)
    page.locator(RELEVANCE).evaluate('e=>e.scrollIntoView({block:"center"})')
    page.wait_for_function(
        "s => new DOMMatrix(getComputedStyle(document.querySelector(s)).transform).m41 > 5",
        arg=RELEVANCE, timeout=2500)
    assert sent == [] and page.errors == []


@pytest.mark.parametrize("width,height", [(390, 844), (360, 740)])
def test_title_metadata_then_actions_and_active_filter_fade(phone, mailhelp, width, height):
    from mailhelp.models import Proposal
    from tests.scenarios.web_scenario import mail_id

    item = mailhelp.store.load_model("proposal-" + mail_id(1) + "-elternabend", Proposal)
    mailhelp.dialog.persist(item.model_copy(update={"title": "<b>Synthetic long title</b> " * 8}))
    mailhelp.site.refresh_overview(force=True)
    phone.set_viewport_size({"width": width, "height": height})
    sign_in(phone, mailhelp)
    for selector in (RELEVANCE, EVENT, f"#v-{mail_id(1)}-formular", QUESTION):
        card = phone.locator(selector)
        card.scroll_into_view_if_needed()
        boxes = card.evaluate("""card=>{
          const title=card.querySelector("h3"), source=card.querySelector(".source");
          const actions=card.querySelector(".actions");
          return {title:title.getBoundingClientRect().bottom,source:source.getBoundingClientRect().top,
            sourceBottom:source.getBoundingClientRect().bottom,actions:actions.getBoundingClientRect().top,
            clamp:getComputedStyle(title).webkitLineClamp};
        }""")
        assert boxes["title"] <= boxes["source"] + 1 and boxes["sourceBottom"] <= boxes["actions"] + 1
        assert boxes["clamp"] == "2"
    assert phone.locator(EVENT + " h3").inner_text().startswith("<b>Synthetic long title</b>")
    assert phone.locator(EVENT + " h3 b").count() == 0
    phone.goto(mailhelp.url + "/?filter=clarification")
    row = phone.locator(".open-toolbar .filter-chips")
    active = row.locator('[aria-current="true"]')
    visible = active.evaluate("""e=>{const a=e.getBoundingClientRect(),p=e.parentElement.getBoundingClientRect();
      return a.left>=p.left-1 && a.right<=p.right+1}""")
    assert visible
    row.evaluate('e=>{e.scrollLeft=0;e.dispatchEvent(new Event("scroll"))}')
    expect(row).to_have_class(re.compile(".*chips-overflow.*"))
    row.evaluate('e=>{e.scrollLeft=e.scrollWidth;e.dispatchEvent(new Event("scroll"))}')
    expect(row).not_to_have_class(re.compile(".*chips-overflow.*"))


def test_filtered_counter_keeps_current_filter_after_decision(phone, mailhelp):
    sign_in(phone, mailhelp)
    phone.goto(mailhelp.url + "/?filter=tasks")
    count = phone.locator(".page-heading h1 .count")
    expect(count).to_have_text("2 von 6")
    phone.locator(".open-items").get_by_role("button", name="Verwerfen", exact=True).first.click()
    expect(count).to_have_text("1 von 5")
    assert phone.url.endswith("?filter=tasks")
    expect(phone.locator('.tab-bar a[href="/"] .nav-count')).to_have_text("5")


@pytest.mark.parametrize("all_blocked", [False, True])
def test_hint_skips_blocked_cards_or_only_shows_the_line(page, mailhelp, all_blocked):
    if page.device != "mobile":
        return
    from mailhelp.models import MailState, Proposal, ProposalStatus
    from tests.scenarios.web_scenario import mail_id

    state = mailhelp.store.load_model("mail-" + mail_id(7), MailState)
    state.awaiting_relevance = False
    state.relevance_dialog = None
    mailhelp.store.save("mail-" + state.id, state.model_dump(mode="json"))
    for row in mailhelp.site.views.overview().open:
        if all_blocked or row.proposal_id == "elternabend":
            item = mailhelp.store.load_model("proposal-" + row.mail_id + "-" + row.proposal_id, Proposal)
            mailhelp.dialog.persist(
                item.model_copy(
                    update={"status": ProposalStatus.NEEDS_CLARIFICATION, "open_questions": ["Synthetic question?"]}
                )
            )
    mailhelp.site.refresh_overview(force=True)
    sign_in(page, mailhelp)
    sent = actions(page)
    expect(page.locator("[data-swipe-hint]")).to_contain_text("nach links: verwerfen")
    if all_blocked:
        page.wait_for_timeout(1300)
        assert page.locator(".swipe-card").count() == 0
    else:
        target = page.locator(f"#v-{mail_id(1)}-formular")
        target.evaluate('e=>e.scrollIntoView({block:"center"})')
        expect(target).to_have_class(re.compile(".*swipe-card.*"), timeout=2500)
        # A real pointer immediately interrupts the presentation and does not decide.
        page.locator("h1").dispatch_event("pointerdown", {"pointerType": "touch", "pointerId": 991})
        expect(target).not_to_have_class(re.compile(".*swipe-card.*"))
    assert sent == []


@pytest.mark.parametrize("fallback", [False, True])
def test_multiple_pointer_samples_write_one_frame_and_use_last_position(phone, mailhelp, fallback):
    if fallback:
        phone.add_init_script(
            'Object.defineProperty(PointerEvent.prototype,"getCoalescedEvents",{configurable:true,value:undefined})'
        )
    sign_in(phone, mailhelp)
    phone.locator(EVENT + " p.source").evaluate('e=>e.scrollIntoView({block:"center"})')
    phone.evaluate(
        """selector=>{
      const card=document.querySelector(selector), source=card.querySelector("p.source");
      const box=source.getBoundingClientRect();
      window.__point={x:90,y:box.y+box.height/2};window.__emit=(type,dx,id=999)=>{
        source.dispatchEvent(new PointerEvent(type,{bubbles:true,pointerType:"touch",pointerId:id,
          clientX:__point.x+dx,clientY:__point.y,isPrimary:true}));
      };
      __emit("pointerdown",0);__emit("pointermove",4);
    }""",
        EVENT,
    )
    phone.wait_for_timeout(40)
    assert phone.locator(".swipe-backdrop").count() == 0
    phone.evaluate('__emit("pointermove",20)')
    expect(phone.locator(".swipe-backdrop")).to_be_visible()
    phone.evaluate(
        """selector=>{
      window.__writes=0;new MutationObserver(records=>window.__writes+=records.length)
        .observe(document.querySelector(selector),{attributes:true,attributeFilter:["style"]});
      __emit("pointermove",30);__emit("pointermove",40);__emit("pointermove",50);
      __emit("pointermove",120,1000);
    }""",
        EVENT,
    )
    phone.wait_for_function(
        """selector => {
      const card = document.querySelector(selector);
      return Math.abs(new DOMMatrix(getComputedStyle(card).transform).m41-50)<1;
    }""",
        arg=EVENT,
    )
    assert phone.evaluate("window.__writes") == 1
    phone.evaluate('__emit("pointercancel",50)')
    expect(phone.locator(".swipe-backdrop")).to_have_count(0)


def test_native_angle_probe_records_the_tested_browser(phone, mailhelp):
    import json

    sign_in(phone, mailhelp)
    observations = {}
    sent = actions(phone)
    for degrees in (35, 40, 44, 45, 46, 50, 55, 60):
        phone.locator(EVENT + " p.source").evaluate('e=>e.scrollIntoView({block:"center"})')
        phone.evaluate(
            'window.__cancelled=false;document.addEventListener("pointercancel",()=>window.__cancelled=true,{once:true})'
        )
        touch = grab(phone).move(120, -120 * math.tan(math.radians(degrees)))
        observations[str(degrees)] = phone.evaluate("window.__cancelled")
        touch.cancel()
        expect(phone.locator(".swipe-backdrop")).to_have_count(0)
    assert observations["35"] is False and observations["60"] is True
    assert sent == []
    print("PAN_Y_MEASUREMENT", json.dumps({"browser": phone.page.context.browser.version, "cancelled": observations}))


def test_regression_background_refresh_cannot_discard_an_accepted_flight(phone, mailhelp, monkeypatch):
    sign_in(phone, mailhelp)
    release = hold(mailhelp, monkeypatch)
    sent = actions(phone)
    try:
        touch = grab(phone).move(180)
        assert phone.evaluate('!document.dispatchEvent(new Event("mailhelp:stale",{cancelable:true}))')
        touch.end()
        assert phone.evaluate('!document.dispatchEvent(new Event("mailhelp:stale",{cancelable:true}))')
        expect(phone.locator(EVENT + " [data-card-command-status]")).to_be_attached()
        assert len(sent) == 1
        release.set()
        expect(phone.locator(EVENT + " [data-command-result]")).to_be_attached(timeout=10000)
    finally:
        release.set()


def test_pointer_release_before_next_frame_and_repeat_during_flight_send_once(phone, mailhelp, monkeypatch):
    sign_in(phone, mailhelp)
    release = hold(mailhelp, monkeypatch)
    sent = actions(phone)
    phone.locator(EVENT + " p.source").evaluate('e=>e.scrollIntoView({block:"center"})')
    try:
        phone.evaluate(
            """selector=>{
          const node=document.querySelector(selector+" p.source"), box=node.getBoundingClientRect();
          const emit=(type,x)=>node.dispatchEvent(new PointerEvent(type,{bubbles:true,pointerType:"touch",
            pointerId:991,clientX:x,clientY:box.y+box.height/2}));
          emit("pointerdown",90);emit("pointermove",175);emit("pointerup",175);
          emit("pointerdown",90);emit("pointermove",270);emit("pointerup",270);
        }""",
            EVENT,
        )
        expect(phone.locator(EVENT + " [data-card-command-status]")).to_be_attached()
        assert len(sent) == 1
        release.set()
        expect(phone.locator(EVENT + " [data-command-result]")).to_be_attached(timeout=10000)
    finally:
        release.set()


def test_regression_steep_start_waits_for_the_browser_instead_of_twitching(phone, mailhelp):
    # The browser scrolls moves steeper than 45° (pointercancel). Starting at 10 px sideways anyway let the
    # card jump for a frame and spring back while the list scrolled. Synthetic events are never cancelled,
    # so the outcome no longer depends on when the native cancel arrives.
    sign_in(phone, mailhelp)
    sent = actions(phone)
    phone.locator(EVENT + " p.source").evaluate('e=>e.scrollIntoView({block:"center"})')
    phone.evaluate(
        """selector=>{
      const node=document.querySelector(selector+" p.source"), box=node.getBoundingClientRect();
      window.emitSwipe=(type,id,x,y)=>node.dispatchEvent(new PointerEvent(type,{bubbles:true,pointerType:"touch",
        pointerId:id,clientX:x,clientY:box.y+box.height/2+y}));
      window.frames2=()=>new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done)));
    }""",
        EVENT,
    )
    # Released before the next frame: the steep move must not start a swipe on the way out either.
    phone.evaluate('emitSwipe("pointerdown",993,120,0);emitSwipe("pointermove",993,108,30);'
                   'emitSwipe("pointerup",993,108,30)')
    assert phone.locator(".swipe-backdrop").count() == 0 and matrix(phone)["x"] == 0
    phone.evaluate('emitSwipe("pointerdown",994,120,0);emitSwipe("pointermove",994,108,18)')
    phone.evaluate("frames2()")
    assert phone.locator(".swipe-backdrop").count() == 0 and matrix(phone)["x"] == 0
    # Once the move is flatter than 45°, it is the card's: it starts and follows both axes.
    phone.evaluate('emitSwipe("pointermove",994,80,20)')
    phone.evaluate("frames2()")
    assert phone.locator(".swipe-backdrop").count() == 1 and abs(matrix(phone)["x"] + 40) < 2
    phone.evaluate('emitSwipe("pointercancel",994,80,20)')
    phone.wait_for_timeout(400)
    assert sent == [] and phone.errors == []


def test_lower_grip_reverses_tilt_and_tall_card_caps_angle(phone, mailhelp):
    sign_in(phone, mailhelp)
    phone.locator(EVENT).evaluate("e=>window.scrollBy(0,e.getBoundingClientRect().bottom-(innerHeight-120))")
    box = phone.locator(EVENT).bounding_box()
    touch = Touch(phone, 90, box["y"] + box["height"] - 10).move(100, 20)
    assert matrix(phone)["angle"] < 0
    assert abs(matrix(phone)["x"] - 100) < 2
    touch.cancel()
    expect(phone.locator(".swipe-backdrop")).to_have_count(0)
    phone.locator(EVENT).evaluate('e=>e.style.minHeight="1000px"')
    touch = grab(phone).move(210, -20)
    assert 3.9 < matrix(phone)["angle"] <= 4.01
    touch.cancel()


def test_regression_pending_hint_does_not_animate_after_resize_to_desktop(page, mailhelp):
    if page.device != "mobile":
        return
    sign_in(page, mailhelp)
    page.evaluate("""()=>{
      window.__wideTransforms=0;
      new MutationObserver(records=>{
        for(const r of records) if(innerWidth>=1024 && r.target.matches("article.card") && r.target.style.transform)
          window.__wideTransforms++;
      }).observe(document.querySelector(".open-items"),{subtree:true,attributes:true,attributeFilter:["style"]});
    }""")
    page.set_viewport_size({"width": 1366, "height": 900})
    page.evaluate(
        """selector=>{
      window.__wideChecks=0;
      const card=document.querySelector(selector), measure=card.getBoundingClientRect.bind(card);
      card.getBoundingClientRect=()=>{window.__wideChecks++;return measure()};
    }""",
        RELEVANCE,
    )
    page.wait_for_timeout(1500)
    assert page.evaluate("window.__wideTransforms") == 0
    assert page.evaluate("window.__wideChecks") == 0


@pytest.mark.parametrize("velocity,share,expected",[(0.89,0.5,False),(0.9,0.5,True),(2,1/3,False)])
def test_exact_momentum_boundary_uses_event_timestamps(phone,mailhelp,velocity,share,expected):
    phone.set_viewport_size({"width":392,"height":844})
    sign_in(phone,mailhelp)
    sent=actions(phone)
    phone.locator(EVENT+" p.source").evaluate('e=>e.scrollIntoView({block:"center"})')
    phone.evaluate("""({selector,velocity,share})=>{
      const card=document.querySelector(selector), node=card.querySelector("p.source");
      const box=node.getBoundingClientRect(), dx=Math.min(card.getBoundingClientRect().width*.4,160)*share;
      const emit=(type,x,t)=>{
        const event=new PointerEvent(type,{bubbles:true,pointerType:"touch",pointerId:992,
          clientX:x,clientY:box.y+box.height/2});
        Object.defineProperty(event,"timeStamp",{value:1000+t});node.dispatchEvent(event);
      };
      emit("pointerdown",90,0);emit("pointermove",90+dx,dx/velocity);emit("pointerup",90+dx,dx/velocity);
    }""",{"selector":EVENT,"velocity":velocity,"share":share})
    if expected:
        expect(phone.locator(EVENT+" [data-command-result]")).to_be_attached(timeout=10000)
        assert len(sent)==1
    else:
        expect(phone.locator(".swipe-backdrop")).to_have_count(0)
        assert sent==[]
