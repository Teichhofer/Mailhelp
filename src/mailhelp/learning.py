"""Terminal-only, read-only mailbox learning workflow."""
from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from collections.abc import Callable
from pathlib import Path

import yaml

from .analysis import Analyzer
from .config import IrrelevantTopicsConfig, Topic, TopicsConfig
from .imap import FetchedMail, ImapReader
from .mime import prepare
from .models import LearnedCategory, MailClassification


def _safe_terminal(value: str) -> str:
    """Prevent untrusted LLM text from injecting terminal control sequences."""
    return "".join(character if character in "\n\t" or ord(character) >= 32 else "�"
                   for character in value)


def _topic_id(name: str, used: set[str]) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-") or "thema"
    base = base[:60].rstrip("-") or "thema"
    candidate, number = base, 2
    while candidate in used:
        suffix = f"-{number}"
        candidate = base[:64 - len(suffix)].rstrip("-") + suffix
        number += 1
    used.add(candidate)
    return candidate


def save_topics(path: Path, existing: list[Topic], accepted: list[LearnedCategory],
                *, allow_empty: bool = False) -> list[Topic]:
    """Validate and atomically replace a topic file with accepted candidates."""
    used = {topic.id for topic in existing}
    additions = [Topic(id=_topic_id(item.name, used), name=item.name, enabled=True,
                       description=item.description, examples=item.examples)
                 for item in accepted]
    model = IrrelevantTopicsConfig if allow_empty else TopicsConfig
    result = model(topics=[*existing, *additions]).topics
    content = yaml.safe_dump(
        {"topics": [topic.model_dump() for topic in result]}, allow_unicode=True,
        sort_keys=False, default_flow_style=False,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return result


class LearningMode:
    def __init__(self, imap: ImapReader, analyzer: Analyzer, folders: list[str],
                 limits: object, topics: list[Topic], topics_path: Path,
                 irrelevant_topics: list[Topic], irrelevant_topics_path: Path,
                 *, input_fn: Callable[[str], str] = input,
                 output_fn: Callable[[str], None] = print,
                 timezone: str = "UTC"):
        self.imap, self.analyzer, self.folders = imap, analyzer, folders
        self.limits, self.topics, self.topics_path = limits, topics, topics_path
        self.irrelevant_topics = irrelevant_topics
        self.irrelevant_topics_path = irrelevant_topics_path
        self.input, self.output, self.timezone = input_fn, output_fn, timezone

    def _fetch(self, count: int) -> list[FetchedMail]:
        mails: list[FetchedMail] = []
        for folder in self.folders:
            ranges: list[tuple[int, int]] = []
            while len(mails) < count:
                batch = self.imap.fetch_since(folder, 0, None, count - len(mails), tuple(ranges))
                if not batch:
                    break
                mails.extend(batch)
                ranges.extend((mail.uid, mail.uid) for mail in batch)
            if len(mails) == count:
                break
        return mails

    def run(self, count: int) -> int:
        mails = self._fetch(count)
        self.output(f"{len(mails)} von {count} angeforderten Mails wurden abgerufen.")
        classifications: list[MailClassification] = []
        for mail in mails:
            payload = prepare(mail.raw, self.limits, mail.received_at, self.timezone)
            known_relevant = self._known(payload, self.topics)
            known_irrelevant = self._known(payload, self.irrelevant_topics)
            if known_relevant or known_irrelevant:
                continue
            _call_id, classification = self.analyzer.classify_for_learning(payload)
            classifications.append(classification)
        if not classifications:
            self.output("Keine unbekannten Mails zum Lernen gefunden; Themendateien wurden nicht geändert.")
            return 0
        _call_id, abstracted = self.analyzer.abstract_learned_categories(classifications)
        accepted: list[LearnedCategory] = []
        rejected: list[LearnedCategory] = []
        for category in abstracted.categories:
            self.output(f"\nKategorie: {_safe_terminal(category.name)}")
            self.output(f"Beschreibung: {_safe_terminal(category.description)}")
            while True:
                answer = self.input("Relevant und in topics.yaml speichern? [j/n]: ").strip().lower()
                if answer in {"j", "ja", "y", "yes"}:
                    accepted.append(category)
                    break
                if answer in {"n", "nein", "no"}:
                    rejected.append(category)
                    break
                self.output("Bitte mit j oder n antworten.")
        if accepted:
            self.topics = save_topics(self.topics_path, self.topics, accepted)
        if rejected:
            self.irrelevant_topics = save_topics(
                self.irrelevant_topics_path, self.irrelevant_topics, rejected,
                allow_empty=True,
            )
        self.output(
            f"{len(accepted)} relevante und {len(rejected)} irrelevante neue Kategorien wurden gespeichert."
        )
        return len(accepted)

    def _known(self, payload: dict[str, object], topics: list[Topic]) -> bool:
        """Return whether a mail matches an enabled topic in the supplied category set."""
        enabled = [topic for topic in topics if topic.enabled]
        if not enabled:
            return False
        _call_id, relevance = self.analyzer.relevance(payload, enabled)
        return relevance.decision == "relevant"
