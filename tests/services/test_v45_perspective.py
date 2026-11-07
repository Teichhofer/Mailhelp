"""4.5, steps 16.3/16.4: routing and extraction learn who wrote the mail."""
import yaml

from mailhelp.mailbox.imap import FetchedMail
from mailhelp.storage import JsonStore
from tests.fakes.shared_profiles import ACCOUNT_ONE
from tests.fakes.shared_self_mail import orchestrator, own_settings
from tests.fakes.shared_services import AnalyzerStub

NOTE = "Ich bin angemeldet und nehme teil.\r\n\r\nVon meinem iPhone gesendet"
FORWARD = ("Bitte eintragen\r\n\r\nAnfang der weitergeleiteten Nachricht:\r\n\r\n"
           "Von: Verein <info@verein.example.test>\r\nBetreff: Einladung\r\n\r\nAm 5.12. um 9:30 Uhr.")


class Recording(AnalyzerStub):
    def __init__(self):
        super().__init__("relevant")
        self.routed = []

    def action_route(self, m):
        self.routed.append(m)
        return super().action_route(m)


def route(tmp_path, sender, subject, text):
    raw = (f"From: {sender}\r\nSubject: {subject}\r\nDate: Sat, 07 Nov 2026 10:00:00 +0000\r\n\r\n{text}").encode()
    with JsonStore(tmp_path / "data") as store:
        run = orchestrator(store, own_settings(tmp_path))
        run.analyzer = analyzer = Recording()
        run.process(FetchedMail("INBOX", 1, 1, raw, account_id=ACCOUNT_ONE))
        stored = store.load(next(name for name in store.names("mail-") if not name.startswith("mail-run")))
    (mail,) = analyzer.routed
    return mail, stored


def test_a_self_note_reaches_the_router_with_its_perspective(tmp_path):
    mail, stored = route(tmp_path, "ich@private.example.test", "Landesversammlung", NOTE)
    assert mail["perspective"] == {"self_mail": True, "user_note": NOTE.replace("\r\n", "\n"),
                                   "is_forwarding": False, "forwarded_headers": None}
    assert "perspective" not in stored["mail"]  # Only the model input carries it.


def test_a_forwarded_self_note_names_the_original_headers(tmp_path):
    mail, _ = route(tmp_path, "ich@private.example.test", "WG: Einladung", FORWARD)
    assert mail["perspective"]["user_note"] == "Bitte eintragen"
    assert mail["perspective"]["forwarded_headers"] == {
        "sender": "Verein <info@verein.example.test>", "date": "", "subject": "Einladung", "recipients": ""}


def test_other_mail_reaches_the_router_unchanged(tmp_path):
    mail, stored = route(tmp_path, "Verein <info@verein.example.test>", "Einladung", "Am 5.12. um 9:30 Uhr.")
    assert "perspective" not in mail and mail == stored["mail"]


def test_the_router_prompt_reverses_the_perspective_for_self_notes():
    prompt = yaml.safe_load(open("prompts.yaml", encoding="utf-8"))["prompts"]["action_router"]["system_prompt"]
    for phrase in ('"perspective"', '"self_mail": true', "nie eine dritte Person", "„Ich nehme teil“",
                   '"event" mit event_count mindestens 1', "Anweisungen an dich als Modell"):
        assert phrase in prompt, phrase
