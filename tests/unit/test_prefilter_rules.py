"""7.7.1: sender rules, header signals and the one evaluator every caller uses (Planung 7.7, 3.1–3.6)."""
from __future__ import annotations

import itertools
import json
import time
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from mailhelp.config import Topic
from mailhelp.domain.relevance import HeaderPrefilter, IrrelevantSenders, ListSignals, SenderRule, SenderRules
from mailhelp.mailbox.imap import FetchedMail
from mailhelp.mailbox.mime import MimeLimits, extract_list_signals
from mailhelp.mailbox.sender_filter import (
    AUTOMATED,
    LISTS,
    header_match,
    is_irrelevant_sender,
    prefilter,
    save_sender_filter,
    sender_addresses,
    wildcard,
)
from mailhelp.persistence.storage import JsonStore
from mailhelp.processing.orchestrator import Orchestrator
from tests.fakes.shared_services import AnalyzerStub, Notify

NOW = datetime(2026, 11, 17, 12, tzinfo=UTC)


def rule(kind, value, action="ignore", mailbox=None, **fields):
    return SenderRule(id=SenderRule.identity(kind, value, mailbox), kind=kind, value=value, action=action,
                      mailbox=mailbox, created_at=NOW, **fields)


def senders(*rules, headers=None, **lists):
    return IrrelevantSenders(rules=list(rules), headers=headers or HeaderPrefilter(), **lists)


# --- models ---------------------------------------------------------------------------------------

@pytest.mark.parametrize(("kind", "value"), [
    ("address", "news@shop.test"), ("domain", "shop.test"), ("pattern", "no-reply@*"),
    ("pattern", "*@mail.shop.test"), ("pattern", "noreply*@*.shop.test"), ("subject", "automatische antwort:"),
])
def test_valid_rules(kind, value):
    assert rule(kind, value).id == SenderRule.identity(kind, value, None)


@pytest.mark.parametrize(("kind", "value"), [
    ("address", "News@Shop.test"), ("address", "kein-at"), ("domain", "-shop.test"), ("pattern", "news@shop.test"),
    ("pattern", "*@*"), ("pattern", "a*b*c*d*@x.test"), ("pattern", "(a+)+@x.test"), ("subject", "Großbuchstaben"),
    ("subject", "zwei  leerzeichen"),
])
def test_invalid_values_are_refused(kind, value):
    with pytest.raises(ValidationError, match="Ungültiger Wert"):
        rule(kind, value)


def test_rule_consistency_is_enforced():
    with pytest.raises(ValidationError, match="nur aussortieren"):
        rule("subject", "angebot", action="vip")
    with pytest.raises(ValidationError, match="Themen"):
        rule("address", "a@b.test", topic_ids=["schule"])
    with pytest.raises(ValidationError, match="Regelkennung"):
        SenderRule(id="0" * 16, kind="address", value="a@b.test", created_at=NOW)
    with pytest.raises(ValidationError, match="nur einmal"):
        senders(rule("address", "a@b.test"), rule("address", "a@b.test", action="vip"))
    assert rule("address", "a@b.test", mailbox=2).id != rule("address", "a@b.test").id
    with pytest.raises(ValidationError, match="Verteiler-Ausnahmen"):
        HeaderPrefilter(list_exceptions=["B", "a"])
    with pytest.raises(ValidationError, match="Verteiler-Ausnahmen"):
        HeaderPrefilter(list_exceptions=[""])


def test_schema_1_and_2_documents_become_schema_3_without_loss():
    for version in (1, 2):
        document = {"schema_version": version, "addresses": ["a@b.test"], "domains": ["shop.test"]}
        if version == 2:
            document["mailboxes"] = {"2": {"addresses": ["c@d.test"], "domains": [], "allow": ["e@shop.test"]}}
        upgraded = IrrelevantSenders.model_validate(document)
        assert upgraded.schema_version == 3 and upgraded.rules == [] and upgraded.headers == HeaderPrefilter()
        assert upgraded.addresses == ["a@b.test"] and upgraded.domains == ["shop.test"]
        assert upgraded.mailboxes == ({"2": SenderRules(addresses=["c@d.test"], allow=["e@shop.test"])}
                                      if version == 2 else {})


# --- the evaluator --------------------------------------------------------------------------------

def _old_is_irrelevant_sender(header, blocked, mailbox_id=1):
    """The evaluator of 7.6 (schema 2), kept here verbatim to prove identical behaviour."""
    addresses = sender_addresses(header)
    rules = blocked.mailboxes.get(str(mailbox_id))
    allowed = set(rules.allow) if rules is not None else set()
    denied = set(blocked.addresses) | (set(rules.addresses) if rules is not None else set())
    domains = set(blocked.domains) | (set(rules.domains) if rules is not None else set())
    addresses -= allowed
    return bool(addresses.intersection(denied) or any(
        address.rsplit("@", 1)[1].rstrip(".") in domains for address in addresses))


def test_migrated_lists_decide_exactly_as_before():
    """Acceptance 7.7 (5.3): exact domains and ``allow`` exceptions keep their meaning."""
    lists = [
        IrrelevantSenders(),
        IrrelevantSenders(addresses=["a@shop.test"], domains=["shop.test"]),
        IrrelevantSenders(domains=["shop.test"],
                          mailboxes={"2": SenderRules(allow=["a@shop.test"], domains=["other.test"])}),
        IrrelevantSenders(mailboxes={"1": SenderRules(addresses=["b@other.test"], allow=["b@other.test"])}),
    ]
    headers = ["a@shop.test", "x@mail.shop.test", "b@other.test", "A <a@shop.test>, c@free.test",
               "kaputt", "", "y@shop.test.", "a@shop.test, b@other.test"]
    for blocked, header, mailbox in itertools.product(lists, headers, (1, 2)):
        assert is_irrelevant_sender(header, blocked, mailbox) == _old_is_irrelevant_sender(header, blocked, mailbox), (
            blocked, header, mailbox)


def test_vip_comes_before_every_ignore_rule_and_brings_its_topics():
    blocked = senders(rule("domain", "schule.test"), rule("subject", "elternbrief"),
                      rule("address", "lehrer@schule.test", action="vip", topic_ids=["schule"]),
                      headers=HeaderPrefilter(lists="on"), domains=["schule.test"])
    match = prefilter("Lehrer <lehrer@schule.test>", "Elternbrief", ListSignals(list_id="x"), blocked)
    assert match.action == "vip" and match.topic_ids == ("schule",)
    assert match.reason == "VIP-Absender: lehrer@schule.test" and match.rule_id == blocked.rules[2].id
    other = prefilter("sekretariat@schule.test", "Hallo", None, blocked)
    assert other.action == "ignore" and other.reason == "Vorfilter: schule.test"


def test_new_domains_cover_subdomains_unless_told_otherwise():
    assert prefilter("x@mail.shop.test", "", None, senders(rule("domain", "shop.test"))).action == "ignore"
    exact = senders(rule("domain", "shop.test", subdomains=False))
    assert prefilter("x@mail.shop.test", "", None, exact) is None
    assert prefilter("x@shop.test", "", None, exact) is not None
    assert prefilter("x@othershop.test", "", None, senders(rule("domain", "shop.test"))) is None


def test_patterns_subjects_mailboxes_and_disabled_rules():
    blocked = senders(rule("pattern", "no-reply@*"), rule("subject", "automatische antwort:"),
                      rule("address", "a@b.test", mailbox=2), rule("address", "c@d.test", enabled=False))
    assert prefilter("No-Reply@Bank.test", "", None, blocked).reason == "Vorfilter: no-reply@*"
    assert prefilter("x@y.test", "AW: Automatische  Antwort: Urlaub", None, blocked).reason == (
        "Vorfilter: „automatische antwort:“")
    assert prefilter("x@y.test", "", None, blocked) is None
    assert prefilter("a@b.test", "", None, blocked, 1) is None
    assert prefilter("a@b.test", "", None, blocked, 2) is not None
    assert prefilter("c@d.test", "", None, blocked) is None


def test_an_exception_lifts_every_ignore_rule_and_the_header_filters():
    blocked = senders(rule("address", "a@shop.test", action="allow_only"), rule("subject", "angebot"),
                      headers=HeaderPrefilter(automated="on"), domains=["shop.test"])
    signals = ListSignals(auto_submitted="auto-generated")
    assert prefilter("a@shop.test", "Angebot", signals, blocked) is None
    assert prefilter("b@shop.test", "", None, blocked).action == "ignore"
    # With a second, not excepted sender the ignore rules apply to that one.
    assert prefilter("a@shop.test, b@shop.test", "", None, blocked).action == "ignore"


@pytest.mark.parametrize(("signals", "expected"), [
    (ListSignals(auto_submitted="auto-replied"), AUTOMATED), (ListSignals(auto_submitted="no"), None),
    (ListSignals(precedence="bulk"), AUTOMATED), (ListSignals(precedence="first-class"), None),
    (ListSignals(list_unsubscribe=True), LISTS), (ListSignals(list_id="<news.shop.test>"), LISTS),
    (ListSignals(list_id="<eltern.schule.test>"), None), (ListSignals(), None), (None, None),
])
def test_header_filters(signals, expected):
    on = HeaderPrefilter(automated="on", lists="on", list_exceptions=["<eltern.schule.test>"])
    match = prefilter("x@y.test", "", signals, senders(headers=on))
    assert (match.rule_id if match else None) == expected
    if match:
        assert match.reason.startswith("Vorfilter: ")


def test_header_filters_are_off_by_default_and_a_trial_never_decides():
    signals = ListSignals(list_unsubscribe=True, auto_submitted="auto-generated")
    assert prefilter("x@y.test", "", signals, senders()) is None
    trial = HeaderPrefilter(automated="trial", lists="trial")
    assert prefilter("x@y.test", "", signals, senders(headers=trial)) is None
    assert header_match(signals, trial, frozenset({"trial"})).rule_id == AUTOMATED
    assert header_match(ListSignals(list_id="x"), trial, frozenset({"trial"})).rule_id == LISTS


@pytest.mark.parametrize(("pattern", "text", "expected"), [
    ("no-reply@*", "no-reply@bank.test", True), ("no-reply@*", "noreply@bank.test", False),
    ("*@mail.shop.test", "a@mail.shop.test", True), ("*@mail.shop.test", "a@shop.test", False),
    ("a*b*c@x", "abc@x", True), ("a*b*c@x", "acb@x", False), ("a*b*c@x", "a-x-c@x", False), ("a*b*c@x", "a-b-c@x", True), ("a*b*c@x", "ab-c@x", True),
    ("ab*ba@x", "aba@x", False), ("exact@x", "exact@x", True), ("exact@x", "other@x", False),
    ("a*z@x", "a@x", False),
])
def test_wildcards(pattern, text, expected):
    assert wildcard(pattern, text) is expected


def test_a_hostile_pattern_stays_linear():
    started = time.perf_counter()
    assert not wildcard("a*a*a*b@x", "a" * 100_000 + "@x")
    assert time.perf_counter() - started < 0.5


# --- header signals and storage --------------------------------------------------------------------

def test_list_signals_are_read_from_a_bounded_header_block():
    raw = (b"From: Shop <news@shop.test>\r\nList-Id: <News.Shop.test>\r\nList-Unsubscribe: <https://x>\r\n"
           b"Precedence: Bulk\r\nAuto-Submitted: auto-generated\r\n\r\nText")
    assert extract_list_signals(raw, 10_000) == {"list_id": "<news.shop.test>", "list_unsubscribe": True,
                                                 "precedence": "bulk", "auto_submitted": "auto-generated"}
    assert extract_list_signals(b"From: a@b.test\n\nText", 10_000) == {
        "list_id": "", "list_unsubscribe": False, "precedence": "", "auto_submitted": ""}
    assert extract_list_signals(b"From: a@b.test", 10_000) == {}
    assert extract_list_signals(b"From: " + b"a" * 200 + b"\n\nText", MimeLimits(10_000, max_header_bytes=50)) == {}


def test_the_pipeline_keeps_the_signals_beside_the_mail_not_inside_it(tmp_path):
    raw = (b"From: Shop <news@shop.test>\nSubject: Angebot\nList-Unsubscribe: <https://x>\n"
           b"Message-ID: <signals@example.test>\n\nText")
    with JsonStore(tmp_path) as store:
        result = Orchestrator(AnalyzerStub("irrelevant"), store, Notify(), 1,
                              [Topic(id="x", name="X", enabled=True, description="X")], 1000,
                              ).process(FetchedMail("INBOX", 1, 7, raw))
        state = result.state
    assert state["list_signals"] == {"list_id": "", "list_unsubscribe": True, "precedence": "",
                                     "auto_submitted": ""}
    assert "list" not in json.dumps(state["mail"]["headers"])


@pytest.mark.parametrize("version", [1, 2])
def test_the_older_schema_is_kept_once_before_schema_3_is_written(tmp_path, version):
    with JsonStore(tmp_path) as store:
        store.save("irrelevant-senders", {"schema_version": version, "addresses": ["a@b.test"]})
        save_sender_filter(store, IrrelevantSenders(addresses=["a@b.test", "c@d.test"]))
        backup = tmp_path / f"irrelevant-senders.json.v{version}"
        assert json.loads(backup.read_text(encoding="utf-8"))["schema_version"] == version
        save_sender_filter(store, IrrelevantSenders(addresses=["a@b.test"]))
        assert json.loads(backup.read_text(encoding="utf-8"))["addresses"] == ["a@b.test"]
        assert store.load("irrelevant-senders")["schema_version"] == 3
        assert sorted(path.name for path in tmp_path.glob("irrelevant-senders.json.v*")) == [backup.name]
