"""Legacy mailbox conversion and invalid topic references are checked before storage."""
import pytest

from mailhelp.configuration import apply_settings


def test_legacy_imap_converts_to_numbered_mailbox_without_inheriting_connection_fields(configured):
    cfg = configured.cfg
    raw = cfg.model_dump(mode="json")
    box = cfg.imap.mailbox(1).model_dump(mode="json")
    candidate = apply_settings(raw, {"imap.mailboxes": [box]}, True, setup=True)
    assert candidate["imap"]["mailboxes"][0]["id"] == 1
    assert "host" not in candidate["imap"] and "folders" not in candidate["imap"]


def test_topic_scope_rejects_unconfigured_mailbox_before_draft_save(profiled):
    from shared_profiles import TOPICS
    topic = {**TOPICS[0].model_dump(mode="json"), "mailboxes": [99]}
    actor = "web:" + profiled.web.auth.sessions()[0].id
    with pytest.raises(ValueError, match="Postfach"):
        profiled.runtime.setup.save_local(actor, 0, "invalid-0001", "topics", topic)
    assert profiled.runtime.setup.state().patch == {}
