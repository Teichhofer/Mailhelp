"""Pages built from the review read models: overview and proposal detail.

They show the same content as the compact Telegram card; description and
evidence can be expanded.  Every value is escaped.  Links contained in mails
are shown as plain text; only an ``https`` video link and the link of an entry
Mailhelp created itself are clickable.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from ..domain.proposal import CalendarSupplement, ProposalKind, ProposalStatus
from ..i18n import msg, stored, tr
from ..review.calendar_display import change_parts
from ..review.cards import sender_name
from ..review.views import MailView, Overview, ProposalView, RelevanceView
from .actions import conflict_boxes
from .pages import e, layout, notice, page_head

# Renders the action forms of a card (phase 6); None shows the card read-only.
Actions = Callable[[ProposalView], str]
RelevanceActions = Callable[[RelevanceView], str]

_STATE_BADGE = {
    ProposalStatus.PENDING_CONFIRMATION: "accent",
    ProposalStatus.NEEDS_CLARIFICATION: "warn",
    ProposalStatus.CREATED: "ok",
    ProposalStatus.REMOVED: "",
    ProposalStatus.SIMULATED: "ok",
    ProposalStatus.REJECTED: "",
    ProposalStatus.FAILED: "danger",
    ProposalStatus.UNCERTAIN: "warn",
    ProposalStatus.CONFIRMED: "accent",
    ProposalStatus.WRITING: "accent",
    ProposalStatus.VERIFYING: "accent",
    ProposalStatus.ALREADY_EXISTS: "info",
    ProposalStatus.MERGED: "info",
}


def https_link(value: str | None) -> str | None:
    """The value if it is an absolute https URL, else None."""
    if not value:
        return None
    parts = urlsplit(value)
    return value if parts.scheme == "https" and parts.netloc else None


def _fact(icon: str, text: str, label: str) -> str:
    return (
        f'<li data-fact="{e(label[:])}"><span class="icon" aria-hidden="true">{icon}</span>'
        f'<span><span class="visually-hidden">{tr(label)}: </span>{text}</span></li>'
    )


FULL_TEXT = {"Beschreibung": msg("Beschreibung vollständig anzeigen"), "Beleg": msg("Beleg vollständig anzeigen")}


def _expandable(short: str, full: str, label: str, quote: bool) -> str:
    # 5.0.7: the evidence is a styled quotation from the mail.
    tag, end = ('blockquote class="evidence"', "blockquote") if quote else ("p", "p")
    if short == full:
        return f"<{tag}>{e(short)}</{end}>"
    summary = tr(FULL_TEXT[label])
    return (f"<{tag}>{e(short)}</{end}><details><summary>{summary}</summary>"
            f'<p class="full">{e(full)}</p></details>')


def _card_facts(card: Any) -> list[str]:
    facts = []
    if card.when:
        when_text = f"{e(card.when)} · {e(card.reminder)}" if card.reminder else e(card.when)
        facts.append(_fact("🕒", when_text, msg("Zeit")))
    if card.due:
        facts.append(_fact("🕒", tr("Fällig: {due}", due=e(card.due)), msg("Frist")))
    if card.target_hint:
        facts.append(_fact("ℹ️", e(card.target_hint), msg("Aufgabenziel")))
    if card.location:
        facts.append(_fact("📍", e(card.location), msg("Ort")))
    if card.video_link:
        link = https_link(card.video_link)
        text = (f'<a href="{e(link)}" rel="noopener noreferrer" target="_blank">{e(link)}</a>'
                if link else e(card.video_link))
        facts.append(_fact("🔗", text, msg("Videolink")))
    return facts


def _metadata(card: Any) -> list[str]:
    return [
        f'<span class="badge warn">{tr(prefix)}: {e(value)}</span>'
        for value, prefix in (
            (card.responsibility, msg("Zuständig")),
            (card.certainty, msg("Sicherheit")),
            (card.classification, msg("Einordnung")),
        )
        if value
    ]


def _card_labels(view: ProposalView, *, metadata: bool = True) -> list[str]:
    card = view.card
    labels = [f'<span class="badge {_STATE_BADGE[view.status]}">{e(view.state)}</span>']
    if card.profile_label:
        labels.append('<span class="badge">' + tr('Zielprofil: {profile} · {target}', profile=e(card.profile_label),
                                                  target=e(card.target)) + '</span>')
    if view.current:
        labels.append(f'<span class="badge accent">{tr("Aktuell in Telegram")}</span>')
    if view.queued:
        labels.append(f'<span class="badge">{tr("Folgt in Telegram")}</span>')
    if metadata:
        labels.extend(_metadata(card))
    if view.duplicate_match is not None:
        labels.append(_duplicate_label(view.duplicate_match))
    return labels


def _duplicate_label(match: Any) -> str:
    url = https_link(getattr(match, "external_link", None))
    text = e(stored(getattr(match, "details", tr("Bereits vorhanden"))))
    if url:
        return (f'<span class="badge info"><a href="{e(url)}" target="_blank" '
                f'rel="noopener noreferrer">{text} ↗</a></span>')
    return f'<span class="badge info">{text}</span>'


def _card_warning(view: ProposalView) -> str:
    card = view.card
    # With open questions the answers decide whether it can be created.
    if not card.writable and not card.questions and view.status in {
            ProposalStatus.PENDING_CONFIRMATION, ProposalStatus.NEEDS_CLARIFICATION}:
        return notice(tr("Kann nicht automatisch angelegt werden – bitte manuell prüfen."), "warn")
    if card.test_mode:
        return notice(tr("Testmodus: Der Eintrag wird nur simuliert."), "info")
    return ""


def _plain_questions(view: ProposalView) -> tuple[str, ...]:
    """5.9.3: a field conflict is shown as a comparison, not again in the question list."""
    shown = {item.stored_question for item in view.conflicts}
    return tuple(question for question in view.card.questions if question not in shown)


def _card_questions(questions: Any) -> str:
    if not questions:
        return ""
    items = "".join(f"<li>{e(question)}</li>" for question in questions)
    return (f'<details class="questions"><summary>{tr('Offene Fragen ({count})', count=len(questions))}</summary>'
            f'<ul>{items}</ul></details>')


def _change_line(change: str) -> str:
    parts = change_parts(change)
    if parts is None:
        return f"<li>{e(change)}</li>"
    label, old, new = parts
    return f"<li>{e(stored(label))}: <del>{e(old)}</del> → <strong>{e(new)}</strong></li>"


def _diff_box(view: ProposalView) -> str:
    """Old values struck through, new ones bold; a cancellation as a red notice (4.6)."""
    if view.is_cancellation:
        return notice(tr("Termin im Kalender stornieren: Der bestehende Eintrag wird nach deiner "
                         "Bestätigung abgesagt."), "error")
    candidates = ""
    if view.calendar_candidates:
        items = "".join(f"<li>{e(label)}</li>" for label in view.calendar_candidates)
        candidates = (f'<div class="diff-box"><p>📅 <strong>{tr("Passende Kalendertermine:")}</strong></p>'
                      f"<ol>{items}</ol></div>")
    supplement = _supplement_box(view.calendar_supplement)
    if not view.time_changes:
        return candidates + supplement
    lines = "".join(_change_line(str(change)) for change in view.time_changes)
    heading = tr("Terminänderung gegenüber dem Kalender:")
    return (candidates + f'<div class="diff-box"><p>🔄 <strong>{heading}</strong></p>'
            f"<ul>{lines}</ul></div>" + supplement)


def _supplement_box(supplement: CalendarSupplement | None) -> str:
    """7.9: the confirmed addition to the existing entry: target, old link struck, new link bold."""
    if supplement is None:
        return ""
    heading = (tr("Bestehenden Termin aktualisieren: Videolink ergänzen") if supplement.previous is None
               else tr("Bestehenden Termin aktualisieren: Videolink ersetzen"))
    old = f"<del>{e(supplement.previous)}</del> → " if supplement.previous is not None else ""
    return (f'<div class="diff-box"><p>🔗 <strong>{heading}</strong></p>'
            f'<ul><li>{tr("Videolink")}: {old}<strong>{e(supplement.proposed)}</strong></li></ul></div>')


# 5.0.7: every kind has a stripe colour, a symbol and a text; colour is never the only mark.
KINDS = {
    "event": msg("📅 Termin"),
    "task": msg("✅ Aufgabe"),
    "change": msg("🔄 Terminänderung"),
    "cancel": msg("🚫 Terminabsage"),
}


def card_kind(view: ProposalView) -> str:
    """The kind of a card: appointment, task, or a change or cancellation of an appointment (4.6)."""
    if view.card.kind != ProposalKind.EVENT:
        return "task"
    if view.is_cancellation:
        return "cancel"
    return "change" if view.time_changes or view.calendar_supplement is not None else "event"


def proposal_card(view: ProposalView, *, actions: Actions | None = None,
                  detail_link: bool = True) -> str:
    card = view.card
    event = card.kind == ProposalKind.EVENT
    description = (
        _expandable(card.description, card.description_full or card.description, msg("Beschreibung"), False)
        if card.description
        else ""
    )
    evidence = _expandable(card.evidence, card.evidence_full, msg("Beleg"), True)
    kind = card_kind(view)
    metadata = " ".join(_metadata(card))
    context = (f'<details class="card-context"><summary class="context-label">{tr("Beschreibung und Beleg")}</summary>'
               f'<p class="labels">{metadata}</p>{description}{evidence}</details>'
               if detail_link else description + evidence)
    created = https_link(view.external_link)
    if view.can_remove:
        created_link = (f'<p class="card-links"><a class="button" '
                        f'href="/vorschlag/{e(view.mail_id)}/{e(view.proposal_id)}/entfernen">'
                        f'{tr("Eintrag wieder entfernen")}</a></p>')
    else:
        created_link = (f'<p><a href="{e(created)}" rel="noopener noreferrer" target="_blank">'
                        f'{tr("Im Kalender öffnen" if event else "Aufgabe öffnen")}</a></p>'
                        if created else "")
    # 4.7: the link is one of the percent-encoded forms validated on Proposal.mail_link.
    original = (f'<p class="card-links"><a href="{e(view.mail_link)}" rel="noopener noreferrer">'
                f"{tr('📧 Original-Mail öffnen')}</a></p>" if view.mail_link else "")
    created_link += original
    version = " · " + tr("Version {number}", number=view.version) if view.version > 1 else ""
    title = e(card.title)
    mobile_facts = " · ".join(value for value in (card.when, card.location) if value)
    if detail_link:
        title = f'<a href="/vorschlag/{e(view.mail_id)}/{e(view.proposal_id)}">{title}</a>'
    current = " current" if view.current else ""
    details = (f'<p class="card-links"><a class="button small" data-detail '
               f'href="/vorschlag/{e(view.mail_id)}/{e(view.proposal_id)}">{tr("Details")}</a></p>'
               if detail_link else "")
    return f"""<article class="card kind-{kind}{current}" id="v-{e(view.mail_id)}-{e(view.proposal_id)}">
<p class="kind"><span class="kind-label">{tr(KINDS[kind])}</span>{version}</p>
<div class="card-head"><h3>{title}</h3></div>
<p class="source">✉️ {e(view.sender)}<span class="source-subject"> · {e(view.subject)}</span>
<span class="mobile-card-facts">{e(mobile_facts)}</span></p>
<p class="labels">{" ".join(_card_labels(view, metadata=not detail_link))}</p>
<ul class="facts">{"".join(_card_facts(card))}</ul>
{_card_warning(view)}{_diff_box(view)}{_card_questions(_plain_questions(view))}{context}{created_link}{details}
{actions(view) if actions else conflict_boxes(view)}
</article>"""


def relevance_card(view: RelevanceView, actions: RelevanceActions | None = None,
                   detail_link: bool = True) -> str:
    details = (f'<p class="card-links"><a class="button small" data-detail href="/mail/{e(view.mail_id)}">'
               f'{tr("Details")}</a></p>' if detail_link else "")
    return f"""<article class="card" id="r-{e(view.mail_id)}">
<p class="kind">{tr("❔ Relevanz")}</p>
<h3>{e(view.subject)}</h3>
<p class="source">✉️ {e(view.sender)}</p>
<p>{tr("Ist diese Mail für dich relevant? Bis zur Antwort wartet die Mailanalyse.")}</p>
{details}
{actions(view) if actions else ""}
</article>"""


def _proposal_items(views: tuple[ProposalView, ...], actions: Actions | None) -> list[str]:
    """Cards in the given order; members of a series stay together in a folded group."""
    items = []
    groups: dict[tuple[str, str | None, str | None], list[ProposalView]] = {}
    for view in views:
        # Only series may collect non-adjacent members. Ordinary proposals keep their sort order.
        identity = (view.mail_id, view.series_key, None if view.series_key else view.proposal_id)
        groups.setdefault(identity, []).append(view)
    for (mail_id, key, _proposal_id), group in groups.items():
        cards = "".join(proposal_card(view, actions=actions) for view in group)
        if key is not None and len(group) > 1:
            title = e(group[0].base_title or group[0].card.title)
            # A running or finished action of a member must not hide in a closed group (4.4).
            opened = " open" if "data-command-result" in cards or "data-card-command-status" in cards else ""
            summary = tr("Serie: {title} ({count} Termine)", title=title, count=len(group))
            items.append(f'<details class="series-group"{opened}><summary>{summary}'
                         f'</summary><p><a class="button" href="/serie/{mail_id}/{key}">'
                         f'{tr("Serie bearbeiten und bestätigen")}</a></p>{cards}</details>')
        else:
            items.append(cards)
    return items


Section = tuple[str, tuple[RelevanceView, ...], tuple[ProposalView, ...]]


# Not a .notice: it is no result message. app.js moves it below the first card it explains, so the first
# decision stays in the upper 60 % of a phone window (6.2.8).
def swipe_hint(first_is_relevance: bool = False) -> str:
    text = tr("Nach rechts wischen: relevant · nach links: irrelevant"
              if first_is_relevance
              else "Nach rechts wischen: anlegen · nach links: verwerfen")
    return ('<div class="swipe-hint" data-swipe-hint hidden>'
            f'<span>{text}</span>'
            '<button class="button small" type="button" data-swipe-hint-close '
            f'aria-label="{tr("Hinweis schließen")}">×</button></div>')


SWIPE_HINT = swipe_hint(False)


def overview_page(overview: Overview, *, actions: Actions | None = None,
                  relevance_actions: RelevanceActions | None = None,
                  message: str | None = None, message_kind: str = "ok",
                  before: str = "", empty: str | None = None, after: str = "",
                  count: str | None = None, sections: list[Section] | None = None,
                  no_match: str | None = None) -> str:
    """*before* places filters below the heading; *empty* replaces the default empty state.

    6.0.6: *count* replaces the number in the heading ("4 von 12"); *sections* group the decisions
    under their own headings; *no_match* is shown when a search or filter leaves nothing.
    """
    count = count if count is not None else str(len(overview.open) + len(overview.relevance))
    parts = [
        page_head(
            tr("Offene Entscheidungen"),
            msg("Arbeitsbereich"),
            tr("Vorschläge prüfen, Rückfragen klären und Entscheidungen treffen."),
            count=f' <span class="count">{e(count)}</span>',
        ),
        before,
    ]
    if message:
        parts.append(notice(message, message_kind))
    if overview.damaged:
        parts.append(notice(tr("{count} gespeicherte Datensätze sind beschädigt und werden "
                               "nicht angezeigt. Bitte die Protokolle prüfen.", count=overview.damaged), "error"))
    items: list[str] = []
    if sections is not None:
        for title, people, views in sections:
            items.append(f'<h2>{e(stored(title))} <span class="count">{len(people) + len(views)}</span></h2>')
            items.extend(relevance_card(view, relevance_actions) for view in people)
            items.extend(_proposal_items(views, actions))
    else:
        if overview.relevance:
            items.append(f"<h2>{tr('Relevanz klären')}</h2>")
            items.extend(relevance_card(view, relevance_actions) for view in overview.relevance)
        if overview.open:
            items.append(f"<h2>{msg('Vorschläge')}</h2>")
            items.extend(_proposal_items(overview.open, actions))
    if items:
        # 6.3: app.js shows the swipe tip once on touch screens; without JavaScript there is no gesture.
        parts.append(swipe_hint(_first_is_relevance(overview, sections)))
        # On wide screens app.js turns this list into the master pane of a split view.
        parts.append('<div class="open-items">' + "\n".join(items) + "</div>")
    if not overview.open and not overview.relevance and no_match is not None:
        parts.append(no_match)
    elif not overview.open and not overview.relevance:
        parts.append(empty if empty is not None else
                     '<p class="empty">'
                     + tr("Nichts zu entscheiden. Neue Vorschläge erscheinen hier automatisch.") + '</p>')
    if overview.recent:
        items = []
        for view in overview.recent:
            items.append(
                f'<li><span><a href="/vorschlag/{e(view.mail_id)}/{e(view.proposal_id)}">'
                f'{e(view.card.title)}</a></span>'
                f'<span class="badge {_STATE_BADGE[view.status]}">{e(view.state)}</span></li>')
        parts.append(f'<h2>{tr("Zuletzt erledigt")}</h2><ul class="recent">{"".join(items)}</ul>')
    return layout(tr("Offen"), "\n".join(parts) + after, active="/", fingerprint=overview.fingerprint)


def _first_is_relevance(overview: Overview, sections: list[Section] | None) -> bool:
    if sections is None:
        return bool(overview.relevance)
    for _heading, people, views in sections:
        if people:
            return True
        if views:
            return False
    return False


VISION_LABELS = {
    "read": msg("Per Bilderkennung gelesen"),
    "no_text": msg("Bild ohne lesbaren Text"),
    "failed": msg("Bilderkennung fehlgeschlagen"),
    "skipped_small": msg("Übersprungen (Symbol oder Logo)"),
    "skipped_limit": msg("Übersprungen (Bildlimit je Mail)"),
    "skipped_oversized": msg("Übersprungen (Bild zu groß)"),
    "skipped_unreadable": msg("Bild nicht lesbar"),
}


def mail_section(mail: MailView | None, sender_actions: str = "") -> str:
    """The complete stored mail as text; links in it stay plain text."""
    if mail is None:
        return ""
    facts = [(msg("Von"), mail.sender), (msg("Betreff"), mail.subject)]
    if mail.mailbox:
        facts.append((msg("Postfach"), mail.mailbox))
    if mail.received:
        facts.append((msg("Datum"), mail.received))
    rows = "".join(f"<dt>{tr(label)}</dt><dd>{e(value)}</dd>" for label, value in facts)
    notes = []
    if mail.attachments_omitted:
        notes.append(tr("{count} Anhang/Anhänge nicht ausgewertet und nicht gespeichert.",
                        count=mail.attachments_omitted))
    if mail.text_shortened:
        notes.append(tr("Der Text wurde für die Auswertung gekürzt."))
    if mail.text is None:
        body = notice(tr("Der vollständige Mailtext ist nicht mehr gespeichert "
                         "(automatische Löschung nach Abschluss und Aufbewahrungsfrist)."), "info")
    else:
        body = f'<div class="mail-text">{e(mail.text)}</div>'
    hints = "".join(f'<p class="meta">{e(note)}</p>' for note in notes)
    att_section = ""
    if mail.extracted_attachments:
        status_labels = {
            "success": msg("Text extrahiert"),
            "no_text_found": msg("Kein Text gefunden"),
            "encrypted": msg("Verschlüsselt / Passwortgeschützt"),
            "skipped_oversized": msg("Übersprungen (zu groß)"),
            "error": msg("Fehler beim Lesen"),
            "unsupported_format": msg("Nicht unterstütztes Format"),
        }
        att_items = []
        for position, att in enumerate(mail.extracted_attachments):
            fn = att.filename
            st = att.extraction_status
            st_text = tr(status_labels[st]) if st in status_labels else st
            badge_class = "ok" if st == "success" else "warn"
            if att.vision is not None:
                st_text = tr(VISION_LABELS[att.vision]) if att.vision in VISION_LABELS else att.vision
                badge_class = "ok" if att.vision == "read" else "warn"
            original = mail.originals.get(position)
            download = (f' <a class="button small" href="/mail/{e(mail.mail_id)}/original/{position}" download>'
                        f'{tr("Original herunterladen")}</a> <span class="meta">{_size(original.size_bytes)}</span>'
                        if original is not None else "")
            att_items.append(
                f'<li>📎 <strong>{e(fn)}</strong> <span class="badge {badge_class}">{e(st_text)}</span>'
                f'{download}</li>'
            )
            preview = att.preview
            if preview is not None:
                url = '/mail/{p0}/anhang/{p1}'.format(p0=f'{e(mail.mail_id)}', p1=f'{preview.index}')
                size = f'{max(1, round(preview.size_bytes / 1024))} KB'
                if preview.width is not None:
                    size = f'{preview.width} × {preview.height} px · {size}'
                text = att.text
                shown = tr("Erkannten Text anzeigen")
                recognized = (f'<details><summary>{shown}</summary><pre>{e(text)}</pre></details>'
                              if text else f'<p class="meta">{tr("Kein erkannter Text gespeichert.")}</p>')
                att_items.append(f'<li class="image-preview"><a href="{url}" data-lightbox '
                                 f'aria-label="{e(tr("{name} vergrößern", name=fn))}">'
                                 f'<img src="{url}" alt="{e(fn)}" loading="lazy"></a>'
                                 f'<p class="meta">{e(fn)} · {size}</p>{recognized}</li>')
        heading = tr("Anhänge ({count}):", count=len(mail.extracted_attachments))
        att_section = (f'<div class="attachments"><p><strong>{heading}</strong></p>'
                       f'<ul>{"".join(att_items)}</ul></div>')
    cal_section = ""
    if mail.calendar_events:
        count = len(mail.calendar_events)
        cal_section = (f'<div class="notice info"><p>📅 <strong>'
                       f'{tr("{count} ICS-Kalenderanhang/-anhänge erkannt", count=count)}</strong></p></div>')
    return f"""<section class="card mail" id="mail" aria-labelledby="mail-titel">
<h2 id="mail-titel">{tr("Mail")}</h2>
<dl class="mail-head">{rows}</dl>
{sender_actions}{att_section}{cal_section}{body}{hints}
</section>"""


def _size(size: int) -> str:
    """A readable file size: KB below one megabyte, else MB with one decimal (German style)."""
    if size < 1_048_576:
        return f"{max(1, round(size / 1024))} KB"
    return f"{size / 1_048_576:.1f} MB".replace(".", ",")


def disclosure(summary: str, body: str, *, opened: bool = False, marker: str = "") -> str:
    """A secondary section, collapsed unless it is needed for the decision."""
    if not body:
        return ""
    return (f'<details class="disclosure"{marker}{" open" if opened else ""}><summary>{summary}</summary>'
            f'{body}</details>')


def source_summary(mail: MailView | None) -> str:
    """5.9.5: the collapsed source names its content, e.g. "(Mail von Schule, 2 Bilder)"."""
    title = tr("Quellbeleg aus E-Mail / Anhang")
    if mail is None:
        return title
    parts = [tr("Mail von {name}", name=sender_name(mail.sender))] if mail.sender.strip("— ") else []
    images = sum(1 for item in mail.extracted_attachments if item.preview is not None)
    if images:
        parts.append(tr("1 Bild") if images == 1 else tr("{count} Bilder", count=images))
    return f"{title} ({e(', '.join(parts))})" if parts else title


def detail_page(view: ProposalView, *, actions: Actions | None = None,
                mail: MailView | None = None, after: str = "") -> str:
    # 5.9.5: always collapsed from the server; app.js opens it from 1024 px (split view and
    # detail page). Without JavaScript and on small screens it stays collapsed.
    content = f"""<p><a href="/">← {tr("Zur Übersicht")}</a></p>
<h1>{tr("Termin" if view.card.kind == ProposalKind.EVENT else "Aufgabe")}</h1>
{proposal_card(view, actions=actions, detail_link=False)}
{disclosure(source_summary(mail), mail_section(mail), marker=" data-source-mail")}"""
    return layout(view.card.title, content, active="/", after=after)


def mail_page(mail: MailView, relevance: RelevanceView | None = None,
              actions: RelevanceActions | None = None, *, sender_actions: str = "",
              message: str | None = None, message_kind: str = "ok", after: str = "", recheck: str = "") -> str:
    """A mail on its own, with the relevance question if it is still open."""
    question = relevance_card(relevance, actions, detail_link=False) if relevance else ""
    result = notice(message, message_kind) if message else ""
    content = f"""<p><a href="/">← {tr("Zur Übersicht")}</a></p>
<h1>{tr("Mail")}</h1>
{result}{question}{recheck}
{mail_section(mail, sender_actions)}"""
    return layout(mail.subject, content, active="/", after=after)


# Compatibility for callers of the original renderer module (public names only;
# deprecated, removed in 3.0 – import from status_pages).
from .status_pages import ANALYSIS_LABELS, COMMAND_LABELS, RUN_LABELS, ServiceInfo, status_page

__all__ = ["ANALYSIS_LABELS", "COMMAND_LABELS", "RUN_LABELS", "ServiceInfo",
           "detail_page", "disclosure", "https_link", "mail_page", "mail_section",
           "overview_page", "proposal_card", "relevance_card", "status_page"]
