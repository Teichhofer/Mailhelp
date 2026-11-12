"""Shared authenticated rule-learning fixture and its two-step web actions."""
import pytest

from tests.fakes.rule_learning import RuleHarness, record
from tests.fakes.topic_forms import hidden


@pytest.fixture
def page(web, tmp_path):
    harness = RuleHarness(tmp_path, web.store, web.dialog.review.web_authorizer)
    web.site.rule_learning.service = harness.service
    session = web.auth.sessions()[0]
    return web, harness, session


def form(page, action="analyze", **changes):
    web, harness, session = page
    state = harness.service.state("web:" + session.id)
    return {"csrf": web.auth.csrf_token(session.id), "key": "browser-key-" + str(state.version),
            "version": str(state.version), "action": action, "confirm": "yes", **changes}


def analyze(page, scope="all"):
    # 5.7.6: "all" re-uses decisions of an earlier analysis; "new" would find none left.
    web, harness, _session = page
    harness.log(record())
    fields = form(page, scope=scope)
    assert web.browser.request("POST", "/lernen/entscheidungen", fields).status == 303
    assert harness.service.tick()


def choice_form(page, **changes):
    return form(page, "apply", **{"selected-0": "yes", "id-0": "school", "name-0": "Von Hand",
        "description-0": "Manuell korrigiert", "examples-0": "Eigener Fall", "exclusions-0": "Kein Newsletter",
        "enabled-0": "true", **changes})


def post_choice(page, fields):
    """5.8: the edited values are previewed, then that persisted snapshot is confirmed."""
    web, _, _ = page
    preview = web.browser.request("POST", "/lernen/entscheidungen", {**fields, "action": "preview"})
    if preview.status != 200:
        return preview
    confirmation = hidden(preview.body.decode(), "/lernen/entscheidungen")
    return web.browser.request("POST", "/lernen/entscheidungen", {**fields, **confirmation,
                                                                  "confirm": fields.get("confirm", "")})
