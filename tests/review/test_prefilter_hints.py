"""7.7.5: suggested prefilter rules and the prefilter figures of /auswertung (Planung 7.7, 3.8, 3.9)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mailhelp.domain.relevance import IrrelevantSenders, PrefilterHits, Relevance, RelevanceDialog, RuleHits, SenderRule
from mailhelp.mailbox.sender_filter import LISTS
from mailhelp.persistence.storage import JsonStore
from mailhelp.processing.perspective import SELF_NOTE_REASON
from mailhelp.review.prefilter_hints import PrefilterHint, prefilter_hints
from mailhelp.web.prefilter_stats import avoided, category, estimate, prefilter_section
from tests.fakes.factories import build_mail_state
from tests.fakes.shared_core import proposal

NOW = datetime(2026, 11, 17, 12, tzinfo=UTC)
IRRELEVANT = Relevance(decision="irrelevant", topic_ids=[], reason="Werbung")
RELEVANT = Relevance(decision="relevant", topic_ids=[], reason="Schule")


def save(store, number, sender, relevance=IRRELEVANT, *, age_days=1, status=None, **changes):
    items = [proposal(source_mail_id=f"{number:024x}", status=status)] if status else []
    state = build_mail_state(f"{number:024x}", sender=sender, subject=f"Mail {number}", proposals=items,
                             relevance=relevance, updated=NOW - timedelta(days=age_days - 1), **changes)
    store.save(f"mail-{number:024x}", state.model_dump(mode="json"))


@pytest.fixture
def store(tmp_path):
    with JsonStore(tmp_path) as opened:
        yield opened


def test_repeatedly_irrelevant_senders_become_ignore_hints_and_two_of_a_domain_the_domain(store):
    for number in range(1, 4):
        save(store, number, "News <news@shop.test>")
        save(store, 10 + number, "Deals <deals@shop.test>")
        save(store, 20 + number, "Freund <freund@gmail.com>")
        save(store, 30 + number, "Freundin <freundin@gmail.com>")
    hints = prefilter_hints(store, IrrelevantSenders(), NOW)
    assert hints[0] == PrefilterHint("ignore", "domain", "shop.test", 6, ("Mail 11", "Mail 12", "Mail 13"))
    assert {(hint.kind, hint.value) for hint in hints} == {
        ("domain", "shop.test"), ("address", "news@shop.test"), ("address", "deals@shop.test"),
        ("address", "freund@gmail.com"), ("address", "freundin@gmail.com")}


def test_a_hint_needs_enough_recent_model_decisions_and_no_rule_or_answer(store):
    save(store, 1, "a@one.test")
    save(store, 2, "a@one.test")
    for number in range(3, 6):
        save(store, number, "b@two.test")
    save(store, 6, "b@two.test", age_days=40)
    for number in range(7, 10):
        save(store, number, "c@three.test", prefilter_rule="0" * 16 if number == 7 else None)
    for number in range(10, 13):
        save(store, number, "d@four.test", relevance_dialog=RelevanceDialog(
            mail_id=f"{number:024x}", status="decided", decision="irrelevant", telegram_offset=1) if number == 10 else None)
    for number in range(13, 16):
        save(store, number, "e@five.test", relevance=IRRELEVANT if number < 15 else RELEVANT)
    for number in range(16, 19):
        save(store, number, "f@six.test", relevance=Relevance(decision="irrelevant", topic_ids=[],
                                                               reason="Vorfilter: six.test" if number == 16 else "x"))
    for number in range(19, 22):
        save(store, number, "g@seven.test")
        save(store, 30 + number, "h@eight.test")
        save(store, 40 + number, "i@nine.test")
    store.save("mail-damaged-index", {"kaputt": True})
    store.save("mail-" + "f" * 24, {"schema_version": 9, "kaputt": True})
    save(store, 90, None)
    save(store, 91, "x@a.test, y@b.test")
    blocked = IrrelevantSenders(addresses=["g@seven.test"], rules=[SenderRule(
        id=SenderRule.identity("address", "h@eight.test", 2), kind="address", value="h@eight.test",
        action="allow_only", mailbox=2, created_at=NOW)], mailboxes={"2": {"allow": []}})
    hints = prefilter_hints(store, blocked, NOW, dismissed=["i@nine.test"])
    assert [hint.value for hint in hints] == ["b@two.test"]
    assert prefilter_hints(store, blocked, NOW, enabled=False) == []
    assert [hint.value for hint in prefilter_hints(store, blocked, NOW, irrelevant_mails=2)][-1] == "a@one.test"


def test_senders_whose_mails_were_all_confirmed_become_vip_hints(store):
    for number in range(1, 6):
        save(store, number, "lehrerin@schule.test", RELEVANT, status="created" if number % 2 else "simulated")
        save(store, 10 + number, "verein@sport.test", RELEVANT, status="created" if number < 5 else "rejected")
    hints = prefilter_hints(store, IrrelevantSenders(), NOW)
    assert hints == [PrefilterHint("vip", "address", "lehrerin@schule.test", 5, ("Mail 1", "Mail 2", "Mail 3"))]
    assert prefilter_hints(store, IrrelevantSenders(), NOW, vip_mails=6) == []


# --- figures --------------------------------------------------------------------------------------

def test_the_reason_of_each_avoided_call_is_counted(store):
    save(store, 1, "a@b.test", RELEVANT, prefilter_rule="1" * 16)
    save(store, 2, "a@b.test", prefilter_rule="2" * 16)
    save(store, 3, "a@b.test", prefilter_rule=LISTS)
    save(store, 4, "a@b.test", Relevance(decision="irrelevant", topic_ids=[], reason="Eigenes Postfach-Briefing"))
    save(store, 5, "a@b.test", Relevance(decision="relevant", topic_ids=[], reason=SELF_NOTE_REASON))
    save(store, 6, "a@b.test")
    save(store, 7, "a@b.test", prefilter_rule="3" * 16, age_days=60)
    save(store, 8, "a@b.test", relevance=None)
    store.save("mail-" + "f" * 24, {"schema_version": 9, "kaputt": True})
    assert dict(avoided(store, NOW - timedelta(days=30))) == {"vip": 1, "rule": 1, "header": 1, "briefing": 1,
                                                                "self_mail": 1}
    assert category(build_mail_state(relevance=None)) is None


def record(stage="relevance", provider="openrouter", cost="0.0011", tokens=(1000, 200), duration=2000, age=1):
    return {"stage": stage, "provider": provider, "cost_usd": cost, "duration_ms": duration, "power_watts": 300,
            "electricity_price": 0.35, "started_at": (NOW - timedelta(days=age)).isoformat(),
            "tokens": {"prompt_tokens": tokens[0], "completion_tokens": tokens[1]}}


def test_the_saving_is_estimated_from_real_relevance_calls_only():
    since = NOW - timedelta(days=30)
    assert estimate([record(stage="summary"), record(age=40)], since, 1.1) is None
    cloud = estimate([record(), record(cost="0.0033", tokens=(3000, None))], since, 1.1)
    assert cloud == {"tokens": 2100.0, "euros": pytest.approx(0.002), "priced": 2.0}
    local = estimate([record(provider="ollama", cost=None, duration=3_600_000)], since, None)
    assert local["euros"] == pytest.approx(0.105)
    assert estimate([record(cost=None)], since, 1.1) == {"tokens": 1200.0, "euros": 0.0, "priced": 0.0}


def test_the_section_shows_the_counts_the_estimate_the_busiest_and_unused_rules(store):
    old = NOW - timedelta(days=120)
    used = SenderRule(id=SenderRule.identity("pattern", "no-reply@*", None), kind="pattern", value="no-reply@*",
                      created_at=old)
    unused = SenderRule(id=SenderRule.identity("domain", "alt.test", None), kind="domain", value="alt.test",
                        created_at=old)
    blocked = IrrelevantSenders(rules=[used, unused], addresses=["a@b.test"])
    hits = PrefilterHits(rules={used.id: RuleHits(count=7, last=NOW), LISTS: RuleHits(count=2, last=NOW),
                                SenderRule.identity("address", "a@b.test", None): RuleHits(count=1, last=old),
                                "9" * 16: RuleHits(count=1, last=old)})
    save(store, 1, "x@y.test", prefilter_rule=used.id)
    html = prefilter_section(store, [record()], blocked, hits, NOW, 30, 1.1)
    assert "Ohne Relevanzprüfung entschieden: 1 Mails." in html and "etwa 1200 Tokens und 0,00 €" in html
    assert "<li>no-reply@*: 7</li>" in html and "<li>Newsletter und Verteiler: 2</li>" in html
    assert "<li>a@b.test: 1</li>" in html and f"<li>{'9' * 16}: 1</li>" in html
    assert "Seit 90 Tagen ohne Treffer" in html and "<li>alt.test</li>" in html
    empty = prefilter_section(store, [], IrrelevantSenders(), PrefilterHits(), NOW, 30, 1.1)
    assert "Ersparnis nicht schätzbar" in empty and "Regeln mit den meisten Treffern" not in empty
    assert "ohne Treffer" not in empty


def test_each_kind_of_hint_is_worded_and_carries_its_rule():
    from mailhelp.web.proposal_evaluation_pages import prefilter_hints_section
    assert prefilter_hints_section([], "c") == ""
    html = prefilter_hints_section([PrefilterHint("vip", "address", "lehrerin@schule.test", 5, ("Elternabend",)),
                                    PrefilterHint("ignore", "domain", "shop.test", 6, ())], "c")
    assert "5 Mails von lehrerin@schule.test führten jeweils zu bestätigten Vorschlägen. Als VIP einstufen?" in html
    assert "Adressen der Domain shop.test" in html and '<li>Elternabend</li>' in html
    assert '<input type="hidden" name="aktion" value="vip">' in html
    assert '<input type="hidden" name="art" value="domain">' in html
