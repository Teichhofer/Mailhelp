"""Native touch sequences and request capture, without external services."""

import time
from urllib.parse import parse_qsl

from tests.scenarios.web_scenario import mail_id

EVENT = f"#v-{mail_id(1)}-elternabend"
QUESTION = f"#v-{mail_id(2)}-zahnarzt"
RELEVANCE = f"#r-{mail_id(7)}"


class Touch:
    """With *exact*, every event carries a timestamp from a virtual clock (7.0.15): the gaps the page
    measures are exactly the requested durations, however long the CDP round trips take."""

    def __init__(self, page, x, y, *, exact=False):
        self.page, self.x, self.y = page, x, y
        self.clock = time.time() if exact else None
        self.send("touchStart", [(x, y)])

    def send(self, kind, points):
        event = {"type": kind, "touchPoints": [{"x": x, "y": y, "id": index} for index, (x, y) in enumerate(points)]}
        if self.clock is not None:
            event["timestamp"] = self.clock
        self.page.cdp.send("Input.dispatchTouchEvent", event)

    def pause(self, milliseconds):
        if self.clock is not None:
            self.clock += milliseconds / 1000
        self.page.wait_for_timeout(milliseconds)
        return self

    def move(self, dx, dy=0, *, steps=8, duration=280):
        x, y = self.x, self.y
        for step in range(1, steps + 1):
            self.x, self.y = x + dx * step / steps, y + dy * step / steps
            self.send("touchMove", [(self.x, self.y)])
            self.pause(duration / steps)
        return self

    def end(self):
        self.send("touchEnd", [])

    def cancel(self):
        self.send("touchCancel", [])


def grab(page, selector=EVENT, x=90, part="p.source", *, exact=False):
    target = page.locator(selector + " " + part).first
    target.scroll_into_view_if_needed()
    box = target.bounding_box()
    return Touch(page, x, box["y"] + box["height"] / 2, exact=exact)


def matrix(page, selector=EVENT):
    return page.locator(selector).evaluate("""card => {
      const m = new DOMMatrix(getComputedStyle(card).transform);
      return {x:m.m41, y:m.m42, angle:Math.atan2(m.b,m.a)*180/Math.PI};
    }""")


def actions(page):
    sent = []
    page.on(
        "request",
        lambda r: sent.append(dict(parse_qsl(r.post_data)))
        if r.method == "POST" and r.url.endswith("/aktion")
        else None,
    )
    return sent
