"""4.8, step 19.1: the drafts folder is found by SPECIAL-USE when the configured one is missing."""
import pytest

from mailhelp.mailbox.draft_folders import choose_drafts_folder, listed_folders
from mailhelp.mailbox.imap import ListedMailbox


def folder(name, role=None):
    return ListedMailbox(name, frozenset(), role)


@pytest.mark.parametrize(("configured", "listed", "chosen"), [
    ("Entwürfe", [folder("Entwürfe"), folder("Drafts", "drafts")], "Entwürfe"),        # configured wins
    ("Drafts", [folder("INBOX"), folder("Entwurf", "drafts")], "Entwurf"),              # WEB.DE: \Drafts
    ("Drafts", [folder("A", "drafts"), folder("B", "drafts"), folder("Entwürfe")], "Entwürfe"),  # ambiguous
    ("Drafts", [folder("INBOX"), folder("INBOX.Drafts")], "INBOX.Drafts"),             # common name
    ("Drafts", [folder("INBOX")], None),
])
def test_the_folder_is_configured_marked_or_commonly_named(configured, listed, chosen):
    assert choose_drafts_folder(configured, listed) == chosen


class Server:
    def __init__(self, status="OK", lines=()):
        self.status, self.lines = status, lines if lines is None else list(lines)

    def list(self):
        return self.status, self.lines


def test_the_list_answer_is_parsed_with_its_roles():
    listed = listed_folders(Server(lines=[b'(\\HasNoChildren \\Drafts) "/" "Entw&APw-rfe"',
                                          b'(\\Noselect) "/" "Archiv"', b'(\\HasNoChildren) "/" INBOX']))
    assert [(item.name, item.role) for item in listed] == [("Entwürfe", "drafts"), ("INBOX", None)]


def test_a_refused_list_is_reported():
    with pytest.raises(ValueError, match="Ordnerliste"):
        listed_folders(Server(status="NO"))
    assert listed_folders(Server(lines=None)) == []


class Connection:
    """A server without the configured "Drafts" folder but with a \\Drafts folder "Entwurf"."""

    def __init__(self, fallback="OK"):
        self.selected, self.fallback, self.appended = [], fallback, []

    def select(self, folder, readonly):
        self.selected.append(folder)
        return ("OK" if folder == "Entwurf" and self.fallback == "OK" else "NO"), []

    def list(self):
        return "OK", [b'(\\Drafts) "/" Entwurf', b"() \"/\" INBOX"]

    def uid(self, *args):
        return "OK", [b""]

    def append(self, folder, flags, date, content):
        self.appended.append(folder)
        return "OK", []


def test_a_draft_is_saved_in_the_marked_folder_and_the_folder_is_recorded(tmp_path):
    from mailhelp.notifications.drafts import DraftService
    service = DraftService(None, lambda actor: True, None, "ich@example.test")
    service._save = lambda mail_id, draft: None
    draft = {"operations": {}}
    connection = Connection()
    service._append(connection, "Drafts", "web:x", "a" * 24, "key-00001", "d", draft, "<id@draft.local>", b"x")
    assert connection.selected == ["Drafts", "Entwurf"] and connection.appended == ["Entwurf"]
    assert draft["status"] == "saved" and draft["folder"] == "Entwurf"


def test_without_a_usable_drafts_folder_nothing_is_written(tmp_path):
    from mailhelp.notifications.drafts import DraftService
    service = DraftService(None, lambda actor: True, None, "ich@example.test")
    for connection, configured in ((Connection(fallback="NO"), "Drafts"), (Connection(), "Entwurf")):
        if configured == "Entwurf":
            connection.fallback = "NO"  # the configured folder itself is refused: no other folder is tried
        with pytest.raises(ValueError, match="Entwurfsordner"):
            service._append(connection, configured, "web:x", "a" * 24, "key-00001", "d", {"operations": {}},
                            "<id@draft.local>", b"x")
        assert connection.appended == []
