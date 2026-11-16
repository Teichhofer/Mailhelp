"""Saved reply drafts remain readable and copyable without another mailbox write."""
from types import SimpleNamespace

import pytest

from tests.fakes.shared_web_actions import MAIL1


@pytest.mark.parametrize("status,label", [
    ("saved", "Als Entwurf im Postfach abgelegt"),
    ("simulated", "Speicherung im Testmodus simuliert"),
    ("editing", "Bitte prüfen"),
    ("uncertain", "Schreibresultat unklar"),
])
def test_reply_preview_on_mail_and_proposal_pages(web, status, label):
    text = 'Danke.\n<script>alert("untrusted")</script> & Grüße'
    draft = {"version": 1, "status": status, "text": text, "auto": True}
    web.site.experience.drafts = SimpleNamespace(available=lambda _: True, get=lambda _: draft)
    for path in (f"/mail/{MAIL1}", f"/vorschlag/{MAIL1}/elternabend"):
        response = web.browser.request("GET", path)
        html = response.body.decode()
        assert response.status == 200 and label in html
        assert "&lt;script&gt;" in html and '<script>alert("untrusted")</script>' not in html
        assert 'data-copy-draft' in html and 'data-copy-status' in html
        assert 'Danke.\n&lt;script&gt;' in html
        if status in {"saved", "simulated"}:
            assert 'id="draft-preview"' in html and 'readonly' in html
            assert 'name="mode" value="save"' not in html


def test_scrubbed_and_discarded_drafts_have_no_copy_button(web):
    for status in ("saved", "discarded"):
        web.site.experience.drafts = SimpleNamespace(
            available=lambda _: True, get=lambda _, status=status: {"version": 1, "status": status, "text": ""})
        assert 'data-copy-draft' not in web.browser.request("GET", f"/mail/{MAIL1}").body.decode()
    web.auth.revoke_all()
    assert web.browser.request("GET", f"/mail/{MAIL1}").status == 303
