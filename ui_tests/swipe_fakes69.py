"""Native touch sequences and request capture, without external services."""

from urllib.parse import parse_qsl

from tests.scenarios.web_scenario import mail_id

EVENT = f"#v-{mail_id(1)}-elternabend"
QUESTION = f"#v-{mail_id(2)}-zahnarzt"
RELEVANCE = f"#r-{mail_id(7)}"


class Touch:
    def __init__(self, page, x, y):
        self.page, self.x, self.y = page, x, y
        self.send("touchStart", [(x, y)])

    def send(self, kind, points):
        self.page.cdp.send(
            "Input.dispatchTouchEvent",
            {"type": kind, "touchPoints": [{"x": x, "y": y, "id": index} for index, (x, y) in enumerate(points)]},
        )

    def move(self, dx, dy=0, *, steps=8, duration=280):
        x, y = self.x, self.y
        for step in range(1, steps + 1):
            self.x, self.y = x + dx * step / steps, y + dy * step / steps
            self.send("touchMove", [(self.x, self.y)])
            self.page.wait_for_timeout(duration / steps)
        return self

    def end(self):
        self.send("touchEnd", [])

    def cancel(self):
        self.send("touchCancel", [])


def grab(page, selector=EVENT, x=90, part="p.source"):
    target = page.locator(selector + " " + part).first
    target.scroll_into_view_if_needed()
    box = target.bounding_box()
    return Touch(page, x, box["y"] + box["height"] / 2)


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
