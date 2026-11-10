"""5.2 V11: the provider and error matrix of the verification, through every real adapter.

Each provider is the JSON-backed simulation of ``ProviderMemory``; after the one write, the
fresh read of the written entry follows the case. Before 5.2 every case ended as "created"
right after the write answer; now only a passed read does.
"""
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from mailhelp import state_names
from mailhelp.domain.verification import VerificationState
from mailhelp.external.confirmed import execute_confirmed
from mailhelp.models import Proposal, ProposalStatus
from mailhelp.processing.write_verification import WriteVerifications
from mailhelp.storage import JsonStore
from tests.fakes.dav_fakes import multistatus
from tests.fakes.provider_matrix import PROVIDERS, ProviderMemory

BERLIN = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 11, 10, 9, tzinfo=UTC)
CALENDARS = {"google_calendar", "outlook_calendar", "caldav_calendar"}
PROPFIND = multistatus('<d:response><d:href>/synthetic/</d:href><d:propstat><d:prop><d:resourcetype>'
                       '<d:collection/><c:calendar/></d:resourcetype><c:supported-calendar-component-set>'
                       '<c:comp name="VEVENT"/><c:comp name="VTODO"/></c:supported-calendar-component-set>'
                       '</d:prop></d:propstat></d:response>')

# case: (forced answers of the entry read, final state, last error)
CASES = {
    "korrekt": ([], VerificationState.VERIFIED, None),
    "spaeter_sichtbar": ([404, 404], VerificationState.VERIFIED, None),
    "dauerhaft_404": ([404] * 5, VerificationState.NOT_FOUND, "not_visible"),
    "401": ([401], VerificationState.UNAVAILABLE, "access_denied"),
    "403": ([403], VerificationState.UNAVAILABLE, "access_denied"),
    "429": ([429] * 5, VerificationState.UNAVAILABLE, "rate_limited"),
    "5xx": ([503] * 5, VerificationState.UNAVAILABLE, "provider_unavailable"),
    "ungueltig": (["kaputt"], VerificationState.UNAVAILABLE, "invalid_response"),
}


def item(provider):
    common = dict(id="p1", version=1, responsibility="user", certainty="certain", classification="new",
                  evidence="Beleg", source_mail_id="a" * 24, target="synthetic-target", status="confirmed",
                  confirmed_web_actor=None, title="Elternabend Klasse 4b", description="Agenda")
    if provider.startswith(("caldav", "apple")):
        common["target"] = "https://dav.example.test/synthetic/"
    if provider in CALENDARS:
        return Proposal.model_validate({**common, "kind": "event", "start": datetime(2026, 12, 1, 19, tzinfo=BERLIN),
                                        "end": datetime(2026, 12, 1, 21, tzinfo=BERLIN), "location": "Aula"})
    return Proposal.model_validate({**common, "kind": "task", "due": date(2026, 12, 1)})


def entry_read(memory, request):
    path = request.url.path
    if request.method != "GET" or not memory.writes():
        return False
    return path.endswith(".ics") or path.endswith("/created-1")


def forced(status, request):
    if status == "kaputt":
        return httpx.Response(200, content=b"kaputt")
    return httpx.Response(status, json={"error": {"errors": []}})


def run(tmp_path, provider, answers, change=None):
    memory = ProviderMemory(tmp_path / f"{provider}.json", provider)
    queue, original = list(answers), memory.handle

    def handler(request):
        if request.method == "PROPFIND":
            return httpx.Response(207, content=PROPFIND)
        if entry_read(memory, request) and queue:
            return forced(queue.pop(0), request)
        answer = original(request)
        if change is not None and entry_read(memory, request) and answer.status_code == 200:
            return change(answer)
        return answer

    memory.handle = handler
    writer, clock = memory.writer(), [NOW]
    with JsonStore(tmp_path / "data") as store:
        checks = WriteVerifications(store, now=lambda: clock[0])
        proposal = item(provider)

        def persist(value):
            store.save(state_names.proposal(value.source_mail_id, value.id), value.model_dump(mode="json"))

        persist(proposal)
        verifying, _ = execute_confirmed(proposal, writer, persist, verification=checks)
        assert verifying.status == ProposalStatus.VERIFYING
        result, record = checks.check(verifying, writer, persist)
        for delay in (1, 5, 15, 60):
            clock[0] += timedelta(seconds=delay)
            result, record = checks.check(verifying, writer, persist)
        writer.close()
        return memory, result, record


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("case", CASES)
def test_every_provider_and_read_outcome(tmp_path, provider, case):
    answers, state, error = CASES[case]
    memory, result, record = run(tmp_path, provider, answers)
    assert (record.state, record.last_error) == (state, error)
    assert len(memory.writes()) == 1  # never a second write, whatever the read said
    assert result.status == (ProposalStatus.CREATED if state == VerificationState.VERIFIED
                             else ProposalStatus.VERIFYING)


def changed_title(answer):
    text = answer.content.decode()
    for old, new in (("Elternabend Klasse 4b", "Elternabend (verlegt)"),):
        text = text.replace(old, new)
    return httpx.Response(200, content=text.encode(), headers={"Content-Type": answer.headers.get(
        "Content-Type", "application/json")})


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_changed_title_is_a_mismatch_at_every_provider(tmp_path, provider):
    memory, result, record = run(tmp_path, provider, [], change=changed_title)
    assert record.state == VerificationState.MISMATCH and set(record.differences) == {"title"}
    assert record.differences["title"].actual == "Elternabend (verlegt)"
    assert result.status == ProposalStatus.VERIFYING and len(memory.writes()) == 1


@pytest.mark.process
@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("point", ["V1", "V2"])
def test_a_hard_kill_around_the_check_never_writes_twice(tmp_path, provider, point):
    from tests.fakes.safety_harness import ProcessHarness, seed
    from tests.scenarios.web_scenario import mail_id, save_mail
    directory = tmp_path / "app"
    memory = ProviderMemory(tmp_path / "external.json", provider)
    seed(directory)
    record = item(provider).model_copy(update={"id": "action", "source_mail_id": mail_id(1),
                                                "status": ProposalStatus.PENDING_CONFIRMATION})
    with JsonStore(directory) as store:
        save_mail(store, 1, "synthetic@example.test", "Synthetic matrix", [record])
    harness = ProcessHarness(directory, memory.path)
    harness.run(point, mode="provider:" + provider)
    for _ in range(2):
        assert harness.run(mode="provider:" + provider)[0] == "done"
        with JsonStore(directory) as store:
            current = store.load_model(f"proposal-{record.source_mail_id}-action", Proposal)
            assert current.status == ProposalStatus.CREATED and current.external_id
            assert WriteVerifications(store).load(current).state == VerificationState.VERIFIED
            assert len(store.load("action-ledger")["entries"]) == 1
    assert len(memory.writes()) == 1
