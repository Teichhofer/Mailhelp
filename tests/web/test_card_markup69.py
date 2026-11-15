"""6.9 card identity, escaped compact metadata and collapsed decision explanations."""

from datetime import UTC, date, datetime

import pytest

from tests.scenarios.web_scenario import mail_id, proposal, save_mail


@pytest.mark.parametrize("kind", ["task", "event", "change"])
def test_card_title_and_compact_metadata_are_escaped_and_precede_actions(web, kind):
    fields = (
        {}
        if kind == "task"
        else {
            "kind": "event",
            "start": datetime(2026, 12, 20, 12, tzinfo=UTC),
            "end": datetime(2026, 12, 20, 13, tzinfo=UTC),
            "location": "<b>Synthetic room</b>",
        }
    )
    if kind == "change":
        fields.update(classification="change", original_date=date(2026, 12, 19), target_event_id="synthetic-existing")
    item = proposal(61, "identity", title="<b>Synthetic identity</b>", **fields)
    save_mail(web.store, 61, "<sender@example.test>", "<b>Synthetic subject</b>", [item])
    web.site.refresh_overview(force=True)
    html = web.browser.request("GET", "/").body.decode()
    start = html.index('id="v-' + mail_id(61) + '-identity"')
    fragment = html[start : html.index("</article>", start)]
    assert "&lt;b&gt;Synthetic identity&lt;/b&gt;" in fragment
    assert "<b>Synthetic identity</b>" not in fragment
    assert fragment.index("<h3>") < fragment.index('class="source"') < fragment.index("decision-bar")
    assert 'class="source-subject"' in fragment and 'class="mobile-card-facts"' in fragment
    assert "sender@example.test" in fragment
    if kind != "task":
        assert "&lt;b&gt;Synthetic room&lt;/b&gt;" in fragment and 'data-fact="Ort"' in fragment
    assert web.writer.created == 0


def test_relevance_help_is_collapsed_without_changing_confirmation_fields(web):
    html = web.browser.request("GET", "/").body.decode()
    start = html.index('id="r-' + mail_id(7) + '"')
    fragment = html[start : html.index("</article>", start)]
    assert ('<details class="decision-help relevance-help"><summary>Was bedeuten diese Entscheidungen?</summary>'
            in fragment)
    assert 'class="decision-help relevance-help" open' not in fragment
    form = web.form("/", decision="relevant")
    assert form["version"] == "1" and form["csrf"] and form["key"]
    assert web.writer.created == 0
