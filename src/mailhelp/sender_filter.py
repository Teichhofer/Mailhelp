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


def is_irrelevant_sender(header: object, blocked: IrrelevantSenders, mailbox_id: int = 1) -> bool:
    """Match an exact mailbox or its whole domain without using message content."""
    addresses = sender_addresses(header)
    rules = blocked.mailboxes.get(str(mailbox_id))
    allowed = set(rules.allow) if rules is not None else set()
    denied = set(blocked.addresses) | (set(rules.addresses) if rules is not None else set())
    domains = set(blocked.domains) | (set(rules.domains) if rules is not None else set())
    addresses -= allowed
    return bool(addresses.intersection(denied) or any(
        address.rsplit("@", 1)[1].rstrip(".") in domains for address in addresses
    ))


def add_irrelevant_senders(blocked: IrrelevantSenders, headers: list[object]) -> IrrelevantSenders:
    """Return a validated list extended by every syntactically usable address."""
    additions = set().union(*(sender_addresses(header) for header in headers)) if headers else set()
    return blocked.model_copy(update={"addresses": sorted(set(blocked.addresses) | additions)})


def sender_entry(text: str) -> tuple[str, str]:
    """Normalize one manually entered address or domain; ``ValueError`` if unusable."""
    value = text.strip()
    if "@" in value:
        addresses = sender_addresses(value)
        if len(addresses) != 1:
            raise ValueError("Bitte genau eine gültige E-Mail-Adresse angeben")
        address = addresses.pop()
        IrrelevantSenders(addresses=[address])
        return "address", address
    domain = value.casefold().rstrip(".")
    IrrelevantSenders(domains=[domain])
    return "domain", domain


def change_irrelevant_senders(blocked: IrrelevantSenders, add: bool, addresses: list[str],
                              domains: list[str], mailbox_id: int | None = None, *, allow=False) -> IrrelevantSenders:
    """Add or remove entries idempotently; the result is validated and sorted."""
    def changed(current: list[str], entries: list[str]) -> list[str]:
        return sorted(set(current) | set(entries) if add else set(current) - set(entries))

    if mailbox_id is None:
        return blocked.model_copy(update={"addresses": changed(blocked.addresses, addresses),
                                           "domains": changed(blocked.domains, domains)})
    from .domain.relevance import SenderRules
    rules = blocked.mailboxes.get(str(mailbox_id), SenderRules())
    patch = {"allow": changed(rules.allow, addresses)} if allow else {
        "addresses": changed(rules.addresses, addresses), "domains": changed(rules.domains, domains)}
    updated = SenderRules.model_validate({**rules.model_dump(), **patch})
    return blocked.model_copy(update={"mailboxes": {**blocked.mailboxes, str(mailbox_id): updated}})


def save_sender_filter(store, blocked: IrrelevantSenders) -> None:
    from .storage import atomic_replace
    with store.locked():
        previous = store.load("irrelevant-senders", {})
        path = store.directory / "irrelevant-senders.json"
        backup = path.with_name("irrelevant-senders.json.v1")
        if previous.get("schema_version") == 1 and not backup.exists():
            atomic_replace(backup, path.read_text(encoding="utf-8"))
        store.save("irrelevant-senders", blocked.model_dump(mode="json"))
