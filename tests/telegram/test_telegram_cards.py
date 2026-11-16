"""Telegram proposal cards: formatting, test mode and the confirmed write flow."""
from __future__ import annotations

import pytest

from mailhelp.app.composition import _state_directory
from mailhelp.config import Settings
from mailhelp.domain.mail import MailState
from mailhelp.persistence.storage import JsonStore
from mailhelp.proposals.integrations import CalendarFileWriter
from mailhelp.telegram import (
    Decision,
    DecisionAction,
    format_proposal,
    numbered_message_parts,
)
from tests.fakes.shared_telegram_dialog import (
    OperationallyFailingRevisionService as OperationallyFailingRevisionService,
)
from tests.fakes.shared_telegram_dialog import (
    Writer,
    callback,
    controller,
    proposal,
)


def test_numbered_parts():
    parts=numbered_message_parts("sender@example.test","Ein Betreff","x"*150,100)
    assert len(parts)>1 and all(
        part.startswith(f"✉️ sender@example.test · Ein Betreff · Teil {i}/{len(parts)}\n")
        for i,part in enumerate(parts,1))
    # A single part carries no counter; the display name replaces the address.
    assert numbered_message_parts("Ada <ada@example.test>", "Betreff", "Text") == [
        "✉️ Ada · Betreff\nText"]
    with pytest.raises(ValueError): numbered_message_parts("","p","x")
    with pytest.raises(ValueError): numbered_message_parts("m","","x")
    with pytest.raises(ValueError): numbered_message_parts("m","p","x",31)


@pytest.mark.parametrize(("item", "expected"), [
    (proposal(description="", due=None), "✅ Aufgabe: Aufgabe\nBeleg: „Beleg“"),
    (proposal(due="2026-05-10"), "✅ Aufgabe: Aufgabe\n🕒 Fällig: 10.05.2026\n📝 Text\nBeleg: „Beleg“"),
    (proposal(kind="event", start="2026-05-10T10:00:00+02:00", end="2026-05-10T11:00:00+02:00",
              location="Raum 1", video_link="https://video.example.test/abc"),
     "📅 Termin: Aufgabe\n🕒 10.05.2026, 10:00–11:00 Uhr\n📍 Raum 1\n"
     "🔗 https://video.example.test/abc\n📝 Text\nBeleg: „Beleg“"),
    (proposal(kind="event", start="2026-05-10T22:00:00+02:00", end="2026-05-11T01:00:00+02:00"),
     "📅 Termin: Aufgabe\n🕒 10.05.2026, 22:00 Uhr – 11.05.2026, 01:00 Uhr\n📝 Text\nBeleg: „Beleg“"),
    (proposal(kind="event", all_day=True, start="2026-05-10", end="2026-05-11", location=None),
     "📅 Termin: Aufgabe\n🕒 10.05.2026, ganztägig\n📝 Text\nBeleg: „Beleg“"),
    (proposal(kind="event", all_day=True, start="2026-05-10", end="2026-05-13"),
     "📅 Termin: Aufgabe\n🕒 10.05.2026 – 12.05.2026, ganztägig\n📝 Text\nBeleg: „Beleg“"),
])
def test_central_proposal_formatting_for_tasks_and_events(item, expected):
    # Compact card: empty fields, default values, target and version 1 are left out.
    assert format_proposal(item, "Europe/Berlin") == expected


def test_card_shows_deviations_shortens_long_texts_and_drops_provenance():
    description = "Lange Beschreibung " * 40 + "\n\nAbsender: a\nBetreff: b\nMail-Datum: c"
    item = proposal(version=3, responsibility="other", certainty="uncertain",
                    classification="non_binding", description=description,
                    evidence="Beleg " * 80, open_questions=[
                        "Ist die Nutzerin oder der Nutzer für diesen Eintrag zuständig?"])
    text = format_proposal(item, "Europe/Berlin")
    assert text.startswith("✅ Aufgabe (Version 3): Aufgabe\n")
    for line in ("Zuständig: Andere Person", "Sicherheit: Unsicher",
                 "Einordnung: Unverbindlicher Hinweis",
                 "⚠️ Kann nicht automatisch angelegt werden – bitte manuell prüfen.",
                 "❓ Offen:\n- Bist du dafür zuständig?"):
        assert line in text
    assert "Mail-Datum" not in text and "Absender:" not in text
    description_line = next(line for line in text.splitlines() if line.startswith("📝 "))
    evidence_line = next(line for line in text.splitlines() if line.startswith("Beleg: "))
    assert len(description_line) <= 2 + 300 and description_line.endswith("…")
    assert len(evidence_line) <= len("Beleg: „“") + 200 and evidence_line.endswith("…“")
    # A description that only repeats title or evidence adds nothing.
    assert "📝" not in format_proposal(proposal(description="Beleg"), "Europe/Berlin")
    assert "📝" not in format_proposal(proposal(description="Aufgabe"), "Europe/Berlin")


def test_test_mode_marks_task_simulation_before_confirmation(tmp_path):
    item = proposal()
    assert "🧪 Testmodus: Der Eintrag wird nur simuliert" in format_proposal(
        item, "Europe/Berlin", test_mode=True
    )
    with JsonStore(tmp_path) as store:
        dialog, transport, _ = controller(store, test_mode=True)
        dialog.send_proposal(item)
        assert transport.sent[-1][2]["inline_keyboard"][0][0]["text"] == "Simulieren"


def test_persist_before_buttons_and_authorized_flow(tmp_path):
    with JsonStore(tmp_path) as store:
        c,t,_=controller(store)
        p=proposal(title="t"*500, description="x"*4000)
        c.send_proposal(p)
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v1")["version"]==1
        assert all(message.startswith("✉️ — · —\n") for _, message, _ in t.sent)
        assert "Vorschlag p1" not in t.sent[-1][1] and "Ursprungsmail:" not in t.sent[-1][1]
        value=t.sent[-1][2]["inline_keyboard"][0][0]["callback_data"]
        # Long texts are shortened, so the card fits into one message.
        assert len(t.sent)==1 and value.startswith("decision:") and len(value.encode("utf-8")) <= 64
        assert Decision.parse(value, store) == Decision(mail_id="a"*24, proposal_id="p1", version=1, action=DecisionAction.CONFIRM)
        c.send(2,"ok")
        assert t.sent[-1][1] != "ok"  # held behind the undecided proposal
        with pytest.raises(PermissionError): c.send(3,"x")

        t.updates=[callback(4,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm")]
        c.poll_once()
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="confirmed"
        assert "bestätigt" in t.sent[-2][1] and t.removed == [(2, 1)]
        assert t.sent[-1][1] == "ok"
        # Duplicate update is ignored by the persisted offset after restart.
        c2,t2,_=controller(store,t.updates)
        c2.poll_once()
        assert t2.polls==[5] and not t2.answered
        # A replay with a fresh update id still cannot mutate the terminal state.
        t2.updates=[callback(5,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:reject")]
        c2.poll_once()
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="confirmed"
        assert "Schaltfläche ist veraltet" in t2.sent[-1][1]


def test_production_mode_creates_calendar_file_and_sends_it_via_telegram(tmp_path):
    item = proposal(kind="event", start="2026-05-10T10:00:00+02:00",
                    end="2026-05-10T11:00:00+02:00", title="Planung")
    with JsonStore(tmp_path) as store:
        dialog, transport, _ = controller(store, test_mode=False)
        dialog.writers["google_calendar"] = CalendarFileWriter(transport, 2)
        dialog.send_proposal(item)
        callback_data = transport.sent[-1][2]["inline_keyboard"][0][0]["callback_data"]
        transport.updates = [callback(1, callback_data)]

        dialog.poll_once()

        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"] == "created"
        assert len(transport.documents) == 1
        chat_id, filename, content, caption = transport.documents[0]
        assert chat_id == 2 and filename.endswith(".ics")
        assert content.startswith(b"BEGIN:VCALENDAR\r\n")
        assert b"SUMMARY:Planung\r\n" in content
        assert "Planung" in caption
        # One message reports the creation; no second confirmation follows.
        # 5.2: a delivered file is no proof of an import into the calendar.
        assert transport.sent[-1][1] == ("📎 Kalenderdatei für „Planung“ · 10.05.2026, 08:00 Uhr bereitgestellt – "
                                         "Übernahme in den Kalender nicht prüfbar.")
        (record,) = [store.load(name) for name in store.names("write-verification-")]
        assert record["state"] == "unsupported" and record["target"]["provider"] == "calendar_file"


def test_proposal_notification_uses_persisted_sender_and_subject(tmp_path):
    mail_id = "a" * 24
    with JsonStore(tmp_path) as store:
        state = MailState(
            id=mail_id, config_fingerprint="f" * 64,
            imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 1},
            display_headers={"sender": "Ada <ada@example.test>", "subject": "Besprechung"},
        )
        store.save("mail-" + mail_id, state.model_dump(mode="json"))
        dialog, transport, _ = controller(store)
        dialog.send_proposal(proposal(source_mail_id=mail_id))
        text = transport.sent[-1][1]
        assert text.startswith("✉️ Ada · Besprechung\n")
        assert mail_id not in text and "Vorschlag p1" not in text


def test_only_exactly_displayed_version_is_written(tmp_path):
    writer=Writer()
    with JsonStore(tmp_path) as store:
        c,t,_=controller(store, writers={"todoist":writer})
        c.send_proposal(proposal(version=1))
        c.send_proposal(proposal(version=2, title="Neue Fassung"))
        t.updates=[callback(1,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm"),callback(2,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:2:confirm")]
        c.poll_once()
        assert any("Schaltfläche ist veraltet" in text for _, text, _ in t.sent)
        assert writer.versions == [2]
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1-v2")["title"] == "Neue Fassung"


def test_deadline_clarification_blocks_every_external_request(tmp_path):
    writer=Writer()
    with JsonStore(tmp_path) as store:
        c,t,_=controller(store, writers={"todoist":writer})
        item=proposal(due="2026-10-01", status="needs_clarification",
                      open_questions=["Welcher Datumskontext soll verwendet werden?"])
        c.send_proposal(item)
        t.updates=[callback(1,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm")]
        c.poll_once()
        assert writer.reconciled == 0 and writer.created == 0
        assert store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"] == "needs_clarification"


def test_identical_proposals_have_isolated_confirmation_and_external_results(tmp_path):
    common=dict(timezone="UTC",poll_interval_seconds=5,data_directory=tmp_path/"state",
                imap={"host":"h","port":993,"folders":["INBOX"]},telegram={"user_id":1,"chat_id":2},
                targets={"todoist_project":"p","google_calendar":"c"},limits={"max_mail_bytes":1024,"llm_calls_per_minute":2},
                retries={"provider_retry":0,"json_repair":0,"schema_repair":0},timeouts={**{name:{"timeout_seconds":30,"retries":0,"initial_backoff_seconds":0,"max_backoff_seconds":1} for name in ("imap","telegram","openrouter","todoist","google_calendar")},"telegram_poll_seconds":30},
                logging={"directory":str(tmp_path/"logs"),"console":{"enabled":False},"file":{"filename":"application.jsonl","max_bytes":10000,"backup_count":1,"retention_days":30},"llm":{"filename":"llm/requests.jsonl","max_bytes":10000,"backup_count":1,"retention_days":30}})
    test_settings=Settings(test_mode=True,**common)
    production_settings=Settings(test_mode=False,**common)
    with JsonStore(_state_directory(test_settings,tmp_path)) as test_store:
        test_dialog,_,_=controller(test_store,[callback(1,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm")],{"todoist":Writer()},True)
        test_dialog.persist(proposal())
        test_dialog.poll_once()
        assert test_store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="simulated"
        assert test_store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1").get("external_id") is None
        assert test_store.load("telegram-offset")["offset"]==2

    writer=Writer()
    with JsonStore(_state_directory(production_settings,tmp_path)) as production_store:
        assert production_store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1") is None
        assert production_store.load("telegram-offset") is None
        production_dialog,_,_=controller(production_store,[callback(7,"proposal:aaaaaaaaaaaaaaaaaaaaaaaa:p1:1:confirm")],{"todoist":writer})
        production_dialog.persist(proposal())
        production_dialog.poll_once()
        assert production_store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["external_id"]=="external-1"
        assert production_store.load("telegram-offset")["offset"]==8
        assert writer.created==1

    with JsonStore(_state_directory(test_settings,tmp_path)) as test_store:
        assert test_store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1")["status"]=="simulated"
        assert test_store.load("proposal-aaaaaaaaaaaaaaaaaaaaaaaa-p1").get("external_id") is None
        assert test_store.load("telegram-offset")["offset"]==2
