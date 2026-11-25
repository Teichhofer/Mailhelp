"""8.7 §5.3/§6: every OpenRouter attempt is bound before the request and settled from its answer."""
import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from mailhelp.llm.adapter import PermanentError
from mailhelp.llm.openrouter import OpenRouterClient, ProviderResponseInvalid
from mailhelp.usage.ledger import Purpose
from mailhelp.usage.points import CostStatus
from mailhelp.usage.valuations import UsageMeter, operator_purpose

START = datetime(2026, 12, 1, 8, tzinfo=UTC)
MAIL = "b" * 24


def answer(cost: object = 0.01, finish: str = "stop") -> dict:
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    if cost != "absent":
        usage["cost"] = cost
    return {"id": "gen-1", "provider": "Synthetic", "usage": usage,
            "choices": [{"finish_reason": finish, "message": {"content": json.dumps({"ok": True})}}]}


@pytest.fixture
def meter(tmp_path):
    meter = UsageMeter(tmp_path, lambda: START)
    meter.valuations.add(Decimal("1.25"), Decimal("25"), "operator-cli", START)
    return meter


def client(meter, *responses):
    queue = list(responses)

    def handler(request):
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        status, body = item
        return httpx.Response(status, json=body, request=request) if not isinstance(body, str) else \
            httpx.Response(status, text=body, request=request)
    return OpenRouterClient("synthetic-key", 1, 3, 100, httpx.MockTransport(handler), sleep=lambda _: None,
                            meter=meter)


def statuses(meter):
    return [(item.begun.stage, item.settled.status if item.settled else None, item.points)
            for item in meter.ledger.attempts()]


def test_a_successful_call_is_counted_once_with_its_reported_cost(meter):
    client(meter, (200, answer())).complete("m", {}, "s", {"mail_id": MAIL}, stage="relevance")
    [attempt] = meter.ledger.attempts()
    assert statuses(meter) == [("relevance", CostStatus.REPORTED, Decimal(10))]
    assert attempt.begun.mail_id == MAIL and attempt.settled.provider_id == "gen-1"
    assert "synthetic-key" not in meter.ledger.path.read_text(encoding="utf-8")


def test_acceptance_12_each_retry_is_its_own_attempt(meter):
    failing = (500, {"error": {"message": "busy"}, "usage": {"cost": 0.002}})
    client(meter, httpx.ConnectError("down"), failing, httpx.ReadTimeout("slow"), (200, answer(0.01))).complete(
        "m", {}, "s", {}, stage="extraction")
    assert statuses(meter) == [("extraction", CostStatus.NOT_SENT, None),
                               ("extraction", CostStatus.REPORTED, Decimal(2)),
                               ("extraction", CostStatus.MISSING, None),
                               ("extraction", CostStatus.REPORTED, Decimal(10))]
    assert len({item.begun.attempt for item in meter.ledger.attempts()}) == 4
    assert [item.unclear for item in meter.ledger.attempts()] == [False, False, True, False]


def test_a_billed_but_unusable_answer_still_counts(meter):
    with pytest.raises(ProviderResponseInvalid):
        client(meter, (200, answer(0.01, finish="length"))).complete("m", {}, "s", {}, stage="summary")
    assert statuses(meter) == [("summary", CostStatus.REPORTED, Decimal(10))]


def test_an_answer_without_cost_or_json_is_not_free(meter):
    client(meter, (200, answer("absent"))).complete("m", {}, "s", {}, stage="relevance")
    with pytest.raises(PermanentError):
        client(meter, (400, "not json")).complete("m", {}, "s", {}, stage="relevance")
    assert [status for _, status, _ in statuses(meter)] == [CostStatus.MISSING, CostStatus.MISSING]


def test_a_call_stopped_before_sending_is_not_recorded(meter):
    def stop():
        raise RuntimeError("stopping")
    with pytest.raises(RuntimeError):
        client(meter, (200, answer())).complete("m", {}, "s", {}, stage="relevance", before_call=stop)
    assert meter.ledger.attempts() == []


def test_operator_maintenance_is_recorded_as_operator_usage(meter):
    with operator_purpose():
        client(meter, (200, answer())).complete("m", {}, "s", {}, stage="selftest")
    assert meter.ledger.attempts()[0].begun.purpose is Purpose.OPERATOR


def test_an_unusual_stage_name_is_stored_safely(meter):
    client(meter, (200, answer())).complete("m", {}, "s", {}, stage="Relevance Check/1")
    assert meter.ledger.attempts()[0].begun.stage == "other"


def test_without_a_meter_or_valuation_nothing_is_written(tmp_path):
    OpenRouterClient("k", 1, 0, 10, httpx.MockTransport(
        lambda request: httpx.Response(200, json=answer(), request=request))).complete("m", {}, "s", {})
    unvalued = UsageMeter(tmp_path)
    client(unvalued, (200, answer())).complete("m", {}, "s", {})
    assert unvalued.ledger.attempts() == [] and not (tmp_path / "attempts.jsonl").exists()
