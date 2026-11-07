"""Actor-bound series choices; the callback contains only an opaque token."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from ..models import Proposal, TelegramDialogState
from ..review.cards import event_time
from ..review.commands import CommandKind, CommandSource
from ..review.errors import StaleCommand
from ..review.results import ResultStatus, ReviewResult
from ..review.series_offers import SeriesOffer, create_offer, current_series, offer_command
from ..temporal_answers import parse_deterministic_temporal_answer
from .formatting import numbered_message_parts


def _actor(controller: Any) -> str:
    return f"telegram:{controller.user_id}:{controller.chat_id}"


def _present(controller: Any, offer: SeriesOffer, mode: str) -> None:
    material = json.dumps([offer.actor, mode, offer.answer, offer.endpoint,
                           [(item.id, item.version) for item in offer.items]], sort_keys=True)
    name = "series-presentation-" + hashlib.sha256(material.encode()).hexdigest()
    with controller.store.locked():
        if controller.store.load(name) is not None:
            return
        token = create_offer(controller.store, offer)
        controller.store.save(name, {"token": token})
    if mode == "answer":
        prompt = f"Für alle {len(offer.items)} offenen Termine dieser Serie übernehmen? Antwort: {offer.answer}"
        buttons = [{"text": "Alle", "callback_data": f"series:{token}:all"},
                   {"text": "Nur diesen", "callback_data": f"series:{token}:one"}]
    else:
        prompt = "Angezeigte Termine und Versionen prüfen. Erst diese Bestätigung autorisiert die Anlage."
        buttons = [{"text": f"Alle {len(offer.items)} Termine anlegen", "callback_data": f"series:{token}:confirm"}]
    rows = [f"{item.title} · {event_time(item, controller.configured_timezone)} · ID {item.id}, Version {item.version}"
            for item in offer.items]
    parts = numbered_message_parts("Mailhelp", "Terminserie", prompt + "\n\n" + "\n".join(rows))
    for part in parts[:-1]:
        controller.telegram.send(controller.chat_id, part)
    controller.telegram.send(controller.chat_id, parts[-1], {"inline_keyboard": [buttons]})


def offer_answer(controller: Any, pointer: TelegramDialogState | None, text: str) -> bool:
    if pointer is None or pointer.proposal_id is None or pointer.retry_required:
        return False
    proposal = controller.repository.load_current(pointer.mail_id, pointer.proposal_id)
    if proposal is None or proposal.version != pointer.version or proposal.kind != "event":
        return False
    question = proposal.open_questions[0] if proposal.open_questions else ""
    if not any(word in question.casefold() for word in ("beginn", "ende", "uhrzeit", "wann")):
        return False
    parsed = parse_deterministic_temporal_answer(text)
    if parsed is None or parsed.date is not None:
        return False
    items = current_series(controller.store, proposal)
    if len(items) < 2:
        return False
    # Keep the term actually answered first, for the explicit "Nur diesen" choice.
    items = [proposal, *[item for item in items if item.id != proposal.id]]
    _present(controller, SeriesOffer(actor=_actor(controller), items=items, answer=text,
                                    endpoint="end" if "ende" in question.casefold() else "start"), "answer")
    return True


def offer_confirmation(controller: Any, proposal: Proposal) -> None:
    if proposal.kind != "event":
        return
    items = current_series(controller.store, proposal)
    if len(items) < 2 or not all(item.is_creatable and item.status == "pending_confirmation" and not item.open_questions
                                for item in items):
        return
    _present(controller, SeriesOffer(actor=_actor(controller), items=items), "confirm")


def execute_callback(controller: Any, data: str) -> str:
    match = re.fullmatch(r"series:([a-f0-9]{32}):(all|one|confirm)", data)
    if match is None:
        raise ValueError("Ungültige Serienentscheidung")
    token, action = match.groups()
    offer = controller.store.load_model(f"series-offer-{token}", SeriesOffer)
    if offer is None or offer.actor != _actor(controller):
        raise StaleCommand("Serienauswahl nicht vorhanden oder nicht autorisiert")
    if action == "one":
        offer = offer.model_copy(update={"items": offer.items[:1]})
    kind = CommandKind.SERIES_CONFIRM if action == "confirm" else CommandKind.SERIES_ANSWER
    command = offer_command(offer, token, kind, CommandSource.TELEGRAM,
                            offer.answer if action != "confirm" else None)
    result: ReviewResult = controller.review.execute(command)
    if result.status == ResultStatus.DONE and action != "confirm":
        pointer = controller.store.load_model("telegram-dialog", TelegramDialogState)
        selected = {(command.mail_id, item.proposal_id, item.version) for item in command.members}
        if pointer is not None and (pointer.mail_id, pointer.proposal_id, pointer.version) in selected:
            controller.store.save("telegram-dialog", TelegramDialogState().model_dump(mode="json"))
        current = controller.repository.load_current(command.mail_id, command.proposal_id)
        if current is not None:
            offer_confirmation(controller, current)
    return result.message
