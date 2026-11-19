"""8.0: an event proposal is bound to its hosted Google connection, not only to "google"."""
from datetime import UTC, datetime

from mailhelp.config import TargetSettings
from mailhelp.domain.proposal import (
    Proposal,
    ProposalCertainty,
    ProposalClassification,
    ProposalKind,
    ProposalResponsibility,
    ProposalStatus,
)
from mailhelp.external.confirmed import execute_confirmed
from mailhelp.external.roles import provider_key
from mailhelp.proposals.integrations import HttpWriter

CONNECTION = "a" * 32


def event(binding):
    return Proposal(id="p", version=1, kind=ProposalKind.EVENT, responsibility=ProposalResponsibility.USER,
                    certainty=ProposalCertainty.CERTAIN, classification=ProposalClassification.NEW,
                    title="Elternabend", evidence="x", source_mail_id="b" * 24, target="primary",
                    target_provider=binding, status=ProposalStatus.CONFIRMED,
                    start=datetime(2026, 12, 1, 18, tzinfo=UTC), end=datetime(2026, 12, 1, 19, tzinfo=UTC))


def test_the_binding_names_the_hosted_connection():
    hosted = TargetSettings(google_calendar="primary", todoist_project="inbox", google_connection=CONNECTION)
    assert hosted.calendar_binding == "google-" + "a" * 16
    assert TargetSettings(google_calendar="primary", todoist_project="inbox").calendar_binding == "google"
    assert TargetSettings(calendar_provider="outlook", todoist_project="inbox").calendar_binding == "outlook"


def test_a_confirmation_for_another_account_never_writes_through_the_new_connection():
    writer = HttpWriter("google_calendar", "token", "primary", calendar_timezone="Europe/Berlin")
    assert provider_key(writer) == "google"
    writer.binding = "google-" + "a" * 16
    assert provider_key(writer) == "google-" + "a" * 16
    for earlier in ("google", "google-" + "b" * 16):  # direct access, or another hosted connection
        proposal, result = execute_confirmed(event(earlier), writer, lambda _: None, authorize=lambda: True)
        assert result == {"target_mismatch": True} and proposal.status == ProposalStatus.CONFIRMED
