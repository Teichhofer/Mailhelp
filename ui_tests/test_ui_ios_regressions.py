"""iPhone regressions checked with WebKit as well as Chromium."""

import pytest
from playwright.sync_api import expect

from conftest import DEVICES, Page
from conftest import sign_in as measured_sign_in
from swipe_fakes69 import EVENT


@pytest.fixture(params=["chromium", "webkit"])
def ios_page(request, browser_runtime):
    browser = getattr(browser_runtime, request.param).launch(
        **({"channel": "chrome", "args": ["--js-flags=--no-compilation-cache"]} if request.param == "chromium" else {})
    )
    context = browser.new_context(**DEVICES["mobile"], locale="de-DE", service_workers="block")
    raw = context.new_page()
    page = Page(raw, "mobile") if request.param == "chromium" else raw
    page.add_init_script('localStorage.setItem("mailhelp-swipe-hint","1")')
    try:
        yield page
    finally:
        if request.param == "chromium":
            page.collect()
        context.close()
        browser.close()


def sign_in(page, mailhelp):
    page.goto(f"{mailhelp.url}/anmelden")
    page.get_by_role("button", name="Code per Telegram senden").click()
    expect(page.get_by_label("Code aus Telegram")).to_be_visible()
    page.get_by_label("Code aus Telegram").fill(mailhelp.pairing_code())
    page.get_by_role("button", name="Gerät koppeln").click()
    page.wait_for_url(f"{mailhelp.url}/")


@pytest.mark.parametrize("release_x,move_x,release_dy", [(270, 150, 0), (210, 150, 0), (270, 270, 2)])
def test_ios_swipe_submits_the_original_confirm_form(ios_page, mailhelp, release_x, move_x, release_dy):
    page = ios_page
    errors, sent = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "request",
        lambda request: sent.append(request.post_data)
        if request.method == "POST" and request.url.endswith("/aktion")
        else None,
    )
    sign_in(page, mailhelp)
    page.locator(EVENT + " p.source").scroll_into_view_if_needed()
    page.evaluate(
        """({selector,releaseX,moveX,releaseDy}) => {
      const node=document.querySelector(selector+' p.source'), box=node.getBoundingClientRect();
      const emit=(type,x,t,dy=0)=>{
        const event=new PointerEvent(type,{bubbles:true,pointerId:991,pointerType:'touch',
          isPrimary:true,clientX:x,clientY:box.top+4+dy});
        Object.defineProperty(event,'timeStamp',{value:1000+t});node.dispatchEvent(event);
      };
      emit('pointerdown',30,0); emit('pointermove',moveX,300); emit('pointerup',releaseX,320,releaseDy);
    }""",
        {"selector": EVENT, "releaseX": release_x, "moveX": move_x, "releaseDy": release_dy},
    )
    expect(page.locator(EVENT + " [data-command-result]")).to_be_attached(timeout=10000)
    assert len(sent) == 1 and errors == []


def test_ios_status_navigation_stays_at_the_visible_bottom(ios_page, mailhelp):
    page = ios_page
    sign_in(page, mailhelp)
    page.locator(".tab-more summary").click()
    page.locator('.tab-menu a[href="/status"]').click()
    page.wait_for_url(mailhelp.url + "/status")
    # Isolate the bottom bar from a composited/scrolled header's containing block.
    page.locator("header.top").evaluate("e=>e.style.transform='translateZ(0)'")
    for share in [0, 0.3, 0.7, 1, 0]:
        page.evaluate("share=>scrollTo(0,share*(document.documentElement.scrollHeight-innerHeight))", share)
        page.wait_for_timeout(100)
        box = page.locator(".tab-bar").bounding_box()
        assert abs(box["y"] + box["height"] - page.evaluate("innerHeight")) < 2
        expect(page.locator('.tab-bar a[href="/"]')).to_be_in_viewport()


def test_ios_navigation_recovers_from_a_drifting_fixed_layer(ios_page, mailhelp):
    page = ios_page
    sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/status")
    # Fault injection: WebKit's async fixed-layer drift leaves bottom:0 above the visual bottom.
    page.locator(".tab-bar").evaluate("e=>e.style.bottom='180px'")
    page.evaluate("scrollTo(0,200);dispatchEvent(new Event('scroll'))")
    page.wait_for_function(
        """() => {
      const box=document.querySelector('.tab-bar').getBoundingClientRect(), view=visualViewport;
      return Math.abs(box.bottom-(view.offsetTop+view.height))<2;
    }""",
        timeout=2000,
    )
    for y in [500, 0]:
        page.evaluate("y=>scrollTo(0,y)", y)
        page.wait_for_timeout(100)
        box = page.locator(".tab-bar").bounding_box()
        assert abs(box["y"] + box["height"] - page.evaluate("visualViewport.offsetTop+visualViewport.height")) < 2


@pytest.mark.parametrize(
    "dx,dy,fingers,blocked", [(80, 10, 1, True), (0, 80, 1, False), (5, 0, 1, False), (80, 10, 2, False)]
)
def test_native_scroll_cannot_take_over_a_horizontal_swipe(ios_page, mailhelp, dx, dy, fingers, blocked):
    page = ios_page
    sign_in(page, mailhelp)
    page.locator(EVENT + " p.source").scroll_into_view_if_needed()
    prevented = page.evaluate(
        """({selector,dx,dy,fingers})=>{
      const node=document.querySelector(selector+' p.source'), box=node.getBoundingClientRect();
      node.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerType:'touch',
        pointerId:992,clientX:80,clientY:box.top+4}));
      const event=new Event('touchmove',{bubbles:true,cancelable:true});
      Object.defineProperty(event,'touches',{value:Array.from({length:fingers},()=>({clientX:80+dx,clientY:box.top+4+dy}))});
      node.dispatchEvent(event);
      node.dispatchEvent(new PointerEvent('pointercancel',{bubbles:true,pointerId:992,pointerType:'touch'}));
      return event.defaultPrevented;
    }""",
        {"selector": EVENT, "dx": dx, "dy": dy, "fingers": fingers},
    )
    assert prevented is blocked


def test_navigation_viewport_recovery_resize_and_focus_clearance(page, mailhelp):
    measured_sign_in(page, mailhelp)
    page.goto(mailhelp.url + "/status")
    page.set_viewport_size({"width": 390, "height": 844})
    bar = page.locator(".tab-bar")
    assert bar.evaluate("e=>e.parentElement===document.body")
    bar.evaluate("e=>e.style.bottom='180px'")
    page.evaluate("""scrollTo(0,200);dispatchEvent(new Event('scroll'));
        dispatchEvent(new Event('scroll'));visualViewport.dispatchEvent(new Event('resize'));
        visualViewport.dispatchEvent(new Event('scroll'));""")
    expect(bar).to_have_css("position", "absolute")
    for share in [0.25, 1, 0]:
        page.evaluate("s=>scrollTo(0,s*(document.documentElement.scrollHeight-innerHeight))", share)
        page.wait_for_function("""() => Math.abs(document.querySelector('.tab-bar')
          .getBoundingClientRect().bottom-(visualViewport.offsetTop+visualViewport.height))<2""")
    page.locator("main a").last.scroll_into_view_if_needed()
    page.locator("main a").last.focus()
    assert page.locator("main a").last.bounding_box()["y"] < bar.bounding_box()["y"]
    page.set_viewport_size({"width": 1366, "height": 900})
    expect(bar).to_be_hidden()
    page.wait_for_function("() => document.querySelector('.tab-bar').style.position === ''")
    page.set_viewport_size({"width": 390, "height": 844})
    expect(bar).to_have_css("position", "fixed")


def test_navigation_without_visual_viewport_keeps_css_fallback(page, mailhelp):
    page.add_init_script("Object.defineProperty(window,'visualViewport',{value:undefined})")
    measured_sign_in(page, mailhelp)
    page.set_viewport_size({"width": 390, "height": 844})
    expect(page.locator(".tab-bar")).to_have_css("position", "fixed")
    assert page.errors == []
