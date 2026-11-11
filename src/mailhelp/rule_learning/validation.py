"""Validate both complete topic files before preparing any file replacement."""
from __future__ import annotations

from typing import Any

import yaml
from pydantic import ValidationError

from ..config import IrrelevantTopicsConfig, TopicsConfig
from .models import RuleProposal, RuleTopic

FILES = {"relevant": "topics.yaml", "irrelevant": "irrelevant_topics.yaml"}


class RuleLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader: RuleLoader, node: yaml.MappingNode) -> dict[str, Any]:
    keys = [loader.construct_object(key) for key, _ in node.value]
    if any(not isinstance(key, str) for key in keys) or len(keys) != len(set(keys)):
        raise yaml.YAMLError("Doppelte oder nicht textuelle YAML-Schlüssel")
    return {str(key): value for key, value in yaml.SafeLoader.construct_mapping(loader, node).items()}


RuleLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def parse_yaml(text: str) -> Any:
    try:
        return yaml.load(text, Loader=RuleLoader)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        line = f" in Zeile {mark.line + 1}" if mark is not None else ""
        raise ValueError("YAML-Syntaxfehler" + line) from None


class RuleConflict(ValueError):
    pass


class RuleValidationService:
    @staticmethod
    def parse(text: str, category: str) -> dict[str, Any]:
        raw = parse_yaml(text)
        model = TopicsConfig if category == "relevant" else IrrelevantTopicsConfig
        try:
            value = model.model_validate(raw)
            topics = [RuleTopic.model_validate(topic.model_dump(mode="json")) for topic in value.topics]
        except ValidationError as error:
            first = error.errors(include_input=False, include_url=False)[0]
            location = ".".join(str(part) for part in first["loc"])
            raise ValueError(f"{FILES[category]}: {location}: {first['msg']}") from None
        return {"topics": [topic.model_dump(mode="json") for topic in topics]}

    @classmethod
    def prepare(cls, documents: dict[str, Any], choices: list[dict[str, Any]],
                proposals: list[RuleProposal], mailbox_ids: set[int] | None = None) -> dict[str, str]:
        groups = {category: list(document["topics"]) for category, document in documents.items()}
        seen: set[int] = set()
        for choice in choices:
            index = choice["index"]
            if type(index) is not int or index in seen or not 0 <= index < len(proposals):
                raise ValueError("Ungültige oder doppelte Vorschlagsauswahl")
            seen.add(index)
            proposal = proposals[index]
            topic = RuleTopic.model_validate(choice["topic"])
            if proposal.action != "create" and topic.id != proposal.topic_id:
                raise ValueError("Die stabile Themen-ID darf nicht geändert werden")
            old = next((item for item in groups[proposal.category] if item["id"] == topic.id), None)
            if (proposal.action == "create") == (old is not None):
                raise RuleConflict("Thema fehlt oder wurde inzwischen angelegt")
            if old is not None and old.get("mailboxes") != topic.mailboxes:
                raise ValueError("Postfachgrenzen einer bestehenden Regel dürfen hier nicht verändert werden")
            groups[proposal.category] = [item for item in groups[proposal.category] if item["id"] != topic.id]
            groups[proposal.category].append(topic.model_dump(mode="json"))
        if not choices:
            raise ValueError("Mindestens einen Vorschlag auswählen")
        result: dict[str, str] = {}
        identifiers: list[str] = []
        for category, topics in groups.items():
            content = yaml.safe_dump({"topics": topics}, allow_unicode=True, sort_keys=False)
            checked = cls.parse(content, category)
            if mailbox_ids is not None and any(not set(topic["mailboxes"] or []) <= mailbox_ids
                                               for topic in checked["topics"]):
                raise ValueError("Thema verweist auf ein nicht konfiguriertes Postfach")
            identifiers.extend(topic["id"] for topic in checked["topics"])
            result[FILES[category]] = content
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Themen-ID ist über beide Dateien doppelt vergeben")
        return result
