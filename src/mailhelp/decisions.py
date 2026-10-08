"""Opt-in typed OpenRouter Decisions adapter; never used by normal analysis."""
from __future__ import annotations

import json
import math
import time
import uuid
from typing import Annotated, Any, Literal
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from .config import ConfigModel, Topic, _yaml, _validated_file
from .models import ActionRoute, Relevance
from .openrouter import OpenRouterClient, RateLimitExceeded


class ChoiceQuestion(ConfigModel):
    type: Literal["choice"] = "choice"
    instructions: str = Field(min_length=1)
    criteria: dict[str, str] = Field(min_length=2, max_length=26)


class NoulQuestion(ConfigModel):
    type: Literal["noul"] = "noul"
    instructions: str = Field(min_length=1)
    criteria: dict[Literal["true", "false"], str]

    @model_validator(mode="after")
    def both_criteria(self):
        if set(self.criteria) != {"true", "false"}:
            raise ValueError("noul benötigt true und false")
        return self


class ScoreQuestion(ConfigModel):
    type: Literal["score"] = "score"
    instructions: str = Field(min_length=1)
    criteria: list[str] = Field(min_length=2, max_length=26)


Question = Annotated[ChoiceQuestion | NoulQuestion | ScoreQuestion, Field(discriminator="type")]
QUESTIONS = TypeAdapter(dict[str, Question])
Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class DecisionAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    type: Literal["choice", "noul", "score"]
    choice: str | None = None
    noul: Probability | None = None
    score: Annotated[float, Field(ge=0, le=25, allow_inf_nan=False)] | None = None
    confidence: Probability | None = None
    probabilities: dict[str, Probability] | None = None


class DecisionResponseError(ValueError):
    """Content-free diagnostic for untrusted provider output."""


def validate_answers(raw: Any, questions: dict[str, Question]) -> None:
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"]:
        raise DecisionResponseError("Ungültige Decision-Antworthülle")
    answers = raw.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise DecisionResponseError("Decision-Antworten passen nicht zu den Fragen")
    for name, question in questions.items():
        try:
            answer = DecisionAnswer.model_validate(answers[name])
            if answer.type != question.type:
                raise ValueError("type")
            if question.type == "noul":
                if answer.noul is None:
                    raise ValueError("noul")
                continue
            keys = (set(question.criteria) if question.type == "choice"
                    else {str(index) for index in range(len(question.criteria))})
            if (answer.probabilities is None or set(answer.probabilities) != keys
                    or not math.isclose(sum(answer.probabilities.values()), 1, abs_tol=0.01)
                    or answer.confidence is None):
                raise ValueError("probabilities")
            if question.type == "choice":
                if answer.choice not in keys:
                    raise ValueError("choice")
            elif answer.score is None or answer.score > len(question.criteria) - 1:
                raise ValueError("score")
        except ValueError as exc:
            raise DecisionResponseError("Ungültige typisierte Decision-Antwort") from exc


class DecisionClient(OpenRouterClient):
    """Reuse bounded HTTP retries, credentials and resource ownership only."""

    endpoint = "https://openrouter.ai/api/alpha/decisions"

    def decide(self, model: str, state: dict[str, Any], questions: dict[str, Any],
               *, stage: str, max_payload_bytes: int) -> tuple[str, dict[str, Any]]:
        validated = QUESTIONS.validate_python(questions)
        if not 1 <= len(validated) <= 64:
            raise ValueError("Eine Decision-Anfrage benötigt 1 bis 64 Fragen")
        request = {"model": model, "state": state,
                   "questions": {name: value.model_dump() for name, value in validated.items()}}
        if len(json.dumps(request, ensure_ascii=False).encode("utf-8")) > max_payload_bytes:
            raise ValueError("Decision-Payload überschreitet max_llm_payload_bytes")
        call_id = str(uuid.uuid4())
        started = time.perf_counter()

        def invoke() -> httpx.Response:
            # Charge every network attempt against the shared rate limit.
            with self._state_lock:
                now = self.clock()
                calls = sorted(value for value in self.load_calls() if now - value < 60)
                if len(calls) >= self.limit:
                    raise RateLimitExceeded(calls[0] + 60)
                calls.append(now)
                self.save_calls(calls)
            response = self.client.post(self.endpoint, headers=self._headers(call_id), json=request)
            self._raise_for_status(response)
            return response

        def begin(number: int) -> None:
            self.logger.llm_event("request_started", request=request, stage=stage,
                                  model=model, call_id=call_id, attempt=number)

        try:
            response = self.policy.run(invoke, begin)
            try:
                raw = response.json()
            except ValueError as exc:
                raise DecisionResponseError("Decision-Antwort ist kein JSON") from exc
            self.logger.llm_event("response_received", response=raw, stage=stage,
                                  model=model, call_id=call_id, http_status=response.status_code,
                                  duration_ms=round((time.perf_counter() - started) * 1000, 3))
            validate_answers(raw, validated)
            return call_id, raw
        except Exception as exc:
            self.logger.llm_event("request_failed", stage=stage, model=model,
                                  call_id=call_id, error_type=type(exc).__name__)
            raise


class DecisionPrompts(ConfigModel):
    model: str = Field(min_length=1, pattern=r"^[^<>\s]+$")
    topic_threshold: Probability = 0.5
    prompts: dict[str, dict[str, Question]]

    @model_validator(mode="after")
    def required_templates(self):
        required = {"relevance": {"decision", "topic_match"},
                    "action_router": {"action_state", "task_count", "event_count"}}
        if set(self.prompts) != set(required):
            raise ValueError("Decision-Vorlagen benötigen relevance und action_router")
        for stage, names in required.items():
            if set(self.prompts[stage]) != names:
                raise ValueError("Unvollständige Decision-Fragen")
        expected = {
            ("relevance", "decision"): {"relevant", "irrelevant", "unclear"},
            ("action_router", "action_state"): {"none", "task", "event", "task_and_event", "unclear"},
            ("action_router", "task_count"): {str(index) for index in range(21)},
            ("action_router", "event_count"): {str(index) for index in range(21)},
        }
        for (stage, name), keys in expected.items():
            question = self.prompts[stage][name]
            if not isinstance(question, ChoiceQuestion) or set(question.criteria) != keys:
                raise ValueError("Decision-Auswahl passt nicht zum Anwendungsschema")
        if not isinstance(self.prompts["relevance"]["topic_match"], NoulQuestion):
            raise ValueError("topic_match muss noul verwenden")
        return self


def load_decision_prompts(path: Path) -> DecisionPrompts:
    return _validated_file(path, DecisionPrompts, _yaml(path))


class DecisionAnalyzer:
    """Only classification/routing; generative stages stay with Analyzer."""

    def __init__(self, client: DecisionClient, prompts: DecisionPrompts,
                 max_payload_bytes: int):
        self.client, self.prompts, self.max_payload_bytes = client, prompts, max_payload_bytes

    def relevance(self, mail: dict[str, Any], topics: list[Topic]) -> tuple[str, Relevance]:
        enabled = [topic for topic in topics if topic.enabled]
        templates = self.prompts.prompts["relevance"]
        questions = {"decision": templates["decision"].model_dump()}
        for index, topic in enumerate(enabled):
            question = templates["topic_match"].model_dump()
            question["instructions"] += f"\nBewerte ausschließlich topics[{index}]."
            questions[f"topic_{index}"] = question
        call, raw = self.client.decide(
            self.prompts.model, {"mail": mail, "topics": [topic.model_dump() for topic in enabled]},
            questions, stage="relevance", max_payload_bytes=self.max_payload_bytes)
        answers = raw["answers"]
        decision = answers["decision"]["choice"]
        ids = [topic.id for index, topic in enumerate(enabled)
               if answers[f"topic_{index}"]["noul"] >= self.prompts.topic_threshold]
        if decision == "irrelevant":
            ids = []
        if decision == "relevant" and not ids:
            raise DecisionResponseError("Relevante Decision-Antwort ohne zugeordnetes Thema")
        return call, Relevance(decision=decision, topic_ids=ids,
                               reason="Decision-Modell: typisierte Relevanz- und Themenentscheidung.")

    def action_route(self, mail: dict[str, Any]) -> tuple[str, ActionRoute]:
        questions = {name: value.model_dump()
                     for name, value in self.prompts.prompts["action_router"].items()}
        call, raw = self.client.decide(self.prompts.model, {"mail": mail}, questions,
                                     stage="action_router", max_payload_bytes=self.max_payload_bytes)
        answers = raw["answers"]
        return call, ActionRoute(
            action_state=answers["action_state"]["choice"],
            task_count=int(answers["task_count"]["choice"]),
            event_count=int(answers["event_count"]["choice"]),
            reason="Decision-Modell: typisierte Aktionsart und Kandidatenzahlen.")
