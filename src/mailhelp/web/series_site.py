"""Accessible series editing and explicit confirmation, also without JavaScript."""
from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from ..models import Proposal
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
    def __init__(self, site: MailhelpSite):
        self.site = site
        site.app.route("GET", r"/serie/(?P<mail_id>[a-f0-9]{24})/(?P<key>[a-f0-9]{64})", site.signed_in(self.show))
        site.app.route("POST", r"/serie/(?P<token>[a-f0-9]{32})", site.signed_in(self.act))

    def show(self, request: Request, session: WebSession, mail_id: str, key: str) -> Response:
        from ..proposals.proposal_reconciliation import ProposalReconciliationService
        first = next((item for item in ProposalReconciliationService(self.site.views.store).current()
                      if item.source_mail_id == mail_id and item.series_key == key), None)
        if first is None:
            return Response.text(404, "Serie nicht vorhanden.")
        items = current_series(self.site.views.store, first)
        if not items or len(items) > 100:
            return Response.text(422, "Bitte einzelne Termine öffnen; keine bearbeitbare Serie.")
        return self.page(SeriesOffer(actor=f"web:{session.id}", items=items), session)

    def page(self, offer: SeriesOffer, session: WebSession, message: str = "") -> Response:
        token = create_offer(self.site.views.store, offer)
        rows = "".join(self._row(item, index) for index, item in enumerate(offer.items))
        ready = all(item.is_creatable and item.status == "pending_confirmation" and not item.open_questions
                    for item in offer.items)
        confirm = (f'<button class="button primary" name="action" value="confirm">'
                   f'Alle {len(offer.items)} Termine anlegen</button>' if ready else
                   '<p>Vor der Anlage müssen die offenen Fragen aller ausgewählten Termine geklärt sein.</p>')
        body = (f'<h1>Terminserie: {e(offer.items[0].base_title or offer.items[0].title)}</h1>'
                '<p>Jede Zeile zeigt die freizugebende Vorschlagsversion. Ausnahmen auswählen und '
                'die Auswahl aktualisieren. Jeder Termin kann auch einzeln bearbeitet werden.</p>'
                + (notice(message, "info") if message else "")
                + f'<form method="post" action="/serie/{token}" class="stack">'
                f'<input type="hidden" name="csrf" value="{e(self.site.auth.csrf_token(session.id))}">'
                f'<fieldset><legend>Angezeigte Termine ({len(offer.items)})</legend>{rows}</fieldset>'
                '<button class="button" name="action" value="select">Auswahl aktualisieren</button>'
                '<fieldset><legend>Gemeinsame Uhrzeit</legend>'
                '<label>Beginn <input name="start" type="time"></label>'
                '<label>Ende (optional; sonst Standarddauer) <input name="end" type="time"></label>'
                '<p>Speichern erstellt nur neue Versionen. Die Anlage muss danach separat bestätigt werden.</p>'
                '<button class="button" name="action" value="answer">Zeit für die Auswahl speichern</button>'
                f'</fieldset>{confirm}</form><p><a href="/">Zur Übersicht</a></p>')
        return Response.html(200, layout("Terminserie", body))

    def _row(self, item: Proposal, index: int) -> str:
        day = event_time(item, self.site.configured_timezone) or "Datum offen"
        return (f'<p><label><input type="checkbox" name="omit_{index}" value="yes"> Ausnehmen: '
                f'{e(item.title)} · {e(str(day))} · ID {e(item.id)}, Version {item.version}</label> '
                f'<a href="/vorschlag/{item.source_mail_id}/{item.id}">Einzeln bearbeiten</a></p>')

    def act(self, request: Request, session: WebSession, form: dict[str, str], token: str) -> Response:
        offer = self.site.views.store.load_model(f"series-offer-{token}", SeriesOffer)
        if offer is None or offer.actor != f"web:{session.id}":
            return Response.text(404, "Serienauswahl nicht vorhanden.")
        selected = [item for index, item in enumerate(offer.items) if form.get(f"omit_{index}") != "yes"]
        if not selected:
            return Response.text(422, "Mindestens einen Termin auswählen.")
        action = form.get("action")
        if action == "select" or action == "confirm" and len(selected) != len(offer.items):
            return self.page(offer.model_copy(update={"items": selected}), session,
                             "Auswahl aktualisiert. Diese Liste vor einer Anlage ausdrücklich bestätigen.")
        if action not in {"answer", "confirm"}:
            return Response.text(422, "Ungültige Serienaktion.")
        answer = form.get("start", "").strip()
        if form.get("end", "").strip():
            answer += " bis " + form["end"].strip()
        if action == "answer" and not form.get("start", "").strip():
            return Response.text(422, "Bitte eine Beginnzeit angeben.")
        try:
            command = offer_command(offer.model_copy(update={"items": selected}), token,
                CommandKind.SERIES_ANSWER if action == "answer" else CommandKind.SERIES_CONFIRM,
                CommandSource.WEB, answer if action == "answer" else None)
            entry, _ = self.site.commands.submit(command)
        except ValidationError:
            return Response.text(422, "Ungültige Zeitangabe.")
        except (CommandConflict, CommandInboxFull):
            return Response.text(409, "Auswahl bereits verwendet oder Warteschlange voll; Seite neu öffnen.")
        return Response.redirect(f"/aktion/{entry.id}")
