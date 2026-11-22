"""HTML of the proposal evaluation and acceptance rates page (Planung 6.5, 3.1)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ..i18n import msg, stored, tr
from ..review.prefilter_hints import PrefilterHint
from ..review.proposal_evaluation import PERIODS, ProposalEvaluationReport, SenderHint
from ..review.reject_reasons import REJECT_REASONS
from .actions import new_key
from .forms import select
from .pages import e, page_head
from .toolbar import toolbar

_SENDER_HINT_PAGE_TEXT_1 = msg(
    '<dl class="kpi-grid"><div '
    'class="kpi-tile"><dt>Annahmequote</dt><dd><strong>{p0}</strong> <span '
    'class="meta">({p1} von {p2} angenommen)</span></dd></div><div '
    'class="kpi-tile"><dt>Häufigster Grund</dt><dd><strong>{p3}</strong></dd></div><div '
    'class="kpi-tile"><dt>Empfohlene '
    "Maßnahme</dt><dd><strong>{p4}</strong></dd></div></dl>"
)

_SENDER_HINT_PAGE_TEXT_2 = msg(
    '<section class="stack"><h2>Gespeicherte Mails dieses Absenders ({p0})</h2><div '
    'class="table-scroll" tabindex="0" role="region" aria-label="Gespeicherte '
    'Mails"><table><thead><tr><th>Betreff</th><th>Datum</th><th>Vorschläge</th></tr></thea'
    "d><tbody>{p1}</tbody></table></div></section>"
)

_SENDER_HINT_PAGE_TEXT_3 = msg(
    '<div class="actions"><form method="post" '
    'action="/lernen/absender-hinweis/uebernehmen"><input type="hidden" name="csrf" '
    'value="{p0}"><input type="hidden" name="key" value="{p1}"><input type="hidden" '
    'name="sender" value="{p2}"><input type="hidden" name="expected_hash" '
    'value="{p3}"><button class="button primary" type="submit">In Vorfilter '
    'aufnehmen</button></form><form method="post" '
    'action="/lernen/absender-hinweis/nicht-mehr-vorschlagen"><input type="hidden" '
    'name="csrf" value="{p4}"><input type="hidden" name="sender" value="{p5}"><button '
    'class="button" type="submit">Nicht mehr vorschlagen</button></form><p '
    'class="card-links"><a class="button link" '
    'href="/lernen/vorschlaege">Zurück</a></p></div>'
)

PERIOD_CHOICES = [(str(k), label) for k, label in PERIODS]


def _quote_fmt(val: float) -> str:
    return f"{round(val)} %"


def _table_section(ident: str, title: str, head: str, rows: str) -> str:
    """A titled, keyboard-scrollable table of the evaluation page."""
    return (f'<section id="{ident}" class="stack"><h2>{title}</h2>'
            f'<div class="table-scroll" tabindex="0" role="region" aria-label="{title}">'
            f'<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div></section>')


def _hints_section(hints: list[SenderHint] | tuple[SenderHint, ...]) -> str:
    hints_html = ""
    if hints:
        hint_cards = "".join(
            tr(
                (
                    '<div class="notice warn sender-hint"><p><strong>Hinweis zum '
                    'Absender:</strong> {p0}</p><p class="card-links"><a '
                    'class="button primary small" '
                    'href="/lernen/absender-hinweis?sender={p1}">Ansehen</a></p></div>'
                ),
                p0=e(stored(h.trigger_sentence)),
                p1=quote(h.sender),
            )
            for h in hints
        )
        hints_html = tr(
            ('<section class="stack" id="absender-hinweise"><h2>Hinweise zu Absendern</h2>{p0}</section>'),
            p0=hint_cards,
        )
    return hints_html


def _post(action: str, label: str, style: str, **fields: str) -> str:
    inputs = "".join(f'<input type="hidden" name="{name}" value="{e(value)}">' for name, value in fields.items())
    return (f'<form method="post" action="{action}" class="inline-form">{inputs}'
            f'<button class="{style}">{e(label)}</button></form>')


def prefilter_hints_section(hints: list[PrefilterHint], csrf: str) -> str:
    """7.7.5: suggested prefilter rules; taking one over saves it as a rule (origin ``hint``)."""
    if not hints:
        return ""
    cards = ""
    for hint in hints:
        if hint.action == "vip":
            text = tr("{count} Mails von {value} führten jeweils zu bestätigten Vorschlägen. Als VIP einstufen?",
                      count=hint.count, value=hint.value)
        elif hint.kind == "domain":
            text = tr("{count} Mails von Adressen der Domain {value} wurden von der KI als irrelevant eingestuft. "
                      "Ganze Domain künftig ohne KI-Aufruf aussortieren?", count=hint.count, value=hint.value)
        else:
            text = tr("{count} Mails von {value} wurden von der KI als irrelevant eingestuft. Künftig ohne "
                      "KI-Aufruf aussortieren?", count=hint.count, value=hint.value)
        subjects = "".join(f"<li>{e(subject)}</li>" for subject in hint.subjects)
        take = _post("/einstellungen/absender/regel", tr("Als Regel übernehmen"), "button primary small",
                     csrf=csrf, key=new_key(), art=hint.kind, wert=hint.value, aktion=hint.action, herkunft="hint")
        dismiss = _post("/lernen/absender-hinweis/nicht-mehr-vorschlagen", tr("Nicht mehr vorschlagen"),
                        "button small", csrf=csrf, sender=hint.value)
        cards += (f'<div class="notice info prefilter-hint"><p>{e(text)}</p><ul class="meta">{subjects}</ul>'
                  f'<p class="card-links">{take}{dismiss}</p></div>')
    return (f'<section class="stack" id="vorfilter-hinweise"><h2>{tr("Hinweise für Vorfilter-Regeln")}</h2>'
            f'<p class="meta">{tr("Aus gespeicherten Entscheidungen, ohne KI-Aufruf ermittelt.")}</p>{cards}</section>')


def _dismissed_section(dismissed: list[str] | tuple[str, ...], csrf: str) -> str:
    dismissed_html = ""
    if dismissed:
        items = "".join(
            tr(
                (
                    '<li><span>{p0}</span> <form method="post" '
                    'action="/lernen/absender-hinweis/wieder-zulassen" '
                    'style="display:inline;"><input type="hidden" name="csrf" '
                    'value="{p1}"><input type="hidden" name="sender" '
                    'value="{p2}"><button class="button small" type="submit">Wieder '
                    "zulassen</button></form></li>"
                ),
                p0=e(s),
                p1=e(csrf),
                p2=e(s),
            )
            for s in dismissed
        )
        dismissed_html = tr(
            (
                '<details class="stack" id="verworfene-hinweise"><summary>Zuvor '
                "verworfene Absender-Hinweise "
                "({p0})</summary><ul>{p1}</ul></details>"
            ),
            p0=len(dismissed),
            p1=items,
        )
    return dismissed_html


def _summary_tiles(report: ProposalEvaluationReport) -> str:
    s = report.summary
    tiles = (
        tr(
            (
                '<dl class="kpi-grid"><div class="kpi-tile"><dt>Annahmequote '
                'gesamt</dt><dd><strong>{p0}</strong> <span class="meta">({p1} '
                "von {p2} angenommen)</span></dd></div><div "
                'class="kpi-tile"><dt>Aufgaben</dt><dd><strong>{p3}</strong> '
                '<span class="meta">({p4} von {p5} '
                "angenommen)</span></dd></div><div "
                'class="kpi-tile"><dt>Termine</dt><dd><strong>{p6}</strong> <span '
                'class="meta">({p7} von {p8} angenommen)</span></dd></div>'
            ),
            p0=_quote_fmt(s.total_quote),
            p1=s.total_accepted,
            p2=s.total_decided,
            p3=_quote_fmt(s.tasks_quote),
            p4=s.tasks_accepted,
            p5=s.tasks_decided,
            p6=_quote_fmt(s.events_quote),
            p7=s.events_accepted,
            p8=s.events_decided,
        )
        + (
            tr(
                (
                    '<div class="kpi-tile"><dt>Wieder '
                    'entfernt</dt><dd><strong>{p0}</strong> <span class="meta">({p1} '
                    "Aufgaben, {p2} Termine)</span></dd></div>"
                ),
                p0=s.total_removed,
                p1=s.tasks_removed,
                p2=s.events_removed,
            )
            if s.total_removed > 0
            else ""
        )
        + "</dl>"
    )
    return tiles


def _weekly_table(report: ProposalEvaluationReport) -> str:
    # Weekly breakdown
    weekly_rows = "".join(
        f'<tr><td>{e(w.week_label)}</td>'
        f'<td>{w.decided}</td>'
        f'<td>{w.accepted}</td>'
        f'<td>{w.rejected}</td>'
        f'<td>{w.removed}</td>'
        f'<td>{_quote_fmt(w.quote)}</td></tr>'
        for w in report.weeks
    )
    weekly_table = _table_section(
        "wochen",
        msg("Verlauf je Woche"),
        tr(
            
                "<th>Woche</th><th>Entschieden</th><th>Angenommen</th><th>Verworfen</th><th>"
                "Wieder entfernt</th><th>Annahmequote</th>"
            
        ),
        weekly_rows,
    )
    return weekly_table


def _topics_table(report: ProposalEvaluationReport, params: dict[str, Any], base_query: str) -> str:
    # Topic breakdown
    sort_topic = params.get("sort_topic", "decided")
    sorted_topics = list(report.topics)
    if sort_topic == "quote":
        sorted_topics.sort(key=lambda t: (t.quote, t.decided), reverse=True)
    elif sort_topic == "name":
        sorted_topics.sort(key=lambda t: t.topic_name.lower())
    else:
        sorted_topics.sort(key=lambda t: (t.decided, t.quote), reverse=True)

    topic_rows = "".join(
        f'<tr><td><a href="/mails?topic={quote(t.topic_id)}">{e(stored(t.topic_name))}</a></td>'
        f'<td>{t.decided}</td>'
        f'<td>{t.accepted}</td>'
        f'<td>{t.rejected}</td>'
        f'<td>{_quote_fmt(t.quote)}</td></tr>'
        for t in sorted_topics
    )
    topics_table = _table_section(
        msg("themen"),
        msg("Nach Thema"),
        tr(
            (
                '<th><a href="/lernen/vorschlaege?{p0}&amp;sort_topic=name">Thema</a></th><t'
                'h><a href="/lernen/vorschlaege?{p1}&amp;sort_topic=decided">Entschieden</a>'
                "</th><th>Angenommen</th><th>Verworfen</th><th><a "
                'href="/lernen/vorschlaege?{p2}&amp;sort_topic=quote">Annahmequote</a></th>'
            ),
            p0=f"{base_query}",
            p1=f"{base_query}",
            p2=f"{base_query}",
        ),
        topic_rows,
    )
    return topics_table


def _senders_table(report: ProposalEvaluationReport, params: dict[str, Any], base_query: str) -> str:
    # Sender breakdown
    sort_sender = params.get("sort_sender", "rejected")
    sorted_senders = list(report.senders)
    if sort_sender == "decided":
        sorted_senders.sort(key=lambda s: (s.decided, s.rejected), reverse=True)
    elif sort_sender == "quote":
        sorted_senders.sort(key=lambda s: (s.quote, s.decided), reverse=True)
    elif sort_sender == "name":
        sorted_senders.sort(key=lambda s: s.sender.lower())
    else:
        sorted_senders.sort(key=lambda s: (s.rejected, s.decided), reverse=True)

    sender_rows = []
    for s_item in sorted_senders:
        if s_item.sender == "Absender entfernt":
            sender_cell = e(tr("Absender entfernt"))
        else:
            sender_cell = f'<a href="/mails?q={quote(s_item.sender)}">{e(s_item.sender)}</a>'
        sender_rows.append(
            f'<tr><td>{sender_cell}</td>'
            f'<td>{s_item.decided}</td>'
            f'<td>{s_item.accepted}</td>'
            f'<td>{s_item.rejected}</td>'
            f'<td>{_quote_fmt(s_item.quote)}</td></tr>'
        )
    senders_table = _table_section(
        msg("absender"),
        msg("Nach Absender"),
        tr(
            (
                '<th><a href="/lernen/vorschlaege?{p0}&amp;sort_sender=name">Absender</a></t'
                'h><th><a href="/lernen/vorschlaege?{p1}&amp;sort_sender=decided">Entschiede'
                "n</a></th><th>Angenommen</th><th><a "
                'href="/lernen/vorschlaege?{p2}&amp;sort_sender=rejected">Verworfen</a></th>'
                '<th><a href="/lernen/vorschlaege?{p3}&amp;sort_sender=quote">Annahmequote</a></th>'
            ),
            p0=f"{base_query}",
            p1=f"{base_query}",
            p2=f"{base_query}",
            p3=f"{base_query}",
        ),
        "".join(sender_rows),
    )
    return senders_table


def _reasons_section(report: ProposalEvaluationReport) -> str:
    # Reasons breakdown (if any rejections)
    reasons_section = ""
    if report.summary.total_rejected > 0:
        reason_rows = "".join(
            f'<tr><td>{e(r.reason_label)}</td>'
            f'<td>{r.count}</td>'
            f'<td>{_quote_fmt(r.percentage)}</td></tr>'
            for r in report.reasons
        )
        reasons_section = _table_section(
            "gruende", msg("Gründe für Ablehnungen"), tr("<th>Grund</th><th>Anzahl</th><th>Anteil</th>"), reason_rows
        )
    return reasons_section


def proposal_evaluation_page(report: ProposalEvaluationReport, params: dict[str, Any],
                             hints: list[SenderHint] | tuple[SenderHint, ...] = (),
                             dismissed: list[str] | tuple[str, ...] = (),
                             prefilter: list[PrefilterHint] | None = None,
                             csrf: str = "") -> str:
    """Render the proposal evaluation page under /lernen/vorschlaege."""
    days_val = str(params.get("days", report.days))
    form = toolbar(
        "/lernen/vorschlaege",
        [select("days", msg("Zeitraum"), days_val, PERIOD_CHOICES)],
        submit=msg("Auswählen"),
        reset="/lernen/vorschlaege" if days_val != "90" and days_val != "0" else "",
    )
    head = page_head(
        msg("Vorschläge"),
        msg("Lernen"),
        tr("Annahmequote messen: Wie viele Vorschläge nimmst du an, wie viele verwirfst du?"),
        back=("/lernen", msg("Zurück zu Lernen")),
    )

    hints_html = _hints_section(hints) + prefilter_hints_section(prefilter or [], csrf)
    dismissed_html = _dismissed_section(dismissed, csrf)

    if report.empty:
        return (
            head
            + form
            + hints_html
            + tr('<p class="empty">In diesem Zeitraum liegen keine entschiedenen Vorschläge vor.</p>')
            + dismissed_html
        )

    base_query = f"days={e(days_val)}"
    return (head + form + hints_html + _summary_tiles(report) + _weekly_table(report)
            + _topics_table(report, params, base_query) + _senders_table(report, params, base_query)
            + _reasons_section(report) + dismissed_html)


def sender_hint_page(hint: SenderHint, mails: list[dict[str, Any]], csrf: str,
                     expected_hash: str | None = None) -> str:
    """Render the preview and confirmation page for an identified sender (Planung 6.5, 3.3)."""
    head = page_head(
        tr("Absender: {p0}", p0=hint.sender),
        msg("Lernen"),
        hint.trigger_sentence,
        back=("/lernen/vorschlaege", msg("Zurück zu Vorschläge")),
    )
    quote_str = _quote_fmt(hint.acceptance_rate * 100)
    reason_label = (
        REJECT_REASONS.get(hint.most_frequent_reason, msg("Keine Angabe"))
        if hint.most_frequent_reason
        else msg("Keine Angabe")
    )
    action_label = (
        msg("In den Absender-Vorfilter aufnehmen")
        if hint.recommended_action == "filter"
        else msg("Regellernlauf für diesen Absender")
    )

    stats = tr(
        (_SENDER_HINT_PAGE_TEXT_1),
        p0=quote_str,
        p1=hint.accepted,
        p2=hint.total,
        p3=e(reason_label),
        p4=e(action_label),
    )

    mail_rows = []
    for m in mails:
        mail_id = m.get("id", "")
        subject = m.get("subject", msg("Ohne Betreff"))
        date_str = m.get("date", "—")
        proposals = m.get("proposals", [])
        prop_badges = []
        for p in proposals:
            title = p.get("title", msg("Vorschlag"))
            is_acc = p.get("is_accepted", False)
            badge_class = "ok" if is_acc else "muted"
            prefix = msg("Angenommen") if is_acc else msg("Verworfen")
            prop_badges.append(f'<span class="badge {badge_class}">{prefix}: {e(title)}</span>')
        mail_rows.append(
            f'<tr><td><a href="/mail/{e(mail_id)}">{e(subject)}</a></td>'
            f'<td>{e(date_str)}</td>'
            f'<td>{" ".join(prop_badges) if prop_badges else "—"}</td></tr>'
        )

    mail_table = tr(
        (_SENDER_HINT_PAGE_TEXT_2),
        p0=len(mails),
        p1="".join(mail_rows),
    )

    actions = tr(
        (_SENDER_HINT_PAGE_TEXT_3),
        p0=e(csrf),
        p1=new_key(),
        p2=e(hint.sender),
        p3=e(expected_hash or ""),
        p4=e(csrf),
        p5=e(hint.sender),
    )

    return head + stats + mail_table + actions


def learning_run_hint_banner(message: str, csrf: str) -> str:
    """Banner for new rule learning run hint (Planung 6.5, 3.4)."""
    return tr(
        (
            '<div class="notice info learning-hint"><p><strong>Lernlauf '
            'empfohlen:</strong> {p0}</p><div class="actions"><a class="button small '
            'primary" href="/lernen/entscheidungen">Lernlauf vorbereiten</a><form '
            'method="post" action="/lernen/hinweis-ausblenden" '
            'style="display:inline;"><input type="hidden" name="csrf" '
            'value="{p1}"><button class="button small" '
            'type="submit">Ausblenden</button></form></div></div>'
        ),
        p0=f"{e(message)}",
        p1=f"{e(csrf)}",
    )
