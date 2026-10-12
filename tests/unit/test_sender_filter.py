import pytest
from pydantic import ValidationError

from mailhelp.models import IrrelevantSenders
from mailhelp.sender_filter import add_irrelevant_senders, is_irrelevant_sender, sender_addresses


def test_sender_extraction_exact_domain_and_learning():
    assert sender_addresses("Alice <ALICE@Example.Test>, bad address, <@broken>") == {
        "alice@example.test"
    }
    blocked = IrrelevantSenders(
        addresses=["exact@elsewhere.test"], domains=["example.test"]
    )
    assert is_irrelevant_sender("Alice <alice@example.test>", blocked)
    assert is_irrelevant_sender("exact@elsewhere.test", blocked)
    assert not is_irrelevant_sender("person@allowed.test", blocked)
    learned = add_irrelevant_senders(
        blocked, ["New <NEW@Allowed.Test>", "new@allowed.test", "invalid"]
    )
    assert learned.addresses == ["exact@elsewhere.test", "new@allowed.test"]
    assert add_irrelevant_senders(blocked, []) == blocked


@pytest.mark.parametrize("values", [
    {"addresses": ["UPPER@example.test"]},
    {"addresses": ["bad address@example.test"]},
    {"addresses": ["a@example.test", "a@example.test"]},
    {"domains": ["UPPER.test"]},
    {"domains": ["-bad.test"]},
    {"domains": ["example.test", "example.test"]},
])
def test_sender_list_rejects_noncanonical_entries(values):
    with pytest.raises(ValidationError):
        IrrelevantSenders(**values)
