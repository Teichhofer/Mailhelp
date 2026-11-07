"""4.5, step 16.2: forwarded mail is recognized; note and original are separated."""
import pytest

from mailhelp.domain.mail import ForwardedHeaders
from mailhelp.mailbox.imap import FetchedMail
from mailhelp.models import MailState
from mailhelp.processing.forwarding import split_forward
from mailhelp.storage import JsonStore
from tests.fakes.shared_profiles import ACCOUNT_ONE
from tests.fakes.shared_self_mail import orchestrator, own_settings

APPLE = """Bitte eintragen

Von meinem iPhone gesendet

Anfang der weitergeleiteten Nachricht:

> Von: Verein <info@verein.example.test>
> Datum: 3. November 2026 um 10:00:00 MEZ
> An: ich@private.example.test
> Betreff: Einladung Landesversammlung
>
> Liebe Mitglieder, die Landesversammlung beginnt am 5. Dezember um 9:30 Uhr."""

OUTLOOK = """Rückmeldung bis Freitag nötig.

-----Ursprüngliche Nachricht-----
**Von:** Schule <sekretariat@schule.example.test>
**Gesendet:** Montag, 2. November 2026 09:00
**An:** Eltern
**Cc:** Klassenleitung
**Betreff:** Rückmeldung Klassenfahrt

Bitte bis Freitag zurückmelden."""

GMAIL = """---------- Forwarded message ---------
From: Kita <kita@example.test>
Date: Mon, Nov 2, 2026 at 9:00 AM
Subject: Elternabend
To: <ich@private.example.test>


Elternabend am 12. November."""

THUNDERBIRD = """Zur Info

-------- Weitergeleitete Nachricht --------
Betreff:\tSitzung
Datum:\tTue, 3 Nov 2026 08:00:00 +0100
Von:\tGemeinde <rat@gemeinde.example.test>
An:\tich@private.example.test

Sitzung am 10.11."""


@pytest.mark.parametrize(("text", "note", "headers", "original"), [
    (APPLE, "Bitte eintragen\n\nVon meinem iPhone gesendet",
     ForwardedHeaders(sender="Verein <info@verein.example.test>", date="3. November 2026 um 10:00:00 MEZ",
                      recipients="ich@private.example.test", subject="Einladung Landesversammlung"),
     "> Liebe Mitglieder, die Landesversammlung beginnt am 5. Dezember um 9:30 Uhr."),
    (OUTLOOK, "Rückmeldung bis Freitag nötig.",
     ForwardedHeaders(sender="Schule <sekretariat@schule.example.test>", date="Montag, 2. November 2026 09:00",
                      recipients="Eltern", subject="Rückmeldung Klassenfahrt"),
     "Bitte bis Freitag zurückmelden."),
    (GMAIL, "", ForwardedHeaders(sender="Kita <kita@example.test>", date="Mon, Nov 2, 2026 at 9:00 AM",
                                 subject="Elternabend", recipients="<ich@private.example.test>"),
     "Elternabend am 12. November."),
    (THUNDERBIRD, "Zur Info", ForwardedHeaders(sender="Gemeinde <rat@gemeinde.example.test>",
                                               date="Tue, 3 Nov 2026 08:00:00 +0100", subject="Sitzung",
                                               recipients="ich@private.example.test"),
     "Sitzung am 10.11."),
])
def test_common_forwarding_formats_separate_note_headers_and_original(text, note, headers, original):
    forward = split_forward("WG: irgendwas", text)
    assert (forward.note, forward.headers, forward.original) == (note, headers, original)


def test_a_marker_without_header_lines_keeps_the_whole_original():
    forward = split_forward("Info", "Notiz\n-----Original Message-----\n\nHallo: das ist Text\nmehr")
    assert forward.headers is None and forward.note == "Notiz"
    assert forward.original == "Hallo: das ist Text\nmehr"
    assert split_forward("x", "Begin forwarded message:").original == ""


def test_a_forwarding_subject_without_marker_is_a_forwarding_without_original():
    for subject in ("WG: Termin", "Fwd: Termin", "fw:Termin", "[Verein] Fwd: Termin", "Weitergeleitet: Termin"):
        forward = split_forward(subject, "  Bitte eintragen  ")
        assert (forward.note, forward.headers, forward.original) == ("Bitte eintragen", None, "")
    assert split_forward("AW: Termin", "Antwort") is None
    assert split_forward("Re: Termin", None) is None
    assert split_forward("Wegweiser: Termin", "Text") is None


def test_header_values_are_cleaned_and_bounded():
    forward = split_forward("x", "-----Original Message-----\nFrom: " + "a\x07" * 400 + "\n\nText")
    assert forward.headers.sender == "a" * 400
    forward = split_forward("x", "-----Original Message-----\nSubject: " + "b" * 900)
    assert len(forward.headers.subject) == 500


def test_a_forwarded_self_note_keeps_only_the_note_as_the_users_words(tmp_path):
    cfg = own_settings(tmp_path)
    raw = ("From: ich@private.example.test\r\nSubject: WG: Einladung Landesversammlung\r\n"
           "Date: Sat, 07 Nov 2026 10:00:00 +0000\r\n\r\n" + APPLE.replace("\n", "\r\n")).encode()
    with JsonStore(tmp_path / "data") as store:
        state = MailState.model_validate(orchestrator(store, cfg).process(
            FetchedMail("INBOX", 1, 1, raw, account_id=ACCOUNT_ONE)).state)
    assert state.self_mail and state.is_forwarding
    assert state.user_note == "Bitte eintragen\n\nVon meinem iPhone gesendet"
    assert state.forwarded_headers.subject == "Einladung Landesversammlung"


def test_a_forwarding_by_someone_else_is_marked_without_a_user_note(tmp_path):
    cfg = own_settings(tmp_path)
    raw = ("From: partner@example.test\r\nSubject: Fwd: Elternabend\r\n"
           "Date: Sat, 07 Nov 2026 10:00:00 +0000\r\n\r\n" + GMAIL.replace("\n", "\r\n")).encode()
    with JsonStore(tmp_path / "data") as store:
        state = MailState.model_validate(orchestrator(store, cfg).process(
            FetchedMail("INBOX", 1, 1, raw, account_id=ACCOUNT_ONE)).state)
    assert state.is_forwarding and not state.self_mail and state.user_note is None
    assert state.forwarded_headers.sender == "Kita <kita@example.test>"
