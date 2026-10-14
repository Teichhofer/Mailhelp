"""Compare user data and interaction targets independently of decorative HTML."""
from html.parser import HTMLParser


class ContentContract(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_main = False
        self.ignored = None
        self.text = []
        self.targets = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "main":
            self.in_main = True
        if not self.in_main:
            return
        if set(values.get("class", "").split()) & {"eyebrow", "page-intro", "context-label"}:
            self.ignored = tag
        targets = {key: value for key, value in attrs if key in {"id", "href", "action", "name", "value", "for"}}
        if targets:
            self.targets.append([tag, targets])

    def handle_endtag(self, tag):
        if tag == self.ignored:
            self.ignored = None
        if tag == "main":
            self.in_main = False

    def handle_data(self, value):
        if self.in_main and self.ignored is None:
            self.text.append(value)


def content_contract(html):
    parser = ContentContract()
    parser.feed(html)
    return {"text": " ".join(" ".join(parser.text).split()), "targets": parser.targets}
