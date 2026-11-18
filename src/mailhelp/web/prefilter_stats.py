"""7.7.5: the prefilter section of /auswertung – avoided relevance calls and an estimated saving.

The saving is always an estimate: the median tokens and costs of the real relevance calls of the
same period, per provider, times the avoided calls. Without real calls to compare with the page
says so instead of showing zero.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from statistics import median
from typing import Any

from ..domain.mail import MailState
from ..domain.relevance import IrrelevantSenders, PrefilterHits, RuleHits, SenderRule
from ..i18n import msg, tr
from ..mailbox.sender_filter import AUTOMATED, LISTS
from ..persistence.storage import CorruptState, JsonStore
from ..processing.perspective import SELF_NOTE_REASON
from ..state_names import MAIL_PREFIX, is_mail_state
from .pages import e

CATEGORIES = {
    "vip": msg("VIP-Absender"),
    "rule": msg("Sperrregel"),
    "header": msg("Kopfzeilen-Vorfilter"),
    "briefing": msg("Eigenes Briefing"),
    "iserv": msg("IServ-Konto"),
    "no_topic": msg("Postfach ohne Thema"),
    "self_mail": msg("Eigene Notiz"),
}
REASONS = {
    "Eigenes Postfach-Briefing": 'briefing',
    "IServ-Elternbrief: immer relevant": 'iserv',
    "Kein relevantes Thema für dieses Postfach": 'no_topic',
    SELF_NOTE_REASON: 'self_mail',
}
# Rules without a hit for this long are offered for tidying up.
STALE_DAYS = 90


def category(state: MailState) -> str | None:
    """Why a mail needed no relevance call, or ``None`` if the model decided."""
    if state.prefilter_rule is not None:
        if state.prefilter_rule in {AUTOMATED, LISTS}:
            return "header"
        return "vip" if state.relevance is not None and state.relevance.decision == "relevant" else "rule"
    return REASONS.get(state.relevance.reason) if state.relevance is not None else None


def avoided(store: JsonStore, since: datetime) -> Counter[str]:
    counts: Counter[str] = Counter()
    for name in store.names(MAIL_PREFIX):
        if not is_mail_state(name):
            continue
        try:
            state = store.peek_model(name, MailState)
        except CorruptState:
            continue
        if state is not None and state.created_at >= since and (kind := category(state)) is not None:
            counts[kind] += 1
    return counts


def estimate(records: list[dict[str, Any]], since: datetime, usd_per_eur: float | None) -> dict[str, float] | None:
    """Median tokens and euros of one real relevance call in the period; ``None`` without any."""
    calls = [row for row in records
             if row["stage"] == "relevance" and datetime.fromisoformat(row["started_at"]) >= since]
    if not calls:
        return None
    tokens = [sum(value or 0 for value in row["tokens"].values()) for row in calls]
    euros = []
    for row in calls:
        if row["provider"] == "ollama":
            euros.append(row["duration_ms"] / 3_600_000 * row["power_watts"] / 1000 * row["electricity_price"])
        elif row["cost_usd"] is not None and usd_per_eur:
            euros.append(float(row["cost_usd"]) / usd_per_eur)
    return {"tokens": float(median(tokens)), "euros": float(median(euros)) if euros else 0.0,
            "priced": float(len(euros))}


def _rule_label(blocked: IrrelevantSenders, rule_id: str) -> str:
    rule = next((item for item in blocked.rules if item.id == rule_id), None)
    if rule is not None:
        return rule.value
    legacy = {SenderRule.identity("address", value, None): value for value in blocked.addresses}
    legacy |= {SenderRule.identity("domain", value, None): value for value in blocked.domains}
    names = {AUTOMATED: msg("Automatische Systemmails"), LISTS: msg("Newsletter und Verteiler")}
    return legacy.get(rule_id) or names.get(rule_id) or rule_id


def prefilter_section(store: JsonStore, records: list[dict[str, Any]], blocked: IrrelevantSenders,
                      hits: PrefilterHits, now: datetime, days: int, usd_per_eur: float | None) -> str:
    since = now - timedelta(days=days)
    counts, total = avoided(store, since), 0
    rows = ""
    for key, label in CATEGORIES.items():
        total += counts[key]
        rows += f"<tr><th>{tr(label)}</th><td>{counts[key]}</td></tr>"
    typical = estimate(records, since, usd_per_eur)
    if typical is None:
        saving = tr("Ersparnis nicht schätzbar: In diesem Zeitraum gab es keine echte Relevanzprüfung zum Vergleich.")
    else:
        saving = tr("Geschätzt gespart: etwa {tokens} Tokens und {euros} € (Median je echter Relevanzprüfung im "
                    "Zeitraum × vermiedene Aufrufe).", tokens=round(typical["tokens"] * total),
                    euros=f"{typical['euros'] * total:.2f}".replace(".", ","))
    top = sorted(hits.rules.items(), key=lambda item: -item[1].count)[:5]
    busiest = "".join(f"<li>{e(_rule_label(blocked, rule_id))}: {item.count}</li>" for rule_id, item in top)
    stale_before = now - timedelta(days=STALE_DAYS)
    stale = [rule.value for rule in blocked.rules if rule.created_at < stale_before
             and ((hit := hits.rules.get(rule.id, RuleHits())).last is None or hit.last < stale_before)]
    body = (f'<section class="card" id="vorfilter"><h2>{tr("Vorfilter")}</h2>'
            f'<p>{tr("Ohne Relevanzprüfung entschieden: {count} Mails.", count=total)}</p>'
            f'<table class="kpi-table"><tbody>{rows}</tbody></table><p class="meta">{e(saving)}</p>')
    if busiest:
        body += f'<h3>{tr("Regeln mit den meisten Treffern")}</h3><ul>{busiest}</ul>'
    if stale:
        body += (f'<h3>{tr("Seit {days} Tagen ohne Treffer", days=STALE_DAYS)}</h3>'
                 f'<ul>{"".join(f"<li>{e(value)}</li>" for value in stale)}</ul>')
    return body + f'<p><a href="/einstellungen/absender">{tr("Absender-Regeln verwalten")}</a></p></section>'


__all__ = ["CATEGORIES", "avoided", "category", "estimate", "prefilter_section"]
