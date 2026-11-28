"""8.9.2 (Planung 8.9 AP2): the identity of an extracted action, independent of incidental wording.

Two actions are the same when their action verbs agree, their subjects agree after a safe normalization
(umlauts, case, filler words, compounds) or the corpus names the title as an alias beforehand, and the
answer's evidence stands verbatim in the source. Equal counts, deadlines or responsibilities never prove
an identity. Pairs are chosen as the best overall assignment, independent of the output order; when
several equally good assignments pair different actions, the affected actions need a review.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

# Verbs and their noun forms of one kind of action. Two titles with known verbs of disjoint groups name
# different actions ("Rechnung prüfen" is not "Rechnung bezahlen"), whatever else they share.
VERB_GROUPS: dict[str, tuple[str, ...]] = {
    "send": ("senden", "schicken", "zusenden", "uebersenden", "uebermitteln", "einreichen", "abgeben",
             "zuschicken", "nachreichen"),
    "reply": ("antworten", "beantworten", "rueckmelden", "rueckmeldung", "antwort"),
    "register": ("anmelden", "anmeldung", "registrieren", "registrierung", "einschreiben"),
    "pay": ("bezahlen", "zahlen", "ueberweisen", "begleichen", "zahlung", "bezahlung"),
    "check": ("pruefen", "ueberpruefen", "kontrollieren", "durchsehen", "sichten", "pruefung"),
    "prepare": ("vorbereiten", "vorbereitung", "erstellen", "ausarbeiten"),
    "sign": ("unterschreiben", "unterzeichnen", "unterschrift"),
    "book": ("buchen", "reservieren", "reservierung"),
    "update": ("aktualisieren", "aendern", "anpassen", "verschieben"),
    "approve": ("freigeben", "genehmigen", "freigabe", "genehmigung"),
    "confirm": ("bestaetigen", "bestaetigung", "zusagen", "zusage"),
    "cancel": ("absagen", "stornieren", "abmelden", "absage", "stornierung", "storniert"),
    "order": ("bestellen", "bestellung"),
    "fill": ("ausfuellen",),
    "read": ("lesen", "durchlesen"),
    "discuss": ("besprechen", "abstimmen", "klaeren", "besprechung"),
    "attend": ("teilnehmen", "teilnahme"),
    "calendar": ("eintragen", "vormerken"),
}
_STOPWORDS = frozenset(
    "der die das den dem des ein eine einen einem einer eines fuer zu zur zum von vom mit und oder im in am "
    "an auf bei aus ueber nach vor bis per als ihr ihre ihren ihrem sein seine seinen letzten letzte naechste "
    "naechsten neue neuen alle allen sowie bitte geben machen".split())
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def normalize(text: str) -> str:
    """Case, umlauts and whitespace of a text as one comparable form."""
    return " ".join(text.casefold().translate(_UMLAUTS).split())


def tokens(text: str) -> list[str]:
    return [word for word in re.findall(r"[a-z0-9]{3,}", normalize(text)) if word not in _STOPWORDS]


def verbs(text: str) -> set[str]:
    """The verb groups a title names; a compound ends with its verb ("zurückschicken")."""
    found = set()
    for word in tokens(text):
        for group, forms in VERB_GROUPS.items():
            if any(word == form or len(form) >= 5 and word.endswith(form) for form in forms):
                found.add(group)
    return found


def same_word(left: str, right: str) -> bool:
    """Equal words, a compound containing the other word, or a long common stem ("rückmelden"/"Rückmeldung")."""
    if left == right:
        return True
    if min(len(left), len(right)) >= 4 and (left in right or right in left):
        return True
    stem = 0
    for a, b in zip(left, right, strict=False):
        if a != b:
            break
        stem += 1
    return stem >= 7


def title_score(left: str, right: str) -> float:
    """Share of the shorter title's subject words that the other title names (0 … 1)."""
    a, b = tokens(left), tokens(right)
    if not a or not b:
        return 0.0
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return sum(any(same_word(word, other) for other in long) for word in short) / len(short)


def verified(evidence: str, source: str) -> bool:
    """The evidence stands verbatim in the source, apart from case, umlaut spelling and whitespace."""
    quote = normalize(evidence)
    return bool(quote) and quote in normalize(source)


def evidence_score(left: str, right: str) -> float:
    """How far two evidence quotes overlap: containment counts fully, else the shared words."""
    a, b = normalize(left), normalize(right)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    words_a, words_b = set(tokens(a)), set(tokens(b))
    return len(words_a & words_b) / len(words_a | words_b) if words_a and words_b else 0.0


@dataclass(frozen=True)
class Candidate:
    """Why an answer may be an expected action; *weight* orders equally valid assignments."""

    expected: int
    actual: int
    weight: float


def identity(expected: dict[str, Any], actual: dict[str, Any], source: str, same_day: bool = False) -> float | None:
    """The weight of the pair, or None when the two cannot be the same action."""
    named = verbs(expected["title"]) | {verb for alias in expected.get("aliases", []) for verb in verbs(alias)}
    answered = verbs(actual["title"])
    if named and answered and not named & answered:
        return None
    alias = any(normalize(alias) == normalize(actual["title"]) for alias in expected.get("aliases", []))
    title = max([title_score(expected["title"], actual["title"]),
                 *(title_score(name, actual["title"]) for name in expected.get("aliases", []))])
    quoted = evidence_score(expected["evidence"], actual["evidence"]) if verified(actual["evidence"], source) else 0.0
    if not (alias or title >= 0.6 or quoted >= 0.6 and title >= 0.3):
        return None
    # The day only orders otherwise equal candidates (a series of equal titles); it never makes one.
    return (2.0 if alias else title) + quoted + (0.5 if same_day else 0.0)


def _assign(weights: list[list[float | None]]) -> tuple[int, float, list[tuple[int, int]]]:
    """The assignment with the most pairs and, among those, the largest weight (Hungarian method)."""
    rows, columns = len(weights), len(weights[0]) if weights else 0
    size = max(rows, columns)
    if size == 0:
        return 0, 0.0, []
    big = 1000.0  # one more pair always outweighs any sum of weights (each below 4)

    def cost_of(row: int, column: int) -> float:
        weight = weights[row][column] if row < rows and column < columns else None
        return 0.0 if weight is None else -(big + weight)
    cost = [[cost_of(r, c) for c in range(size)] for r in range(size)]
    u, v, p, way = [0.0] * (size + 1), [0.0] * (size + 1), [0] * (size + 1), [0] * (size + 1)
    for r in range(1, size + 1):
        p[0], column = r, 0
        minimum, used = [float("inf")] * (size + 1), [False] * (size + 1)
        while True:
            used[column] = True
            row, delta, nxt = p[column], float("inf"), 0
            for c in range(1, size + 1):
                if not used[c]:
                    current = cost[row - 1][c - 1] - u[row] - v[c]
                    if current < minimum[c]:
                        minimum[c], way[c] = current, column
                    if minimum[c] < delta:
                        delta, nxt = minimum[c], c
            for c in range(size + 1):
                if used[c]:
                    u[p[c]] += delta
                    v[c] -= delta
                else:
                    minimum[c] -= delta
            column = nxt
            if p[column] == 0:
                break
        while column:
            previous = way[column]
            p[column] = p[previous]
            column = previous
    pairs = [(p[c] - 1, c - 1) for c in range(1, size + 1)
             if p[c] and p[c] - 1 < rows and c - 1 < columns and weights[p[c] - 1][c - 1] is not None]
    return len(pairs), round(sum(weights[r][c] for r, c in pairs), 6), pairs  # type: ignore[misc]


def match(expected: Sequence[dict[str, Any]], actual: Sequence[dict[str, Any]], source: str,
          days: Sequence[Sequence[bool]] | None = None) -> tuple[list[tuple[int, int]], set[int]]:
    """Pairs (expected index, actual index) and the expected indices whose pairing is ambiguous."""
    weights = [[identity(item, other, source, bool(days and days[i][j])) for j, other in enumerate(actual)]
               for i, item in enumerate(expected)]
    count, total, pairs = _assign(weights)
    ambiguous: set[int] = set()
    for row, column in pairs:
        forbidden = [[None if (r, c) == (row, column) else weights[r][c] for c in range(len(actual))]
                     for r in range(len(expected))]
        other_count, other_total, _pairs = _assign(forbidden)
        if (other_count, other_total) == (count, total):
            ambiguous.add(row)
    return pairs, ambiguous


__all__ = ["VERB_GROUPS", "evidence_score", "identity", "match", "normalize", "same_word", "title_score", "tokens",
           "verbs", "verified"]
