"""Deterministic prefilter for untrusted RFC 5322 sender headers."""
from __future__ import annotations

from email.utils import getaddresses

from .models import IrrelevantSenders


def sender_addresses(header: object) -> set[str]:
    """Extract conservative, normalized mailbox addresses from an untrusted header."""
    result: set[str] = set()
    for _display_name, address in getaddresses([str(header)]):
        normalized = address.strip().casefold()
        if (normalized.count("@") == 1 and not any(character.isspace() for character in normalized)
                and not any(character in normalized for character in "<>") and normalized[0] != "@"
                and not normalized.endswith("@")):
            result.add(normalized)
    return result


def is_irrelevant_sender(header: object, blocked: IrrelevantSenders) -> bool:
    """Match an exact mailbox or its whole domain without using message content."""
    addresses = sender_addresses(header)
    return bool(addresses.intersection(blocked.addresses) or any(
        address.rsplit("@", 1)[1].rstrip(".") in blocked.domains for address in addresses
    ))


def add_irrelevant_senders(blocked: IrrelevantSenders, headers: list[object]) -> IrrelevantSenders:
    """Return a validated list extended by every syntactically usable address."""
    additions = set().union(*(sender_addresses(header) for header in headers)) if headers else set()
    return blocked.model_copy(update={"addresses": sorted(set(blocked.addresses) | additions)})
