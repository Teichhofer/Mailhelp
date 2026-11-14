"""Tests for proposal evaluation and acceptance rate calculation (Planung 6.5, 3.1)."""
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from mailhelp import state_names
from mailhelp.domain.proposal import DuplicateMatchInfo, DuplicateSource, ProposalKind, ProposalStatus
from mailhelp.models import MailState, Proposal
from mailhelp.review.proposal_evaluation import (
    collect_decided_proposals,
    evaluate_proposals,
)
from mailhelp.storage import JsonStore


def _make_mail(mid: str, sender: str = "alice@example.com", topic_ids: list[str] | None = None, now: datetime | None = None) -> MailState:
    t = now or datetime.now(UTC)
    return MailState(
        id=mid,
        config_fingerprint="0" * 64,
        created_at=t,
        updated_at=t,
        imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 1},
        mail={"headers": {"from": sender, "subject": "Test"}},
        relevance={"decision": "relevant", "topic_ids": topic_ids or ["schule"], "reason": "Relevant"},
    )


def _make_proposal(
    mail_id: str,
    prop_id: str,
    kind: ProposalKind,
    status: ProposalStatus,
    resolution: str | None = None,
    now: datetime | None = None,
) -> Proposal:
    now = now or datetime.now(UTC)
    extra = {}
    if kind == ProposalKind.EVENT:
        extra["start"] = now
        extra["end"] = now + timedelta(hours=1)
    if status == ProposalStatus.ALREADY_EXISTS:
        extra["duplicate_match"] = DuplicateMatchInfo(
            source=DuplicateSource.ACTION_LEDGER,
            matched_title="Existing Event",
            matched_time=now,
        )
    return Proposal(
        id=prop_id,
        version=1,
        source_mail_id=mail_id,
        kind=kind,
        responsibility="user",
        certainty="certain",
        classification="new",
        title="Test Proposal",
        evidence="Quelle",
        target="inbox",
        status=status,
        resolution=resolution,
        **extra,
    )


def test_empty_store_returns_empty_evaluation(tmp_path: Path):
    store = JsonStore(tmp_path)
    report = evaluate_proposals(store)
    assert report.empty
    assert report.summary.total_decided == 0
    assert report.summary.total_accepted == 0
    assert report.summary.total_rejected == 0
    assert report.summary.total_quote == 0.0
    assert report.weeks == []
    assert report.topics == []
    assert report.senders == []
    assert report.reasons == []


def test_evaluation_matches_production_baseline_numbers(tmp_path: Path):
    """Verify against the numbers in Planung-6.5.md: 249 decided, 50 accepted (11 tasks, 39 events), 199 rejected."""
    store = JsonStore(tmp_path)
    now = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)

    # 1. 11 accepted tasks
    for i in range(11):
        mid = f"{i + 1:024x}"
        pid = f"p-task-acc-{i:03d}"
        mail = _make_mail(mid, sender=f"sender-task-acc-{i % 3}@example.com", topic_ids=["schule"], now=now)
        store.save(state_names.mail(mid), mail.model_dump(mode="json"))
        prop = _make_proposal(mid, pid, ProposalKind.TASK, ProposalStatus.CREATED, now=now)
        store.save(state_names.proposal(mid, pid), prop.model_dump(mode="json"))

    # 2. 94 rejected tasks (5 of which have resolution="already_done")
    for i in range(94):
        mid = f"{i + 100:024x}"
        pid = f"p-task-rej-{i:03d}"
        resolution = "already_done" if i < 5 else None
        mail = _make_mail(mid, sender=f"sender-task-rej-{i % 5}@example.com", topic_ids=["sport"], now=now)
        store.save(state_names.mail(mid), mail.model_dump(mode="json"))
        prop = _make_proposal(mid, pid, ProposalKind.TASK, ProposalStatus.REJECTED, resolution=resolution, now=now)
        store.save(state_names.proposal(mid, pid), prop.model_dump(mode="json"))

    # 3. 39 accepted events (some SIMULATED, CONFIRMED, CREATED)
    statuses = [ProposalStatus.CREATED, ProposalStatus.CONFIRMED, ProposalStatus.SIMULATED]
    for i in range(39):
        mid = f"{i + 300:024x}"
        pid = f"p-event-acc-{i:03d}"
        mail = _make_mail(mid, sender=f"sender-event-acc-{i % 4}@example.com", topic_ids=["arbeit"], now=now)
        store.save(state_names.mail(mid), mail.model_dump(mode="json"))
        prop = _make_proposal(mid, pid, ProposalKind.EVENT, statuses[i % len(statuses)], now=now)
        store.save(state_names.proposal(mid, pid), prop.model_dump(mode="json"))

    # 4. 105 rejected events
    for i in range(105):
        mid = f"{i + 500:024x}"
        pid = f"p-event-rej-{i:03d}"
        mail = _make_mail(mid, sender=f"sender-event-rej-{i % 10}@example.com", topic_ids=["familie"], now=now)
        store.save(state_names.mail(mid), mail.model_dump(mode="json"))
        prop = _make_proposal(mid, pid, ProposalKind.EVENT, ProposalStatus.REJECTED, now=now)
        store.save(state_names.proposal(mid, pid), prop.model_dump(mode="json"))

    # Also include an open proposal to ensure it is NOT counted as decided
    open_mid, open_pid = f"{999:024x}", "p-open-001"
    open_mail = _make_mail(open_mid, now=now)
    store.save(state_names.mail(open_mid), open_mail.model_dump(mode="json"))
    open_prop = _make_proposal(open_mid, open_pid, ProposalKind.TASK, ProposalStatus.PENDING_CONFIRMATION, now=now)
    store.save(state_names.proposal(open_mid, open_pid), open_prop.model_dump(mode="json"))

    report = evaluate_proposals(store, now=now)
    assert not report.empty
    s = report.summary
    assert s.total_decided == 249
    assert s.total_accepted == 50
    assert s.total_rejected == 199
    assert round(s.total_quote) == 20

    assert s.tasks_decided == 105
    assert s.tasks_accepted == 11
    assert s.tasks_rejected == 94
    assert round(s.tasks_quote) == 10

    assert s.events_decided == 144
    assert s.events_accepted == 39
    assert s.events_rejected == 105
    assert round(s.events_quote) == 27

    # Check weeks
    assert len(report.weeks) == 1
    w = report.weeks[0]
    assert w.decided == 249
    assert w.accepted == 50
    assert w.rejected == 199
    assert round(w.quote) == 20

    # Check topics
    topic_ids = {t.topic_id for t in report.topics}
    assert topic_ids == {"schule", "sport", "arbeit", "familie"}

    # Check already_done reason counted
    already_done = next((r for r in report.reasons if r.reason_key == "already_done"), None)
    assert already_done is not None
    assert already_done.count == 5


def test_evaluation_with_cutoff_and_jsonl_fallback(tmp_path: Path):
    store = JsonStore(tmp_path)
    now = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    old = now - timedelta(days=40)

    # 1 proposal in store, recent
    m_rec = f"{1:024x}"
    mail_rec = _make_mail(m_rec, now=now)
    store.save(state_names.mail(m_rec), mail_rec.model_dump(mode="json"))
    prop_recent = _make_proposal(m_rec, "p-recent", ProposalKind.TASK, ProposalStatus.CREATED, now=now)
    store.save(state_names.proposal(m_rec, "p-recent"), prop_recent.model_dump(mode="json"))

    # 1 proposal in store, old
    m_old = f"{2:024x}"
    mail_old = _make_mail(m_old, now=old)
    store.save(state_names.mail(m_old), mail_old.model_dump(mode="json"))
    prop_old = _make_proposal(m_old, "p-old", ProposalKind.TASK, ProposalStatus.CREATED, now=old)
    store.save(state_names.proposal(m_old, "p-old"), prop_old.model_dump(mode="json"))

    # 1 decision only in decisions.jsonl (proposal removed by retention)
    log_dir = tmp_path / "learning"
    log_dir.mkdir(parents=True, exist_ok=True)
    m_ret = f"{3:024x}"
    jsonl_record = {
        "schema_version": 1,
        "id": "dec-001",
        "recorded_at": (now - timedelta(days=5)).isoformat(),
        "mail_id": m_ret,
        "proposal_id": "p-retained",
        "kind": "reject",
        "reject_reason": "advertising",
        "mail": {"headers": {"sender": "newsletter@spam.example"}},
        "analysis": {"relevance": {"topic_ids": ["werbung"]}},
        "proposal": {"decided": {"kind": "task"}},
    }
    # And another that is a duplicate of prop_recent to test no double-counting
    jsonl_dup = {
        "schema_version": 1,
        "id": "dec-dup",
        "recorded_at": now.isoformat(),
        "mail_id": m_rec,
        "proposal_id": "p-recent",
        "kind": "confirm",
        "proposal": {"decided": {"kind": "task"}},
    }
    (log_dir / "decisions.jsonl").write_text(
        json.dumps(jsonl_record) + "\n" + json.dumps(jsonl_dup) + "\n",
        encoding="utf-8",
    )

    # Evaluate for 7 days
    report_7d = evaluate_proposals(store, days=7, now=now)
    assert report_7d.summary.total_decided == 2
    assert report_7d.summary.total_accepted == 1
    assert report_7d.summary.total_rejected == 1

    # Check reason from jsonl
    adv_reason = next((r for r in report_7d.reasons if r.reason_key == "advertising"), None)
    assert adv_reason is not None and adv_reason.count == 1

    # Evaluate for all time (days=0)
    report_all = evaluate_proposals(store, days=0, now=now)
    assert report_all.summary.total_decided == 3
    assert report_all.summary.total_accepted == 2
    assert report_all.summary.total_rejected == 1


def test_sender_fallback_when_mail_stripped(tmp_path: Path):
    store = JsonStore(tmp_path)
    now = datetime.now(UTC)
    m_miss = f"{4:024x}"
    prop = _make_proposal(m_miss, "p-1", ProposalKind.EVENT, ProposalStatus.CREATED)
    store.save(state_names.proposal(m_miss, "p-1"), prop.model_dump(mode="json"))

    proposals = collect_decided_proposals(store, now=now)
    assert len(proposals) == 1
    assert proposals[0].sender == "Absender entfernt"


def test_collect_decided_proposals_edge_cases(tmp_path: Path):
    from mailhelp.models import DisplayHeaders, PreparedMail
    from mailhelp.review.proposal_evaluation import _parse_iso
    store = JsonStore(tmp_path)
    now = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)

    # 1. _parse_iso edge cases
    assert _parse_iso(None) is None
    assert _parse_iso("") is None
    assert _parse_iso("not-a-date") is None

    # 2. Versioned proposal state proposal-<mid>-<pid>-v2 is skipped
    mid1 = f"{10:024x}"
    prop1 = _make_proposal(mid1, "p-1", ProposalKind.TASK, ProposalStatus.CREATED)
    store.save(f"proposal-{mid1}-p-1-v2", prop1.model_dump(mode="json"))

    # 3. Corrupt proposal state and None proposal state
    store.save(f"proposal-{mid1}-p-corrupt", {"invalid": "data"})
    store.save(f"proposal-{mid1}-p-missing", None)
    # Proposal suffix with -v but non-digit
    prop_v_alpha = _make_proposal(mid1, "p-valpha", ProposalKind.TASK, ProposalStatus.CREATED)
    store.save(f"proposal-{mid1}-p-valpha", prop_v_alpha.model_dump(mode="json"))

    # 4. Mail without display_headers, fallback to mail.headers.from
    mid2 = f"{11:024x}"
    dt2 = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)
    mail2 = MailState(
        id=mid2,
        config_fingerprint="0" * 64,
        created_at=dt2,
        imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 1},
        mail={"headers": {"from": "prep@example.com", "subject": "Sub"}},
    )
    store.save(state_names.mail(mid2), mail2.model_dump(mode="json"))
    prop2 = _make_proposal(mid2, "p-2", ProposalKind.TASK, ProposalStatus.CREATED)
    store.save(state_names.proposal(mid2, "p-2"), prop2.model_dump(mode="json"))

    # 4b. Mail without display_headers and without mail headers
    mid3 = f"{13:024x}"
    mail3 = MailState(
        id=mid3,
        config_fingerprint="0" * 64,
        created_at=dt2,
        imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 1},
    )
    store.save(state_names.mail(mid3), mail3.model_dump(mode="json"))
    prop3 = _make_proposal(mid3, "p-3", ProposalKind.TASK, ProposalStatus.CREATED)
    store.save(state_names.proposal(mid3, "p-3"), prop3.model_dump(mode="json"))

    # 4c. Corrupt mail state triggers get_mail exception handling
    mid_corrupt = f"{14:024x}"
    store.save(state_names.mail(mid_corrupt), {"invalid": "mail"})
    prop_corrupt = _make_proposal(mid_corrupt, "p-corrupt", ProposalKind.TASK, ProposalStatus.CREATED)
    store.save(state_names.proposal(mid_corrupt, "p-corrupt"), prop_corrupt.model_dump(mode="json"))

    # 5. decisions.jsonl with edge cases
    log_dir = tmp_path / "learning"
    log_dir.mkdir(parents=True, exist_ok=True)
    records = [
        # missing mail_id/proposal_id
        {"id": "d1", "kind": "confirm"},
        # invalid recorded_at
        {"id": "d2", "mail_id": "m", "proposal_id": "p", "recorded_at": "bad", "kind": "confirm"},
        # older than cutoff
        {"id": "d3", "mail_id": "m_old", "proposal_id": "p_old", "recorded_at": "2020-01-01T00:00:00Z", "kind": "confirm"},
        # kind neither accepted nor rejected
        {"id": "d4", "mail_id": "m_other", "proposal_id": "p_other", "recorded_at": now.isoformat(), "kind": "ignore"},
        # kind == "already_done" with no reject_reason
        {"id": "d5", "mail_id": "m_done", "proposal_id": "p_done", "recorded_at": now.isoformat(), "kind": "already_done"},
    ]
    (log_dir / "decisions.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")

    results = collect_decided_proposals(store, cutoff=now - timedelta(days=1), now=now)
    assert any(r.proposal_id == "p-2" and r.sender == "prep@example.com" for r in results)
    done_rec = next((r for r in results if r.proposal_id == "p_done"), None)
    assert done_rec is not None
    assert done_rec.reject_reason == "already_done"

