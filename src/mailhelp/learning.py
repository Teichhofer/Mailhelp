"""Terminal-only, read-only mailbox learning workflow."""
from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import yaml

from .analysis import Analyzer
from .config import IrrelevantTopicsConfig, Topic, TopicsConfig
from .imap import FetchedMail, ImapReader
from .mime import prepare
from .models import IrrelevantSenders, LearnedCategory, MailClassification
from .sender_filter import add_irrelevant_senders, is_irrelevant_sender
from .storage import JsonStore


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
                 store: JsonStore | None = None,
                 *, input_fn: Callable[[str], str] = input,
                 output_fn: Callable[[str], None] = print,
                 timezone: str = "UTC", parallel_llm_calls: int = 4,
                 global_newest_first: bool = False,
                 historical_start: datetime | None = None):
        self.imap, self.analyzer, self.folders = imap, analyzer, folders
        self.limits, self.topics, self.topics_path = limits, topics, topics_path
        self.irrelevant_topics = irrelevant_topics
        self.irrelevant_topics_path = irrelevant_topics_path
        self.store = store
        self.input, self.output, self.timezone = input_fn, output_fn, timezone
        self.parallel_llm_calls = parallel_llm_calls
        self.global_newest_first = global_newest_first
        self.historical_start = historical_start

    def _fetch(self, count: int) -> list[FetchedMail]:
        if self.global_newest_first:
            candidates = [candidate for folder in self.folders
                          for candidate in self.imap.discover_since(
                              folder, max_count=count,
                              historical_start=self.historical_start)]
            # Folder order is the stable final tie-breaker; within a folder the
            # greater UID wins when servers report identical INTERNALDATE values.
            folder_rank = {folder: index for index, folder in enumerate(self.folders)}
            candidates.sort(key=lambda item: (
                item.received_at, item.uid, -folder_rank[item.folder]
            ), reverse=True)
            return [self.imap.fetch_uid(candidate.folder, candidate.uid,
                                        candidate.uidvalidity)
                    for candidate in candidates[:count]]
        mails: list[FetchedMail] = []
        for folder in self.folders:
            after_uid = (self.imap.determine_start_uid(folder, self.historical_start)
                         if self.historical_start is not None else 0)
            ranges: list[tuple[int, int]] = []
            while len(mails) < count:
                batch = self.imap.fetch_since(
                    folder, after_uid, None, count - len(mails), tuple(ranges)
                )
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
        known_topics = [*self.topics, *self.irrelevant_topics]

        blocked = (self.store.load_model("irrelevant-senders", IrrelevantSenders,
                                        IrrelevantSenders()) if self.store else IrrelevantSenders())
        assert isinstance(blocked, IrrelevantSenders)

        def classify(mail: FetchedMail) -> tuple[MailClassification | None, dict[str, object] | None, bool]:
            try:
                payload = prepare(mail.raw, self.limits, mail.received_at, self.timezone)
                if is_irrelevant_sender(payload["headers"].get("from", ""), blocked):
                    return None, None, False
                if self._known(payload, known_topics):
                    return None, None, False
                _call_id, classification = self.analyzer.classify_for_learning(payload)
                return classification, payload, False
            except Exception:
                # A malformed mail or an exhausted provider retry budget belongs to
                # this independent item. Do not discard successful sibling results.
                # Exception text may contain untrusted data and is not printed.
                return None, None, True

        # Each mail forms an independent first-stage pipeline. ``map`` preserves
        # mailbox order while relevance checks and classifications run concurrently.
        with ThreadPoolExecutor(max_workers=self.parallel_llm_calls) as executor:
            results = list(executor.map(classify, mails))
        classifications = [classification for classification, _payload, _failed in results
                           if classification is not None]
        failures = sum(failed for _classification, _payload, failed in results)
        if failures:
            self.output(
                f"{failures} Mail(s) konnten nicht ausgewertet werden und wurden übersprungen."
            )
        if not classifications:
            self.output("Keine unbekannten Mails zum Lernen gefunden; Themendateien wurden nicht geändert.")
            return 0
        try:
            _call_id, abstracted = self.analyzer.abstract_learned_categories(classifications)
            categories = abstracted.categories
        except Exception:
            # Abstraction is an optimization, not a reason to lose all successful
            # per-mail work. The fallback values were already schema-validated.
            self.output(
                "Die Verdichtung der Kategorien ist fehlgeschlagen; "
                "die Einzelklassifikationen werden stattdessen verwendet."
            )
            categories = [category for item in classifications for category in item.categories]
        accepted: list[LearnedCategory] = []
        rejected: list[LearnedCategory] = []
        for category in categories:
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
            if self.store is not None:
                rejected_names = {item.name.casefold() for item in rejected}
                rejected_topics = self.irrelevant_topics[-len(rejected):]
                headers: list[object] = []
                for classification, payload, _failed in results:
                    if classification is None or payload is None:
                        continue
                    directly_matched = any(
                        category.name.casefold() in rejected_names
                        for category in classification.categories
                    )
                    try:
                        matched = directly_matched or self._known(payload, rejected_topics)
                    except Exception:
                        matched = directly_matched
                    if matched:
                        headers.append(payload["headers"].get("from", ""))
                updated = add_irrelevant_senders(blocked, headers)
                if updated != blocked:
                    self.store.save("irrelevant-senders", updated.model_dump(mode="json"))
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
