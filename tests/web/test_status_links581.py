"""Status tiles lead to the records counted, without executing an action."""
import pytest

from mailhelp.configuration import AdminCommand, AdminKind
from mailhelp.review.inbox import CommandStatus
from mailhelp.review.results import ResultStatus, ReviewResult
from tests.fakes.shared_web_actions import web as web
from tests.fakes.shared_web_auth import Browser
from tests.scenarios.web_scenario import mail_id

TARGETS = {"Offene Vorschläge": "/status/vorschlaege", "Relevanzfragen": "/status/relevanzfragen",
           "Mails mit Fehler": "/mails?state=failed", "Wartende Web-Aktionen": "/status/web-aktionen"}


def test_status_tiles_are_real_links_to_their_own_overviews(web):
    html = web.browser.request("GET", "/status").body.decode()
    for label, target in TARGETS.items():
        assert f'href="{target}"' in html and label in html


@pytest.mark.parametrize("path", TARGETS.values())
def test_status_targets_require_authentication(web, path):
    assert Browser(web.app).request("GET", path).status == 303


def test_proposals_and_relevance_are_shown_separately(web):
    proposals = web.browser.request("GET", "/status/vorschlaege")
    relevance = web.browser.request("GET", "/status/relevanzfragen")
    assert proposals.status == relevance.status == 200
    assert "Elternabend Klasse 4b" in proposals.body.decode()
    assert 'id="r-' not in proposals.body.decode()
    assert 'id="r-' in relevance.body.decode() and "Elternabend Klasse 4b" not in relevance.body.decode()
    assert web.writer.created == 0


@pytest.mark.parametrize("path", ["/status/vorschlaege", "/status/relevanzfragen", "/status/web-aktionen"])
def test_empty_status_pages_stay_useful_after_a_restart(web, tmp_path, path):
    from mailhelp.storage import JsonStore
    from tests.fakes.shared_web_actions import Web
    with JsonStore(tmp_path / "empty") as store:
        first = Web(store)
        assert "Aktuell keine Einträge" in first.browser.request("GET", path).body.decode()
    with JsonStore(tmp_path / "empty") as store:
        restarted = Web(store)
        html = restarted.browser.request("GET", path).body.decode()
        assert "Aktuell keine Einträge" in html and "Übersicht aktualisieren" in html
        assert restarted.writer.created == 0


def test_queued_entries_are_listed_without_execution_and_finished_entries_disappear(web):
    fields = web.form("/", kind="confirm", proposal_id="elternabend")
    web.submit(fields)
    queued = web.commands.queued()[0]
    before = web.store.revision
    html = web.browser.request("GET", "/status/web-aktionen").body.decode()
    assert f'href="/aktion/{queued.id}"' in html and "1 wartende Web-Aktionen" in html
    assert "Wartende Aktion ansehen" in html
    assert web.commands.get(queued.id).status == CommandStatus.QUEUED
    assert web.store.revision == before and web.writer.created == 0
    assert web.browser.request("GET", "/status/web-aktionen").body.decode() == html
    web.commands.start(queued.id)
    assert "Aktuell keine Einträge" in web.browser.request("GET", "/status/web-aktionen").body.decode()
    web.commands.finish(queued.id, ReviewResult(status=ResultStatus.DONE, message="Synthetisch erledigt"))
    assert "Aktuell keine Einträge" in web.browser.request("GET", "/status/web-aktionen").body.decode()


def test_foreign_queued_actions_are_counted_but_their_private_content_is_not_exposed(web):
    command = AdminCommand(kind=AdminKind.SENDERS, actor="web:" + "f" * 16, idempotency_key="foreign-queue-key",
                           patch={"private": "private-synthetic-value"})
    entry, _ = web.commands.submit(command)
    html = web.browser.request("GET", "/status/web-aktionen").body.decode()
    assert "1 wartende Web-Aktionen" in html and "Aktion einer anderen Sitzung" in html
    assert entry.id not in html and "private-synthetic-value" not in html


def test_failed_mail_tile_shows_only_failed_mails(web):
    from datetime import UTC, datetime

    from mailhelp.models import MailState, ProcessingError
    state = web.store.load_model("mail-" + mail_id(7), MailState)
    state.error = ProcessingError(code="llm_rate_limited", stage="summary", retryable=True,
                                  occurred_at=datetime.now(UTC))
    web.store.save("mail-" + mail_id(7), state.model_dump(mode="json"))
    html = web.browser.request("GET", "/mails?state=failed").body.decode()
    assert 'href="/mail/' + mail_id(7) in html
    assert 'href="/mail/' + mail_id(1) not in html
    status = web.browser.request("GET", "/status").body.decode()
    assert 'href="/mails?state=failed"><strong>1</strong>' in status


def test_invalid_status_subpage_is_not_a_public_catchall(web):
    assert web.browser.request("GET", "/status/unknown").status == 404
