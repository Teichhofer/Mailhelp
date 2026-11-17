"""Deterministic prefilter for untrusted RFC 5322 sender headers.

7.7: one evaluator (``prefilter``) decides for every caller – pipeline, image recognition, decision
test, learning mode, activity report and web – so a rule has the same effect everywhere.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from email.utils import getaddresses
from typing import Literal

from ..domain.relevance import HeaderPrefilter, IrrelevantSenders, ListSignals, SenderRule, SenderRules, subject_key
from ..persistence.storage import JsonStore, atomic_replace

HeaderMode = Literal["off", "trial", "on"]
# Rule ids of the two header filters; rule ids of sender rules are 16 hex digits.
AUTOMATED, LISTS = "header-automated", "header-lists"


@dataclass(frozen=True)
class PrefilterMatch:
    """What decided a mail before any model call: ``ignore`` → irrelevant, ``vip`` → relevant."""

    action: Literal["ignore", "vip"]
    rule_id: str
    reason: str
    topic_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Rule:
    id: str
    action: str
    kind: str
    value: str
    subdomains: bool
    topic_ids: tuple[str, ...] = ()


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


def wildcard(pattern: str, text: str) -> bool:
    """``*`` stands for any text; linear in the text, no regular expression (no ReDoS)."""
    if "*" not in pattern:
        return pattern == text
    first, *middle, last = pattern.split("*")
    if len(text) < len(first) + len(last) or not text.startswith(first) or not text.endswith(last):
        return False
    position, end = len(first), len(text) - len(last)
    for segment in middle:
        found = text.find(segment, position, end)
        if found < 0:
            return False
        position = found + len(segment)
    return True


def _legacy(kind: str, values: Iterable[str], mailbox: int | None, action: str = "ignore") -> list[_Rule]:
    # Schema 2 entries keep their meaning: an exact domain never covers its subdomains.
    return [_Rule(SenderRule.identity(kind, value, mailbox), action, kind, value, False) for value in values]


def active_rules(blocked: IrrelevantSenders, mailbox: int) -> list[_Rule]:
    """The simple lists and the enabled rules that apply to one mailbox."""
    scope = blocked.mailboxes.get(str(mailbox), SenderRules())
    rules = (_legacy("address", blocked.addresses, None) + _legacy("domain", blocked.domains, None)
             + _legacy("address", scope.addresses, mailbox) + _legacy("domain", scope.domains, mailbox)
             + _legacy("address", scope.allow, mailbox, "allow_only"))
    rules += [_Rule(rule.id, rule.action, rule.kind, rule.value, rule.subdomains, tuple(rule.topic_ids))
              for rule in blocked.rules if rule.enabled and rule.mailbox in {None, mailbox}]
    return rules


def _matches(rule: _Rule, address: str) -> bool:
    domain = address.rsplit("@", 1)[1].rstrip(".")
    if rule.kind == "address":
        return address == rule.value
    if rule.kind == "domain":
        return domain == rule.value or (rule.subdomains and domain.endswith("." + rule.value))
    return wildcard(rule.value, address)


def _label(rule: _Rule) -> str:
    return f"„{rule.value}“" if rule.kind == "subject" else rule.value


def header_match(signals: ListSignals | None, headers: HeaderPrefilter,
                 modes: frozenset[HeaderMode] = frozenset({"on"})) -> PrefilterMatch | None:
    """The header filters in the given modes; ``{"trial"}`` counts what a trial would filter."""
    if signals is None:
        return None
    if headers.automated in modes and (signals.auto_submitted not in {"", "no"}
                                       or signals.precedence in {"bulk", "junk", "list"}):
        return PrefilterMatch("ignore", AUTOMATED, "Vorfilter: automatische Systemmail")
    listed = signals.list_unsubscribe or signals.list_id != ""
    if headers.lists in modes and listed and signals.list_id not in headers.list_exceptions:
        return PrefilterMatch("ignore", LISTS, "Vorfilter: Newsletter oder Verteiler")
    return None


def prefilter(sender: object, subject: str, signals: ListSignals | None, blocked: IrrelevantSenders,
              mailbox: int = 1) -> PrefilterMatch | None:
    """The first deciding rule: VIP before every ignore rule, an exception lifts every ignore rule."""
    addresses = sender_addresses(sender)
    rules = active_rules(blocked, mailbox)
    for rule in rules:
        if rule.action == "vip" and any(_matches(rule, address) for address in addresses):
            return PrefilterMatch("vip", rule.id, f"VIP-Absender: {_label(rule)}", rule.topic_ids)
    allowed = {address for address in addresses
               if any(rule.action == "allow_only" and _matches(rule, address) for rule in rules)}
    if addresses and allowed == addresses:
        return None
    remaining, key = addresses - allowed, subject_key(subject)
    for rule in rules:
        if rule.action != "ignore":
            continue
        if (key and rule.value in key) if rule.kind == "subject" else any(
                _matches(rule, address) for address in remaining):
            return PrefilterMatch("ignore", rule.id, f"Vorfilter: {_label(rule)}")
    return header_match(signals, blocked.headers)


def is_irrelevant_sender(header: object, blocked: IrrelevantSenders, mailbox_id: int = 1) -> bool:
    """Match the sender rules alone, without using message content."""
    match = prefilter(header, "", None, blocked, mailbox_id)
    return match is not None and match.action == "ignore"


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
                              domains: list[str], mailbox_id: int | None = None, *,
                              allow: bool = False) -> IrrelevantSenders:
    """Add or remove entries idempotently; the result is validated and sorted."""
    def changed(current: list[str], entries: list[str]) -> list[str]:
        return sorted(set(current) | set(entries) if add else set(current) - set(entries))

    if mailbox_id is None:
        return blocked.model_copy(update={"addresses": changed(blocked.addresses, addresses),
                                           "domains": changed(blocked.domains, domains)})
    rules = blocked.mailboxes.get(str(mailbox_id), SenderRules())
    patch = {"allow": changed(rules.allow, addresses)} if allow else {
        "addresses": changed(rules.addresses, addresses), "domains": changed(rules.domains, domains)}
    updated = SenderRules.model_validate({**rules.model_dump(), **patch})
    return blocked.model_copy(update={"mailboxes": {**blocked.mailboxes, str(mailbox_id): updated}})


def save_sender_filter(store: JsonStore, blocked: IrrelevantSenders) -> None:
    """Before an older schema is replaced for the first time, it is kept as ``….json.v<n>``."""
    with store.locked():
        previous = store.load("irrelevant-senders", {})
        path = store.directory / "irrelevant-senders.json"
        version = previous.get("schema_version")
        backup = path.with_name(f"irrelevant-senders.json.v{version}")
        if version in {1, 2} and not backup.exists():
            atomic_replace(backup, path.read_text(encoding="utf-8"))
        store.save("irrelevant-senders", blocked.model_dump(mode="json"))
