from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mailhelp import state_names
from mailhelp.domain.proposal import ProposalKind, ProposalStatus
from mailhelp.models import MailState, Proposal
from mailhelp.review.proposal_evaluation import (
    dismiss_learning_run_hint,
    dismiss_sender_hint,
    get_learning_run_hint,
    list_dismissed_sender_hints,
    restore_sender_hint,
    sender_hint_for_sender,
    sender_hints,
)
from mailhelp.storage import JsonStore


def _save_data(
    store: JsonStore,
    mail_id: str,
    sender: str,
    proposals_info: list[tuple[str, ProposalKind, ProposalStatus, str | None]],
    created_at: datetime,
) -> None:
    mail = MailState(
        id=mail_id,
        config_fingerprint="0" * 64,
        created_at=created_at,
        updated_at=created_at,
        imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 1},
        mail={"headers": {"from": sender, "subject": "Test"}},
        relevance={"decision": "relevant", "topic_ids": ["thema"], "reason": "Relevant"},
    )
    store.save(state_names.mail(mail_id), mail.model_dump(mode="json"))

    for prop_id, kind, status, reject_reason in proposals_info:
        prop = Proposal(
            id=prop_id,
            version=1,
            source_mail_id=mail_id,
            kind=kind,
            responsibility="user",
            certainty="certain",
            classification="new",
            title=f"Proposal {prop_id}",
            evidence="Quelle",
            target="inbox",
            status=status,
            reject_reason=reject_reason,
        )
        store.save(state_names.proposal(mail_id, prop_id), prop.model_dump(mode="json"))


def test_sender_hints_thresholds(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)
    now = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)

    # Sender 1: exactly 4 proposals (below min_proposals=5) -> no hint
    props_s1 = [(f"p1_{i}", ProposalKind.TASK, ProposalStatus.REJECTED, None) for i in range(4)]
    _save_data(store, "1" * 24, "newsletter@example.org", props_s1, now - timedelta(days=5))

    hints = sender_hints(store, now=now, min_proposals=5, max_acceptance_rate=0.10)
    assert len(hints) == 0

    # Sender 2: 5 proposals, 1 confirmed -> rate 20% > 10% -> no hint
    props_s2 = [
        (f"p2_{i}", ProposalKind.TASK, ProposalStatus.CREATED if i == 0 else ProposalStatus.REJECTED, None)
        for i in range(5)
    ]
    _save_data(store, "2" * 24, "partner@example.org", props_s2, now - timedelta(days=5))

    hints = sender_hints(store, now=now, min_proposals=5, max_acceptance_rate=0.10)
    assert len(hints) == 0

    # Sender 3: 5 proposals, 0 confirmed -> rate 0% <= 10% -> hint!
    props_s3 = [
        (f"p3_{i}", ProposalKind.TASK, ProposalStatus.REJECTED, "advertising")
        for i in range(5)
    ]
    _save_data(store, "3" * 24, "spam@promo.com", props_s3, now - timedelta(days=5))

    hints = sender_hints(store, now=now, min_proposals=5, max_acceptance_rate=0.10)
    assert len(hints) == 1
    h = hints[0]
    assert h.sender == "spam@promo.com"
    assert h.total == 5
    assert h.accepted == 0
    assert h.rejected == 5
    assert h.acceptance_rate == 0.0
    assert h.most_frequent_reason == "advertising"
    assert h.recommended_action == "filter"
    assert "5 von 5 Vorschlägen verworfen" in h.trigger_sentence

    # Sender 4: 10 proposals, 1 confirmed -> rate 10% <= 10% -> hint!
    # Most frequent reason: misrecognized -> recommended_action == "rule_learning"
    props_s4 = [
        (f"p4_{i}", ProposalKind.TASK,
         ProposalStatus.CREATED if i == 0 else ProposalStatus.REJECTED,
         "misrecognized" if i > 0 else None)
        for i in range(10)
    ]
    _save_data(store, "4" * 24, "service@cloud.com", props_s4, now - timedelta(days=10))

    hints = sender_hints(store, now=now, min_proposals=5, max_acceptance_rate=0.10)
    assert len(hints) == 2
    h_service = next(hint for hint in hints if hint.sender == "service@cloud.com")
    assert h_service.total == 10
    assert h_service.accepted == 1
    assert h_service.rejected == 9
    assert round(h_service.acceptance_rate, 2) == 0.10
    assert h_service.most_frequent_reason == "misrecognized"
    assert h_service.recommended_action == "rule_learning"


def test_sender_hints_cutoff_and_disabled(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)
    now = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)

    # 5 proposals older than 90 days
    props_old = [(f"p_old_{i}", ProposalKind.TASK, ProposalStatus.REJECTED, None) for i in range(5)]
    _save_data(store, "5" * 24, "old@example.org", props_old, now - timedelta(days=95))

    # 90-day window ignores them
    hints = sender_hints(store, now=now, days=90)
    assert len(hints) == 0

    # 100-day window includes them
    hints_100 = sender_hints(store, now=now, days=100)
    assert len(hints_100) == 1

    # Disabled returns empty
    assert sender_hints(store, now=now, days=100, enabled=False) == []


def test_sender_hints_dismiss_and_restore(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)
    now = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)

    props = [(f"p_{i}", ProposalKind.TASK, ProposalStatus.REJECTED, None) for i in range(5)]
    _save_data(store, "6" * 24, "spam@promo.com", props, now - timedelta(days=2))

    assert list_dismissed_sender_hints(store) == []
    hints = sender_hints(store, now=now)
    assert len(hints) == 1
    assert sender_hint_for_sender(store, "spam@promo.com", now=now) is not None

    # Dismiss hint
    dismiss_sender_hint(store, "spam@promo.com")
    assert list_dismissed_sender_hints(store) == ["spam@promo.com"]
    # Dismissing again is idempotent
    dismiss_sender_hint(store, "spam@promo.com")
    assert list_dismissed_sender_hints(store) == ["spam@promo.com"]

    assert sender_hints(store, now=now) == []
    assert sender_hint_for_sender(store, "spam@promo.com", now=now) is None

    # Restore hint
    restore_sender_hint(store, "spam@promo.com")
    assert list_dismissed_sender_hints(store) == []
    # Restoring non-existent is safe
    restore_sender_hint(store, "other@example.org")

    assert len(sender_hints(store, now=now)) == 1
    assert sender_hint_for_sender(store, "spam@promo.com", now=now) is not None
    assert sender_hint_for_sender(store, "other@example.org", now=now) is None


def test_sender_hints_blocked_sender_excluded(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)
    now = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)

    props = [(f"p_{i}", ProposalKind.TASK, ProposalStatus.REJECTED, None) for i in range(6)]
    _save_data(store, "7" * 24, "blocked@annoying.com", props, now - timedelta(days=2))

    # Excluded via irrelevant-senders store entry
    store.save("irrelevant-senders", {"addresses": ["blocked@annoying.com"]})
    assert sender_hints(store, now=now) == []

    # Also test exclusion via configuration.blocked_senders()
    store.save("irrelevant-senders", {"addresses": []})
    class FakeBlocked:
        addresses = ["blocked@annoying.com"]
    class FakeConfig:
        def blocked_senders(self):
            return FakeBlocked()
    assert sender_hints(store, configuration=FakeConfig(), now=now) == []

    # And when configuration raises an exception
    class BrokenConfig:
        def blocked_senders(self):
            raise RuntimeError("disk error")
    hints_broken = sender_hints(store, configuration=BrokenConfig(), now=now)
    assert len(hints_broken) == 1

    # And when irrelevant-senders is corrupt in store
    store.save("irrelevant-senders", "corrupt-string")
    hints_corrupt = sender_hints(store, now=now)
    assert len(hints_corrupt) == 1


def test_learning_run_hint(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)
    now = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)

    # Disabled
    assert get_learning_run_hint(store, now=now, enabled=False) is None

    # Fewer than 20 rejections
    log_dir = tmp_path / "learning"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "decisions.jsonl"

    lines = []
    for i in range(19):
        lines.append(json.dumps({
            "id": f"d_{i}",
            "kind": "reject",
            "mail_id": f"m_{i}",
            "proposal_id": f"p_{i}",
            "recorded_at": (now - timedelta(days=1)).isoformat(),
        }))
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert get_learning_run_hint(store, now=now, min_rejections=20) is None

    # 20th rejection
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "id": "d_19",
            "kind": "reject",
            "mail_id": "m_19",
            "proposal_id": "p_19",
            "recorded_at": (now - timedelta(days=1)).isoformat(),
        }) + "\n")

    msg = get_learning_run_hint(store, now=now, min_rejections=20)
    assert msg is not None
    assert "20 neue Ablehnungen" in msg

    # Dismiss hint for 7 days
    dismiss_learning_run_hint(store, now=now)
    assert get_learning_run_hint(store, now=now, min_rejections=20) is None
    # 6 days later: still suppressed
    assert get_learning_run_hint(store, now=now + timedelta(days=6), min_rejections=20) is None
    # 8 days later: fires again
    msg_after = get_learning_run_hint(store, now=now + timedelta(days=8), min_rejections=20)
    assert msg_after is not None

    # If rejections are already recorded in rule-learning-history, they don't count as new
    store.save("rule-learning-history", {"decision_ids": [f"d_{i}" for i in range(20)]})
    assert get_learning_run_hint(store, now=now + timedelta(days=8), min_rejections=20) is None
