"""Pages built from the review read models: overview and proposal detail.

They show the same content as the compact Telegram card; description and
evidence can be expanded.  Every value is escaped.  Links contained in mails
are shown as plain text; only an ``https`` video link and the link of an entry
Mailhelp created itself are clickable.
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlsplit

from ..models import ProposalKind, ProposalStatus
from ..review.views import MailView, Overview, ProposalView, RelevanceView
from .pages import e, layout, notice

# Renders the action forms of a card (phase 6); None shows the card read-only.
Actions = Callable[[ProposalView], str]
RelevanceActions = Callable[[RelevanceView], str]

_STATE_BADGE = {
    ProposalStatus.PENDING_CONFIRMATION: "accent",
    ProposalStatus.NEEDS_CLARIFICATION: "warn",
    ProposalStatus.CREATED: "ok",
    ProposalStatus.SIMULATED: "ok",
    ProposalStatus.REJECTED: "",
    ProposalStatus.FAILED: "danger",
    ProposalStatus.UNCERTAIN: "warn",
    ProposalStatus.CONFIRMED: "accent",
    ProposalStatus.WRITING: "accent",
    ProposalStatus.ALREADY_EXISTS: "info",
}



def https_link(value: str | None) -> str | None:
    """The value if it is an absolute https URL, else None."""
    if not value:
        return None
    parts = urlsplit(value)
    return value if parts.scheme == "https" and parts.netloc else None


def _fact(icon: str, text: str, label: str) -> str:
    return (f'<li><span class="icon" aria-hidden="true">{icon}</span>'
            f'<span><span class="visually-hidden">{label}: </span>{text}</span></li>')


def _expandable(short: str, full: str, label: str, quote: bool) -> str:
    tag = "blockquote" if quote else "p"
    if short == full:
        return f"<{tag}>{e(short)}</{tag}>"
    return (f"<{tag}>{e(short)}</{tag}><details><summary>{label} vollständig anzeigen</summary>"
            f'<p class="full">{e(full)}</p></details>')


def proposal_card(view: ProposalView, *, actions: Actions | None = None,
                  detail_link: bool = True) -> str:
    card = view.card
    event = card.kind == ProposalKind.EVENT
    facts = []
    if card.when:
        facts.append(_fact("🕒", e(card.when), "Zeit"))
    if card.due:
        facts.append(_fact("🕒", f"Fällig: {e(card.due)}", "Frist"))
    if card.location:
        facts.append(_fact("📍", e(card.location), "Ort"))
    if card.video_link:
        link = https_link(card.video_link)
        text = (f'<a href="{e(link)}" rel="noopener noreferrer" target="_blank">{e(link)}</a>'
                if link else e(card.video_link))
        facts.append(_fact("🔗", text, "Videolink"))
    labels = [f'<span class="badge {_STATE_BADGE[view.status]}">{e(view.state)}</span>']
    if view.current:
        labels.append('<span class="badge accent">Aktuell in Telegram</span>')
    if view.queued:
        labels.append('<span class="badge">Folgt in Telegram</span>')
    for value, prefix in ((card.responsibility, "Zuständig"), (card.certainty, "Sicherheit"),
                          (card.classification, "Einordnung")):
        if value:
            labels.append(f'<span class="badge warn">{prefix}: {e(value)}</span>')
    warnings = []
    # With open questions the answers decide whether it can be created.
    if not card.writable and not card.questions and view.status in {
            ProposalStatus.PENDING_CONFIRMATION, ProposalStatus.NEEDS_CLARIFICATION}:
        warnings.append(notice("Kann nicht automatisch angelegt werden – bitte manuell prüfen.", "warn"))
    elif card.test_mode:
        warnings.append(notice("Testmodus: Der Eintrag wird nur simuliert.", "info"))
    questions = ""
    if card.questions:
        items = "".join(f"<li>{e(question)}</li>" for question in card.questions)
        questions = f'<div class="questions"><p>Offene Fragen</p><ul>{items}</ul></div>'
    description = (_expandable(card.description, card.description_full or card.description,
                               "Beschreibung", False) if card.description else "")
    evidence = _expandable(card.evidence, card.evidence_full, "Beleg", True)
    created = https_link(view.external_link)
    created_link = (f'<p><a href="{e(created)}" rel="noopener noreferrer" target="_blank">'
                    f'{"Im Kalender öffnen" if event else "In Todoist öffnen"}</a></p>'
                    if created else "")
    version = f" · Version {view.version}" if view.version > 1 else ""
    title = e(card.title)
    if detail_link:
        title = f'<a href="/vorschlag/{e(view.mail_id)}/{e(view.proposal_id)}">{title}</a>'
    diff_box = ""
    if view.time_changes:
        diff_lines = [f"<li>{e(str(change))}</li>" for change in view.time_changes]
        diff_box = ('<div class="diff-box"><p>🔄 <strong>Terminänderung gegenüber Google Kalender:</strong></p>'
                    f'<ul>{"".join(diff_lines)}</ul></div>')
    if view.duplicate_match is not None:
        dm = view.duplicate_match
        dup_url = https_link(getattr(dm, "external_link", None))
        dup_text = e(getattr(dm, "details", "Bereits vorhanden"))
        if dup_url:
            labels.append(f'<span class="badge info"><a href="{e(dup_url)}" target="_blank" '
                          f'rel="noopener noreferrer">{dup_text} ↗</a></span>')
        else:
            labels.append(f'<span class="badge info">{dup_text}</span>')
    current = " current" if view.current else ""
    details = (f'<p class="card-links"><a class="button small" '
               f'href="/vorschlag/{e(view.mail_id)}/{e(view.proposal_id)}">Details</a></p>'
               if detail_link else "")
    return f"""<article class="card{current}" id="v-{e(view.mail_id)}-{e(view.proposal_id)}">
<p class="kind">{"📅 Termin" if event else "✅ Aufgabe"}{version}</p>
<div class="card-head"><h3>{title}</h3></div>
<p class="source">✉️ {e(view.sender)} · {e(view.subject)}</p>
<p class="labels">{" ".join(labels)}</p>
<ul class="facts">{"".join(facts)}</ul>
{"".join(warnings)}{diff_box}{questions}{description}{evidence}{created_link}{details}
{actions(view) if actions else ""}
</article>"""


def relevance_card(view: RelevanceView, actions: RelevanceActions | None = None,
                   detail_link: bool = True) -> str:
    details = (f'<p class="card-links"><a class="button small" href="/mail/{e(view.mail_id)}">'
               'Details</a></p>' if detail_link else "")
    return f"""<article class="card" id="r-{e(view.mail_id)}">
<p class="kind">❔ Relevanz</p>
<h3>{e(view.subject)}</h3>
<p class="source">✉️ {e(view.sender)}</p>
<p>Ist diese Mail für dich relevant? Bis zur Antwort wartet die Mailanalyse.</p>
{details}
{actions(view) if actions else ""}
</article>"""


def overview_page(overview: Overview, *, actions: Actions | None = None,
                  relevance_actions: RelevanceActions | None = None,
                  message: str | None = None, message_kind: str = "ok",
                  before: str = "", empty: str | None = None) -> str:
    """*before* precedes the heading (filters); *empty* replaces the default empty state."""
    count = len(overview.open) + len(overview.relevance)
    parts = [f'<h1>Offene Entscheidungen <span class="count">{count}</span></h1>']
    if message:
        parts.append(notice(message, message_kind))
    if overview.damaged:
        parts.append(notice(f"{overview.damaged} gespeicherte Datensätze sind beschädigt und werden "
                            "nicht angezeigt. Bitte die Protokolle prüfen.", "error"))
    items = []
    if overview.relevance:
        items.append("<h2>Relevanz klären</h2>")
        items.extend(relevance_card(view, relevance_actions) for view in overview.relevance)
    if overview.open:
        items.append("<h2>Vorschläge</h2>")
        items.extend(proposal_card(view, actions=actions) for view in overview.open)
    if items:
        # On wide screens app.js turns this list into the master pane of a split view.
        parts.append('<div class="open-items">' + "\n".join(items) + "</div>")
    if not overview.open and not overview.relevance:
        parts.append(empty if empty is not None else
                     '<p class="empty">Nichts zu entscheiden. Neue Vorschläge erscheinen hier automatisch.</p>')
    if overview.recent:
        items = []
        for view in overview.recent:
            items.append(
                f'<li><span><a href="/vorschlag/{e(view.mail_id)}/{e(view.proposal_id)}">'
                f'{e(view.card.title)}</a></span>'
                f'<span class="badge {_STATE_BADGE[view.status]}">{e(view.state)}</span></li>')
        parts.append(f'<h2>Zuletzt erledigt</h2><ul class="recent">{"".join(items)}</ul>')
    return layout("Offen", "\n".join(parts), active="/", fingerprint=overview.fingerprint, before=before)


VISION_LABELS = {
    "read": "Per Bilderkennung gelesen",
    "no_text": "Bild ohne lesbaren Text",
    "failed": "Bilderkennung fehlgeschlagen",
    "skipped_small": "Übersprungen (Symbol oder Logo)",
    "skipped_limit": "Übersprungen (Bildlimit je Mail)",
    "skipped_oversized": "Übersprungen (Bild zu groß)",
    "skipped_unreadable": "Bild nicht lesbar",
}


def mail_section(mail: MailView | None, sender_actions: str = "") -> str:
    """The complete stored mail as text; links in it stay plain text."""
    if mail is None:
        return ""
    facts = [("Von", mail.sender), ("Betreff", mail.subject)]
    if mail.received:
        facts.append(("Datum", mail.received))
    rows = "".join(f"<dt>{label}</dt><dd>{e(value)}</dd>" for label, value in facts)
    notes = []
    if mail.attachments_omitted:
        notes.append(f"{mail.attachments_omitted} Anhang/Anhänge nicht ausgewertet und nicht gespeichert.")
    if mail.text_shortened:
        notes.append("Der Text wurde für die Auswertung gekürzt.")
    if mail.text is None:
        body = notice("Der vollständige Mailtext ist nicht mehr gespeichert "
                      "(automatische Löschung nach Abschluss und Aufbewahrungsfrist).", "info")
    else:
        body = f'<div class="mail-text">{e(mail.text)}</div>'
    hints = "".join(f'<p class="meta">{e(note)}</p>' for note in notes)
    att_section = ""
    if mail.extracted_attachments:
        status_labels = {
            "success": "Text extrahiert",
            "no_text_found": "Kein Text gefunden",
            "encrypted": "Verschlüsselt / Passwortgeschützt",
            "skipped_oversized": "Übersprungen (zu groß)",
            "error": "Fehler beim Lesen",
            "unsupported_format": "Nicht unterstütztes Format",
        }
        att_items = []
        for att in mail.extracted_attachments:
            fn = att.filename
            st = att.extraction_status
            st_text = status_labels.get(st, st)
            badge_class = "ok" if st == "success" else "warn"
            if att.vision is not None:
                st_text = VISION_LABELS.get(att.vision, att.vision)
                badge_class = "ok" if att.vision == "read" else "warn"
            att_items.append(
                f'<li>📎 <strong>{e(fn)}</strong> <span class="badge {badge_class}">{e(st_text)}</span></li>'
            )
            preview = att.preview
            if preview is not None:
                url = f'/mail/{e(mail.mail_id)}/anhang/{preview.index}'
                size = f'{max(1, round(preview.size_bytes / 1024))} KB'
                if preview.width is not None:
                    size = f'{preview.width} × {preview.height} px · {size}'
                text = att.text
                recognized = (f'<details><summary>Erkannten Text anzeigen</summary><pre>{e(text)}</pre></details>'
                              if text else '<p class="meta">Kein erkannter Text gespeichert.</p>')
                att_items.append(f'<li class="image-preview"><a href="{url}" data-lightbox '
                                 f'aria-label="{e(fn)} vergrößern">'
                                 f'<img src="{url}" alt="{e(fn)}" loading="lazy"></a>'
                                 f'<p class="meta">{e(fn)} · {size}</p>{recognized}</li>')
        att_section = (f'<div class="attachments"><p><strong>Anhänge ({len(mail.extracted_attachments)}):</strong></p>'
                       f'<ul>{"".join(att_items)}</ul></div>')
    cal_section = ""
    if mail.calendar_events:
        cal_section = (f'<div class="notice info"><p>📅 <strong>{len(mail.calendar_events)} '
                       'ICS-Kalenderanhang/-anhänge erkannt</strong></p></div>')
    return f"""<section class="card mail" id="mail" aria-labelledby="mail-titel">
<h2 id="mail-titel">Mail</h2>
<dl class="mail-head">{rows}</dl>
{sender_actions}{att_section}{cal_section}{body}{hints}
</section>"""


def disclosure(summary: str, body: str, *, opened: bool = False) -> str:
    """A secondary section, collapsed unless it is needed for the decision."""
    if not body:
        return ""
    return (f'<details class="disclosure"{" open" if opened else ""}><summary>{summary}</summary>'
            f'{body}</details>')


def detail_page(view: ProposalView, *, actions: Actions | None = None,
                mail: MailView | None = None, after: str = "") -> str:
    # Image previews are the evidence to compare with; they are shown at once.
    previews = mail is not None and any(item.preview is not None for item in mail.extracted_attachments)
    content = f"""<p><a href="/">← Zur Übersicht</a></p>
<h1>{"Termin" if view.card.kind == ProposalKind.EVENT else "Aufgabe"}</h1>
{proposal_card(view, actions=actions, detail_link=False)}
{disclosure("Quellbeleg aus E-Mail / Anhang", mail_section(mail), opened=previews)}"""
    return layout(view.card.title, content, active="/", after=after)


def mail_page(mail: MailView, relevance: RelevanceView | None = None,
              actions: RelevanceActions | None = None, *, sender_actions: str = "",
              message: str | None = None, message_kind: str = "ok", after: str = "") -> str:
    """A mail on its own, with the relevance question if it is still open."""
    question = relevance_card(relevance, actions, detail_link=False) if relevance else ""
    result = notice(message, message_kind) if message else ""
    content = f"""<p><a href="/">← Zur Übersicht</a></p>
<h1>Mail</h1>
{result}{question}
{mail_section(mail, sender_actions)}"""
    return layout(mail.subject, content, active="/", after=after)


# Compatibility for callers of the original renderer module (public names only;
# deprecated, removed in 3.0 – import from status_pages).
from .status_pages import ANALYSIS_LABELS, COMMAND_LABELS, RUN_LABELS, ServiceInfo, status_page

__all__ = ["ANALYSIS_LABELS", "COMMAND_LABELS", "RUN_LABELS", "ServiceInfo",
           "detail_page", "disclosure", "https_link", "mail_page", "mail_section",
           "overview_page", "proposal_card", "relevance_card", "status_page"]
