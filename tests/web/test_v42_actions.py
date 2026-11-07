"""Authenticated, versioned local closure and minimal status polling."""
import json

from mailhelp.models import ProposalStatus
from mailhelp.review.results import ReviewResult
from tests.fakes.shared_web_actions import web as web
from tests.fakes.shared_web_auth import Browser
from tests.fakes.web_routes import action_id, progress_link


def test_already_done_form_checks_csrf_and_version_and_reports_a_positive_local_closure(web):
    rejected_before = web.site.views.system().proposals.get(ProposalStatus.REJECTED, 0)
    fields = web.form("/", kind="already_done", proposal_id="elternabend")
    assert web.submit({**fields, "csrf": "wrong"}).status == 403
    assert web.submit({**fields, "version": "0"}).status == 422
    response = web.submit(fields)
    assert web.submit(fields).headers["Location"] == response.headers["Location"]
    progress = web.browser.request("GET", response.headers["Location"]).body.decode()
    assert "Wird verarbeitet" in progress and "Die Anlage im Ziel" not in progress
    web.run()
    assert web.writer.created == 0 and web.writer.reconciled == 0
    assert "Schon erledigt" in web.browser.request("GET", "/").body.decode()
    status = web.browser.request("GET", "/status").body.decode()
    assert "Schon erledigt" in status and "Wartezeit bis Beginn" in status
    reports = web.browser.request("GET", "/berichte").body.decode()
    assert "Schon erledigt: 1" in reports and f"Verworfen: {rejected_before}" in reports


def test_status_endpoint_reads_only_the_command_and_redirects_after_completion(web, monkeypatch):
    response = web.submit(web.form("/", kind="already_done", proposal_id="formular"))
    location = response.headers["Location"]
    entry_id = action_id(location)
    api = f"/api/aktion/{entry_id}"
    def forbidden(*args, **kwargs):
        raise AssertionError("Minimal command status must not rebuild views")
    monkeypatch.setattr(web.site.views, "overview", forbidden)
    monkeypatch.setattr(web.site.views, "system", forbidden)
    monkeypatch.setattr(web.site.views, "proposal", forbidden)
    result = web.browser.request("GET", api, accept="application/json")
    assert result.status == 200 and json.loads(result.body) == {"status": "queued", "target": None}
    web.commands.finish(entry_id, ReviewResult(status="done", message="synthetic"))
    assert json.loads(web.browser.request("GET", api).body) == {"status": "done", "target": progress_link(location)}
    assert web.browser.request("GET", "/api/aktion/" + "0" * 32).status == 404
    stranger = Browser(web.app)
    assert stranger.request("GET", api, accept="application/json").status == 401


def test_command_page_has_lightweight_polling_and_a_no_javascript_fallback(web):
    response = web.submit(web.form("/", kind="confirm", proposal_id="elternabend"))
    page = web.browser.request("GET", progress_link(response.headers["Location"])).body.decode()
    assert 'data-command-status="/api/aktion/' in page
    assert '<noscript><meta http-equiv="refresh" content="1"></noscript>' in page
    assert "Wird ausgeführt … Danach geht es automatisch zur Übersicht." in page
    assert "Kalender" in page and "Mail analysiert" not in page
    response = web.submit(web.form("/", kind="confirm", proposal_id="formular"))
    assert "Todoist" in web.browser.request("GET", progress_link(response.headers["Location"])).body.decode()


def test_a_session_revoked_after_submission_cannot_close_the_proposal(web):
    response = web.submit(web.form("/", kind="already_done", proposal_id="formular"))
    entry_id = action_id(response.headers["Location"])
    web.auth.revoke_all()
    assert web.browser.request("GET", f"/api/aktion/{entry_id}", accept="application/json").status == 401
    web.run()
    assert web.commands.get(entry_id).result.status == "unauthorized"
    assert web.writer.created == 0
