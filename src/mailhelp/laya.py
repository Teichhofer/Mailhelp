"""Experimental relevance check with Laya, a local typed decision model.

Laya runs behind Ollama's ``/v1/systemone``: it answers typed questions about a
text with probabilities and generates no text.  It is used only in
``--decision-test`` for the relevance check of the Ollama path.

The question is built at runtime from the relevance criteria, following the
Laya model card: one ``choice`` question whose options are the enabled topics
from ``topics.yaml`` plus a catch-all, with neutral letter keys (yes/no label
bias) and asked in several option orders whose probabilities are averaged
(position bias).  ``laya_prompts.yaml`` holds only the frame, limits,
thresholds and the number of orders.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx
from pydantic import Field, model_validator

from .config import ConfigModel, Topic, _validated_file, _yaml
from .decisions import DecisionClient, Probability, Question, validate_answers
from .models import Relevance
from .ollama import LocalLlm, OllamaClient, require_installed_model

_LINK = re.compile(r"https?://\S+")
# Lines left over from link footnotes and separators, e.g. "[1]", "Links:", "-----".
_NOISE = re.compile(r"Links:|[\[\]\d\s=_-]+")
_PLACEHOLDER = re.compile(r"\{(name|description|irrelevant)\}")
_STATE_TOO_LONG = re.compile(r"state has (\d+) tokens; limit is (\d+)")
# Ollama limits a choice question to 26 options: the topics plus the catch-all.
MAX_TOPICS = 25
OTHER = "other"


class LayaStateTooLong(ValueError):
    """Laya rejected the mail text as longer than its token window."""

    def __init__(self, tokens: int, limit: int):
        super().__init__(f"Laya: Mailtext hat {tokens} Token, erlaubt sind {limit}")
        self.tokens, self.limit = tokens, limit


class LayaPrompts(ConfigModel):
    model: str = Field(min_length=1, max_length=200, pattern=r"^[^<>\s]+$")
    max_state_characters: int = Field(default=900, ge=100, le=20000)
    # Laya rejects options above roughly 48 tokens.
    max_option_characters: int = Field(default=90, ge=20, le=300)
    rotations: int = Field(default=3, ge=1, le=10)
    instructions: str = Field(min_length=1, max_length=300)
    # {name} and {description} come from the topic.
    topic_option: str = Field(min_length=1, max_length=200, pattern=r"\{name\}")
    # {irrelevant} lists the names of the enabled irrelevant categories.
    other_option: str = Field(min_length=1, max_length=300)
    relevant_threshold: Probability = 0.9
    irrelevant_threshold: Probability = 0.75
    topic_threshold: Probability = 0.2

    @model_validator(mode="after")
    def ordered_thresholds(self) -> "LayaPrompts":
        if self.irrelevant_threshold > self.relevant_threshold:
            raise ValueError("irrelevant_threshold darf relevant_threshold nicht übersteigen")
        return self


def load_laya_prompts(directory: Path) -> LayaPrompts:
    """Use the editable configuration, or the packaged template if absent."""
    path = directory / "laya_prompts.yaml"
    if not path.exists():
        path = Path(__file__).parent / "defaults" / "laya_prompts.yaml"
    return _validated_file(path, LayaPrompts, _yaml(path))


class LayaClient(DecisionClient):
    """Typed decisions against a local Ollama server; never sends credentials."""

    service_name = "Laya (lokal, experimentell)"
    endpoint = "/v1/systemone"

    def __init__(self, host: str, port: int, model: str, timeout: float, retries: int,
                 calls_per_minute: int, **kwargs: Any):
        super().__init__("", timeout, retries, calls_per_minute,
                         base_url=LocalLlm(host, port, model).base_url, **kwargs)
        self.model = model

    def _headers(self, call_id: str) -> dict[str, str]:
        return {"X-Request-Id": call_id}

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code == 400:
            try:
                message = str(response.json().get("error", ""))
            except (ValueError, AttributeError):
                message = ""
            match = _STATE_TOO_LONG.search(message)
            if match:
                raise LayaStateTooLong(int(match.group(1)), int(match.group(2)))
        OllamaClient._raise_for_status(response)

    @staticmethod
    def _validate_answers(raw: Any, questions: dict[str, Question]) -> None:
        validate_answers(raw, questions, require_id=False)

    def check_access(self) -> None:
        require_installed_model(self, self.model)


def _shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rsplit(" ", 1)[0] + "…"


class LayaRelevanceAnalyzer:
    """Relevance and topics from one rotated topic choice built from the relevance criteria."""

    def __init__(self, client: LayaClient, prompts: LayaPrompts, max_payload_bytes: int,
                 irrelevant_topics: list[Topic]):
        self.client, self.prompts, self.max_payload_bytes = client, prompts, max_payload_bytes
        self.irrelevant = [topic for topic in irrelevant_topics if topic.enabled]

    def state(self, mail: dict[str, Any], limit: int | None = None) -> str:
        """Sender, subject and body without links, quotes and link footnotes.

        Long tracking links push Laya to answer every question with yes.
        """
        headers = mail.get("headers") or {}
        body = _LINK.sub("", mail.get("text", ""))
        lines = [line for line in body.splitlines()
                 if line.strip() and not line.lstrip().startswith(">")
                 and not _NOISE.fullmatch(line.strip())]
        text = (f"From: {headers.get('from', '')}\nSubject: {headers.get('subject', '')}\n\n"
                + "\n".join(lines))
        return text[:limit or self.prompts.max_state_characters]

    def options(self, topics: list[Topic]) -> dict[str, str]:
        """Option text per topic id plus the catch-all, built from the relevance criteria."""
        values = {"irrelevant": ", ".join(topic.name for topic in self.irrelevant)}

        def fill(template: str, topic: Topic | None) -> str:
            text = _PLACEHOLDER.sub(lambda match: values[match.group(1)] if topic is None
                                    else getattr(topic, match.group(1), ""), template)
            return _shorten(text, self.prompts.max_option_characters)

        options = {topic.id: fill(self.prompts.topic_option, topic) for topic in topics}
        options[OTHER] = fill(self.prompts.other_option, None)
        return options

    def questions(self, options: dict[str, str]) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
        """The choice in several option orders with neutral letter keys."""
        keys, count = list(options), self.prompts.rotations
        questions, mappings = {}, {}
        for rotation in range(count):
            shift = rotation * len(keys) // count
            order = keys[shift:] + keys[:shift]
            if rotation % 2:
                order.reverse()
            mapping = {chr(65 + index): key for index, key in enumerate(order)}
            questions[f"order_{rotation}"] = {
                "type": "choice", "instructions": self.prompts.instructions,
                "criteria": {letter: options[key] for letter, key in mapping.items()}}
            mappings[f"order_{rotation}"] = mapping
        return questions, mappings

    def relevance(self, mail: dict[str, Any], topics: list[Topic]) -> tuple[str, Relevance]:
        enabled = [topic for topic in topics if topic.enabled]
        if len(enabled) > MAX_TOPICS:
            raise ValueError(f"Laya unterstützt höchstens {MAX_TOPICS} aktivierte Themen")
        questions, mappings = self.questions(self.options(enabled))
        state = self.state(mail)
        try:
            call, raw = self.client.decide(self.prompts.model, state, questions, stage="relevance",
                                           max_payload_bytes=self.max_payload_bytes)
        except LayaStateTooLong as exc:
            # Shorten once in proportion to the reported token counts.
            state = self.state(mail, max(1, len(state) * exc.limit * 9 // (exc.tokens * 10)))
            call, raw = self.client.decide(self.prompts.model, state, questions, stage="relevance",
                                           max_payload_bytes=self.max_payload_bytes)
        probabilities = dict.fromkeys([topic.id for topic in enabled] + [OTHER], 0.0)
        for name, mapping in mappings.items():
            for letter, value in raw["answers"][name]["probabilities"].items():
                probabilities[mapping[letter]] += value / len(mappings)
        score = 1 - probabilities[OTHER]
        ids = sorted((topic.id for topic in enabled
                      if probabilities[topic.id] >= self.prompts.topic_threshold),
                     key=lambda key: -probabilities[key])
        if score < self.prompts.irrelevant_threshold:
            decision = "irrelevant"
        elif score >= self.prompts.relevant_threshold and ids:
            decision = "relevant"
        else:
            decision = "unclear"
        reason = (f"Laya: P(Thema)={score:.2f}; " + json.dumps(
            {key: round(probabilities[key], 2) for key in ids}, ensure_ascii=False))
        return call, Relevance(decision=decision, topic_ids=[] if decision == "irrelevant" else ids,
                               reason=_shorten(reason, 1000))


__all__ = ["LayaClient", "LayaPrompts", "LayaRelevanceAnalyzer", "LayaStateTooLong",
           "load_laya_prompts"]
