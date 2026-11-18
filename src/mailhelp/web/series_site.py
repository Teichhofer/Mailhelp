"""Accessible series editing and explicit confirmation, also without JavaScript."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from ..domain.proposal import Proposal
from ..i18n import msg, tr
from ..proposals.proposal_reconciliation import ProposalReconciliationService
from ..review.cards import event_time
from ..review.commands import CommandKind, CommandSource
from ..review.inbox import CommandConflict, CommandInboxFull
from ..review.series_offers import SeriesOffer, create_offer, current_series, offer_command
from .auth import WebSession
from .http import Request, Response
from .pages import e, layout, notice

if TYPE_CHECKING:
    from .site import MailhelpSite


class SeriesSite:
    def __init__(self, site: MailhelpSite) -> None:
        self.site = site
        site.app.route("GET", r"/serie/(?P<mail_id>[a-f0-9]{24})/(?P<key>[a-f0-9]{64})", site.signed_in(self.show))
        site.app.route("POST", r"/serie/(?P<token>[a-f0-9]{32})", site.signed_in(self.act))

    def show(self, request: Request, session: WebSession, mail_id: str, key: str) -> Response:
        first = next((item for item in ProposalReconciliationService(self.site.views.store).current()
                      if item.source_mail_id == mail_id and item.series_key == key), None)
        if first is None:
            return Response.text(404, msg("Serie nicht vorhanden."))
        items = current_series(self.site.views.store, first)
        if not items or len(items) > 100:
            return Response.text(422, msg("Bitte einzelne Termine öffnen; keine bearbeitbare Serie."))
        return self.page(SeriesOffer(actor=f"web:{session.id}", items=items), session)

    def page(self, offer: SeriesOffer, session: WebSession, message: str = "") -> Response:
        token = create_offer(self.site.views.store, offer)
        rows = "".join(self._row(item, index) for index, item in enumerate(offer.items))
        ready = all(item.is_creatable and item.status == "pending_confirmation" and not item.open_questions
                    for item in offer.items)
        confirm = (
            tr(
                ('<button class="button primary" name="action" value="confirm">Alle {p0} Termine anlegen</button>'),
                p0=len(offer.items),
            )
            if ready
            else tr("<p>Vor der Anlage müssen die offenen Fragen aller ausgewählten Termine geklärt sein.</p>")
        )
        body = (
            tr(
                (
                    "<h1>Terminserie: {p0}</h1><p>Jede Zeile zeigt die freizugebende "
                    "Vorschlagsversion. Ausnahmen auswählen und die Auswahl "
                    "aktualisieren. Jeder Termin kann auch einzeln bearbeitet "
                    "werden.</p>"
                ),
                p0=e(offer.items[0].base_title or offer.items[0].title),
            )
            + (notice(message, "info") if message else "")
            + tr(
                (
                    '<form method="post" action="/serie/{p0}" class="stack"><input '
                    'type="hidden" name="csrf" '
                    'value="{p1}"><fieldset><legend>Angezeigte Termine '
                    '({p2})</legend>{p3}</fieldset><button class="button" '
                    'name="action" value="select">Auswahl '
                    "aktualisieren</button><fieldset><legend>Gemeinsame "
                    'Uhrzeit</legend><label>Beginn <input name="start" '
                    'type="time"></label><label>Ende (optional; sonst Standarddauer) '
                    '<input name="end" type="time"></label><p>Speichern erstellt nur '
                    "neue Versionen. Die Anlage muss danach separat bestätigt "
                    'werden.</p><button class="button" name="action" '
                    'value="answer">Zeit für die Auswahl '
                    'speichern</button></fieldset>{p4}</form><p><a href="/">Zur '
                    "Übersicht</a></p>"
                ),
                p0=token,
                p1=e(self.site.auth.csrf_token(session.id)),
                p2=len(offer.items),
                p3=rows,
                p4=confirm,
            )
        )
        return Response.html(200, layout(tr("Terminserie"), body))

    def _row(self, item: Proposal, index: int) -> str:
        day = event_time(item, self.site.configured_timezone) or msg("Datum offen")
        return tr(
            (
                '<p><label><input type="checkbox" name="omit_{p0}" value="yes"> '
                "Ausnehmen: {p1} · {p2} · ID {p3}, Version {p4}</label> <a "
                'href="/vorschlag/{p5}/{p6}">Einzeln bearbeiten</a></p>'
            ),
            p0=index,
            p1=e(item.title),
            p2=e(str(day)),
            p3=e(item.id),
            p4=item.version,
            p5=item.source_mail_id,
            p6=item.id,
        )

    def act(self, request: Request, session: WebSession, form: dict[str, str], token: str) -> Response:
        offer = self.site.views.store.load_model(f"series-offer-{token}", SeriesOffer)
        if offer is None or offer.actor != f"web:{session.id}":
            return Response.text(404, msg("Serienauswahl nicht vorhanden."))
        selected = [item for index, item in enumerate(offer.items) if form.get(f"omit_{index}") != "yes"]
        if not selected:
            return Response.text(422, msg("Mindestens einen Termin auswählen."))
        action = form.get("action")
        if action == "select" or action == "confirm" and len(selected) != len(offer.items):
            return self.page(
                offer.model_copy(update={"items": selected}),
                session,
                msg("Auswahl aktualisiert. Diese Liste vor einer Anlage ausdrücklich bestätigen."),
            )
        if action not in {"answer", "confirm"}:
            return Response.text(422, msg("Ungültige Serienaktion."))
        answer = form.get("start", "").strip()
        if form.get("end", "").strip():
            answer += msg(" bis ") + form["end"].strip()
        if action == "answer" and not form.get("start", "").strip():
            return Response.text(422, msg("Bitte eine Beginnzeit angeben."))
        try:
            command = offer_command(offer.model_copy(update={"items": selected}), token,
                CommandKind.SERIES_ANSWER if action == "answer" else CommandKind.SERIES_CONFIRM,
                CommandSource.WEB, answer if action == "answer" else None)
            entry, _ = self.site.commands.submit(command)
        except ValidationError:
            return Response.text(422, msg("Ungültige Zeitangabe."))
        except (CommandConflict, CommandInboxFull):
            return Response.text(409, msg("Auswahl bereits verwendet oder Warteschlange voll; Seite neu öffnen."))
        return Response.redirect(
            '/?aktion={p0}#v-{p1}-{p2}'.format(p0=f'{entry.id}', p1=f'{command.mail_id}', p2=f'{command.proposal_id}')
        )
