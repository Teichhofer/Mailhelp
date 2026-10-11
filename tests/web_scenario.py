"""Synthetic Mailhelp state for the browser tests (no real mails, no real services)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mailhelp.domain.processing import TelegramOutboxEntry, TelegramOutboxGate, TelegramOutboxState
from mailhelp.models import (DisplayHeaders, MailRunCounters, MailRunEntry, MailRunState,
                             MailState, Proposal, RelevanceDialog)
from mailhelp.storage import JsonStore

ACCOUNT = "0" * 24
NOW = datetime(2026, 10, 11, 9, 30, tzinfo=timezone.utc)


def mail_id(number: int) -> str:
    return f"{number:024x}"


def proposal(number: int, pid: str, **fields) -> Proposal:
    data = {"id": pid, "version": 1, "kind": "task", "responsibility": "user",
            "certainty": "certain", "classification": "new", "title": "Aufgabe",
            "description": "", "evidence": "Beleg", "source_mail_id": mail_id(number),
            "target": "Inbox"}
    data.update(fields)
    if "status" not in data:
        data["status"] = ("needs_clarification" if data.get("open_questions")
                          or data["responsibility"] != "user" else "pending_confirmation")
    return Proposal.model_validate(data)


def save_mail(store: JsonStore, number: int, sender: str, subject: str, proposals=(),
              text: str | None = None, **fields) -> None:
    if text is not None:
        fields["mail"] = {"headers": {"from": sender, "subject": subject}, "text": text,
                          "date_header_parsed": (NOW - timedelta(hours=number)).isoformat(),
                          "metadata": {"attachments_omitted": 0, "text_shortened": False}}
    state = MailState(
        id=mail_id(number), config_fingerprint="f" * 64,
        imap={"account_id": ACCOUNT, "folder": "INBOX", "uidvalidity": 1, "uid": number},
        display_headers=DisplayHeaders(sender=sender, subject=subject),
        proposals=list(proposals), created_at=NOW - timedelta(days=1),
        updated_at=NOW + timedelta(minutes=number), **fields)
    store.save(f"mail-{mail_id(number)}", state.model_dump(mode="json"))
    for item in proposals:
        store.save(f"proposal-{item.source_mail_id}-{item.id}", item.model_dump(mode="json"))
        store.save(f"proposal-{item.source_mail_id}-{item.id}-v{item.version}",
                   item.model_dump(mode="json"))


def populate(store: JsonStore) -> None:
    """Open decisions of every kind, recent results, a relevance question and a run."""
    elternabend = proposal(
        1, "elternabend", kind="event", title="Elternabend Klasse 4b",
        start="2026-10-21T19:00:00+02:00", end="2026-10-21T20:30:00+02:00",
        location="Grundschule am Park, Raum 12", target="Familie",
        description="Themen: Klassenfahrt, Sportfest und die neue Hausaufgabenregel. "
                    "Bitte die unterschriebene Einverständniserklärung mitbringen.",
        evidence="Liebe Eltern, unser Elternabend findet am Dienstag, 21.10., um 19 Uhr in Raum 12 "
                 "statt. Wir besprechen die Klassenfahrt, das Sportfest und die neue Regel zu den "
                 "Hausaufgaben. Bitte bringen Sie die unterschriebene Einverständniserklärung mit.")
    formular = proposal(
        1, "formular", title="Einverständniserklärung Klassenfahrt zurückgeben",
        due="2026-10-17", evidence="Bitte die Erklärung bis Freitag, 17.10., zurückgeben.")
    zahnarzt = proposal(
        2, "zahnarzt", kind="event", title="Zahnarzt Kontrolle", target="Familie",
        open_questions=["Wann beginnt der Termin?"], known_temporal_facts={"date": "2026-10-23"},
        evidence="Ihr Kontrolltermin ist am 23.10. – die Uhrzeit teilen wir Ihnen noch mit.")
    hinweis = proposal(
        3, "fest", kind="event", title="Herbstfest des Fördervereins", target="Familie",
        responsibility="unclear",
        open_questions=["Ist die Nutzerin oder der Nutzer für diesen Eintrag zuständig?"],
        start="2026-10-25T14:00:00+02:00", end="2026-10-25T18:00:00+02:00",
        evidence="Der Förderverein lädt alle Familien zum Herbstfest am 25.10. von 14 bis 18 Uhr ein.")
    boese = proposal(
        4, "boese", title='Rechnung <script>alert("x")</script> prüfen',
        evidence='Zahlung über <a href="https://evil.test">diesen Link</a> javascript:alert(1)',
        description="Siehe https://evil.test/login?token=1")
    save_mail(store, 1, "Klassenleitung 4b <klasse4b@schule.test>", "Elternabend und Klassenfahrt",
              [elternabend, formular], text=(
                  "Liebe Eltern,\n\nunser Elternabend findet am Dienstag, 21.10., um 19 Uhr in "
                  "Raum 12 der Grundschule am Park statt. Wir besprechen die Klassenfahrt, das "
                  "Sportfest und die neue Regel zu den Hausaufgaben.\n\nBitte bringen Sie die "
                  "unterschriebene Einverständniserklärung mit oder geben Sie sie bis Freitag, "
                  "17.10., Ihrem Kind mit.\n\nMehr Infos: https://schule.test/elternabend\n\n"
                  "Viele Grüße\nKlassenleitung 4b"))
    save_mail(store, 2, "Praxis Dr. Weiß <praxis@zahn.test>", "Ihr Kontrolltermin", [zahnarzt])
    save_mail(store, 3, "Förderverein <info@foerderverein.test>", "Einladung zum Herbstfest", [hinweis])
    save_mail(store, 4, '"Buchhaltung" <rechnung@evil.test>', "Offene Rechnung <b>dringend</b>", [boese])
    angelegt = proposal(5, "turnen", kind="event", title="Kinderturnen", status="created",
                        start="2026-10-14T16:00:00+02:00", end="2026-10-14T17:00:00+02:00",
                        external_link="https://calendar.google.com/event?eid=1", target="Familie")
    verworfen = proposal(6, "werbung", title="Gutschein einlösen", status="rejected")
    save_mail(store, 5, "Turnverein <info@tv.test>", "Kinderturnen", [angelegt])
    save_mail(store, 6, "Shop <news@shop.test>", "Ihr Gutschein", [verworfen])
    save_mail(store, 7, "Sportverein <news@sv.test>", "Vereinsnachrichten Oktober",
              text="Hallo zusammen,\n\nim Oktober startet das Hallentraining. Unser Sommerfest war "
                   "ein voller Erfolg – danke an alle Helfer!\n\nEuer Vorstand",
              awaiting_relevance=True, relevance_dialog=RelevanceDialog(mail_id=mail_id(7)))
    store.save("telegram-outbox", TelegramOutboxState(active=TelegramOutboxGate(
        kind="proposal", mail_id=mail_id(1), proposal_id="elternabend", version=1),
        # Telegram shows one decision at a time; the Herbstfest is still held back.
        entries=[TelegramOutboxEntry(id="1" * 32, kind="proposal", mail_id=mail_id(3),
                                     proposal_id="fest", version=1, created_at=NOW)],
    ).model_dump(mode="json"))
    entries = [MailRunEntry(account_id=ACCOUNT, folder="INBOX", uidvalidity=1, uid=uid,
                            status=status, analysis_terminal=terminal,
                            user_action_open=status == "waiting_for_user")
               for uid, status, terminal in (
                   (1, "waiting_for_user", "completed"), (2, "waiting_for_user", "completed"),
                   (3, "waiting_for_user", "completed"), (4, "waiting_for_user", "completed"),
                   (5, "completed", "completed"), (6, "completed", "completed"),
                   (7, "processing", None), (8, "completed", "irrelevant"), (9, "queued", None))]
    counters = {status: sum(entry.status == status for entry in entries)
                for status in MailRunCounters.model_fields}
    store.save(f"mail-run-{ACCOUNT}", MailRunState(
        run_id="00000000-0000-0000-0000-000000000001", created_at=NOW, entries=entries,
        counters=MailRunCounters(**counters)).model_dump(mode="json"))


class Revisions:
    """Deterministic stand-in for the LLM revision of an answered question."""

    def interpret_telegram_answer(self, item, question, answer):
        return "interpret", type("I", (), {"usable": True, "normalized_answer": answer,
                                           "reason": "eindeutig"})()

    def clarify_telegram_answer(self, question, answer, reason, *, current_date=None):
        return "clarify", type("C", (), {"message": f"Bitte genauer: {question}"})()

    def revise_proposal(self, item, question, answer):
        remaining = item.open_questions[1:]
        data = {**item.model_dump(), "version": item.version + 1, "open_questions": remaining,
                "status": "needs_clarification" if remaining else "pending_confirmation",
                "responsibility": "user"}
        if item.kind.value == "event" and item.known_temporal_facts is not None:
            day = item.known_temporal_facts.date.isoformat()
            data.update(known_temporal_facts=None, start=f"{day}T10:00:00+02:00",
                        end=f"{day}T10:30:00+02:00")
        if not item.open_questions:
            data["title"] = answer.removeprefix("Titel:").strip() or item.title
        return "revision", Proposal.model_validate(data)


__all__ = ["Revisions", "mail_id", "populate", "proposal", "save_mail"]
