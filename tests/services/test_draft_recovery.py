"""An uncertain APPEND stays bound to its original folder across configuration changes."""
import pytest

from mailhelp.notifications.drafts import DraftService


class Imap:
    def __init__(self, available=True):
        self.available, self.selected, self.writes = available, [], []

    def select(self, folder, readonly):
        self.selected.append(folder)
        return ("OK" if self.available else "NO"), []

    def uid(self, *args):
        return "OK", [b"81" if self.selected[-1] == "Original" else b""]

    def list(self):
        return "OK", [b'(\\Drafts) "/" Fallback']

    def append(self, *args):
        self.writes.append(args)
        return "OK", []


def service():
    drafts = DraftService(None, lambda _: True, None, "me@example.test")
    drafts._save = lambda mail_id, draft: None
    return drafts


def append(drafts, server, draft):
    drafts._append(server, "Changed", "reviewer", "a" * 24, "save-0001", "digest", draft,
                   "<mailhelp-a-v1@draft.local>", b"synthetic message")


def test_uncertain_draft_is_reconciled_in_its_original_folder_after_a_folder_change():
    draft = {"status": "uncertain", "folder": "Original", "operations": {}}
    server = Imap()
    append(service(), server, draft)
    assert server.selected == ["Original"] and server.writes == []
    assert draft["status"] == "saved" and draft["folder"] == "Original"


def test_unavailable_original_folder_never_falls_back_after_an_uncertain_append():
    draft = {"status": "uncertain", "folder": "Original", "operations": {}}
    server = Imap(available=False)
    with pytest.raises(ValueError, match="Entwurfsordner"):
        append(service(), server, draft)
    assert server.selected == ["Original"] and server.writes == [] and draft["status"] == "uncertain"


def test_the_folder_is_durable_before_the_first_append():
    draft = {"status": "editing", "operations": {}}
    drafts, server, committed = service(), Imap(), []
    drafts._save = lambda mail_id, value: committed.append(dict(value))
    append(drafts, server, draft)
    assert committed[0]["folder"] == "Changed" and committed[0]["status"] == "uncertain"
    assert len(server.writes) == 1 and draft["status"] == "saved"
