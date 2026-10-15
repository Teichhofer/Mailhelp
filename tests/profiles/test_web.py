"""Authenticated draft routes with real sessions, CSRF, versions and command execution."""
import json
from types import SimpleNamespace as NS

import pytest
import yaml
from shared_profiles import ACCOUNT_ONE, ACCOUNT_TWO, TOPICS, settings
from shared_telegram_dialog import proposal
from shared_web_actions import MAIL1
from shared_web_auth import Browser

from mailhelp.config import Settings, Topic
from mailhelp.configuration import AdminCommand, AdminKind, ConfigurationConflict, file_hash
from mailhelp.models import MailState
from mailhelp.review.results import ResultStatus
from mailhelp.setup import SetupState
from mailhelp.web.mailbox_site import FIELDS, control, lookup


def discard(configured):
    web = configured.web
    form = web.form("/einstellungen/postfaecher", action="/einstellungen/postfaecher/verwerfen")
    assert web.browser.request("POST", "/einstellungen/postfaecher/verwerfen", form).status == 303


def apply(configured):
    runtime, web = configured.runtime, configured.web
    runtime.update_profile_checks()
    for name in runtime.diagnostics.checks:
        runtime.diagnostics.checks[name] = lambda _: ("ready", "")
        runtime.diagnostics.run(web.auth.sessions()[0].id, name, runtime.diagnostics.state().version, "probe-" + name.replace(":", "-"))
    form = web.form("/einstellungen/postfaecher", action="/einrichtung/uebernehmen")
    assert web.browser.request("POST", "/einrichtung/uebernehmen", {**form, "confirm": "yes"}).status == 303
    web.run()


def test_mailbox_tabs_and_inherited_controls_are_visible(profiled):
    web = profiled.web
    assert "Privat" in web.browser.request("GET", "/einstellungen/postfaecher").body.decode()
    for tab in (*FIELDS, "topics", "filters"):
        response = web.browser.request("GET", "/einstellungen/postfaecher/2?tab=" + tab)
        assert response.status == 200 and "Postfacheinstellungen" in response.body.decode()
    assert web.browser.request("GET", "/einstellungen/postfaecher/99").status == 404
    assert web.browser.request("GET", "/einstellungen/postfaecher/2?tab=unknown").status == 422
    assert lookup(None, "a") is None and lookup({}, "missing") is None
    assert 'selected' in control("notifications.categories.decisions", ["telegram"])


@pytest.mark.parametrize(("tab", "field", "value"), [
    ("replies", "personal_info", "Work signature"), ("replies", "smart_reply", "false"),
    ("replies", "activity_report_folder", "Projekte"), ("replies", "retention.full_mail_days", "disabled"),
    ("targets", "event_defaults.video_duration_minutes", "90"), ("targets", "target_profile", "1"),
    ("notifications", "daily_briefing", "false"), ("notifications", "notifications.categories.decisions", "[]"),
    ("notifications", "notifications.quiet_hours.enabled", "true")])
def test_overrides_save_repeat_and_reset_without_external_actions(profiled, tab, field, value):
    web, setup = profiled.web, profiled.runtime.setup
    path = "/einstellungen/postfaecher/2?tab=" + tab
    before = profiled.tmp_path.joinpath("config.yaml").read_bytes()
    form = web.form(path, action="/einstellungen/postfaecher/speichern", field=field)
    assert web.browser.request("POST", "/einstellungen/postfaecher/speichern", {**form, "value": value}).status == 303
    assert web.browser.request("POST", "/einstellungen/postfaecher/speichern", {**form, "value": value}).status == 303
    assert setup.state().version == 1 and profiled.tmp_path.joinpath("config.yaml").read_bytes() == before
    assert ("Erbt global" if field == "target_profile" else "Eigener Wert") in web.browser.request("GET", path).body.decode()
    reset = web.form(path, action="/einstellungen/postfaecher/speichern", field=field, index=1)
    assert web.browser.request("POST", "/einstellungen/postfaecher/speichern", reset).status == 303
    assert setup.state().version == 2
    discard(profiled)
    assert setup.state().patch == {} and web.writer.created == 0


def test_topic_scope_preview_counts_only_affected_running_mailbox(profiled):
    app, web = profiled.app, profiled.web
    from mailhelp.storage import mail_state_names
    for name in mail_state_names(app.store):
        existing = app.store.load_model(name, MailState)
        existing.steps.completion = "completed"
        app.store.save(name, existing.model_dump(mode="json"))
    for mid, account in (("a" * 24, ACCOUNT_ONE), ("b" * 24, ACCOUNT_TWO)):
        mail = MailState(id=mid, config_fingerprint=app.orchestrator.fingerprint_for(account),
            imap={"account_id": account, "folder": "INBOX", "uidvalidity": 1, "uid": 1})
        app.store.save("mail-" + mid, mail.model_dump(mode="json"))
    app.store.save("mail-run-" + ACCOUNT_ONE, {"schema_version": 1})
    form = web.form("/einstellungen/postfaecher/2?tab=topics", action="/einstellungen/postfaecher/thema", scope="exclude", category="relevant")
    assert web.browser.request("POST", "/einstellungen/postfaecher/thema", form).status == 303
    assert web.site.mailbox_page.affected() == {2: 1}
    assert "configuration_changed" in web.browser.request("GET", "/einstellungen/postfaecher").body.decode()
    apply(profiled)
    assert yaml.safe_load((profiled.tmp_path / "topics.yaml").read_text())["topics"][0]["mailboxes"] == [1]
    assert profiled.runtime.setup.state().kind == "settings"


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("field", ["google_calendar", "todoist_project"])
def test_target_draft_never_holds_current_or_upgraded_pending_mails(profiled, legacy, field):
    """Regression: preview must respect upgrade equivalence as well as target-free hashes."""
    from mailhelp.fingerprints import adopt_legacy_configuration, legacy_fingerprints, legacy_policies, topic_policy
    from mailhelp.storage import mail_state_names

    app, web, setup = profiled.app, profiled.web, profiled.runtime.setup
    cfg, prompts, run = app.settings, app.analyzer.prompts, app.orchestrator
    for name in mail_state_names(app.store):
        mail = app.store.load_model(name, MailState)
        mail.steps.completion = "completed"
        app.store.save(name, mail.model_dump(mode="json"))
    current = run.fingerprint_for(ACCOUNT_TWO)
    fingerprint = current
    if legacy:
        fingerprint = sorted(legacy_fingerprints(cfg, prompts, TOPICS))[0]
        adopt_legacy_configuration(app.store, current, {fingerprint}, topic_policy(cfg, prompts),
                                   legacy_policies(cfg, prompts), TOPICS)
    waiting = MailState(id="a" * 24, config_fingerprint=fingerprint,
        imap={"account_id": ACCOUNT_TWO, "folder": "INBOX", "uidvalidity": 1, "uid": 1})
    app.store.save("mail-" + waiting.id, waiting.model_dump(mode="json"))
    assert run.accepts_configuration(fingerprint, ACCOUNT_TWO)
    before = app.store.load("mail-" + waiting.id)
    actor = "web:" + web.auth.sessions()[0].id
    setup.save(actor, 0, "target-hash-0001", 6, {"targets." + field: "new-target"})
    assert web.site.mailbox_page.affected() == {}
    assert app.store.load("mail-" + waiting.id) == before and web.writer.created == 0
    # A genuine analysis change still appears for the same pending mail.
    setup.save(actor, 1, "analysis-hash-0001", 6, {"timezone": "America/New_York"})
    assert web.site.mailbox_page.affected() == {2: 1}


@pytest.mark.parametrize("scope", ["own", "all", "exclude"])
def test_topic_local_draft_discard_and_invalid_scope(profiled, scope):
    web = profiled.web
    form = web.form("/einstellungen/postfaecher/2?tab=topics", action="/einstellungen/postfaecher/thema", scope=scope)
    assert web.browser.request("POST", "/einstellungen/postfaecher/thema", {**form, "scope": "invalid"}).status == 409
    assert web.browser.request("POST", "/einstellungen/postfaecher/thema", {**form, "category": "invalid"}).status == 409
    assert web.browser.request("POST", "/einstellungen/postfaecher/thema", form).status == 303
    assert web.browser.request("POST", "/einstellungen/postfaecher/thema", form).status == 303
    discard(profiled)


def test_sender_draft_allows_global_exception_only_for_selected_mailbox(profiled):
    web = profiled.web
    form = web.form("/einstellungen/postfaecher/2?tab=filters", action="/einstellungen/postfaecher/filter")
    change = {**form, "value": "chief@example.test", "action": "allow"}
    assert web.browser.request("POST", "/einstellungen/postfaecher/filter", change).status == 303
    assert "chief@example.test" in web.browser.request("GET", "/einstellungen/postfaecher").body.decode()
    apply(profiled)
    assert profiled.app.configuration.blocked_senders().mailboxes["2"].allow == ["chief@example.test"]
    assert "Eigene Sperren" in web.browser.request("GET", "/einstellungen/postfaecher/2?tab=filters").body.decode()


def test_routes_require_session_csrf_current_version_and_local_execution_recheck(profiled):
    web = profiled.web
    form = web.form("/einstellungen/postfaecher/2?tab=replies", action="/einstellungen/postfaecher/speichern", field="personal_info")
    url = "/einstellungen/postfaecher/speichern"
    assert Browser(web.app).request("POST", url, {**form, "value": "x"}).status in {303, 401, 403}
    assert web.browser.request("POST", url, {**form, "csrf": "wrong", "value": "x"}).status == 403
    assert web.browser.request("POST", url, {**form, "version": "99", "value": "x"}).status == 409
    assert web.browser.request("POST", url, {**form, "field": "prompts", "value": "x"}).status == 409
    assert web.browser.request("POST", url, {**form, "value": "x"}).status == 303
    cfg = profiled.app.configuration
    state = profiled.runtime.setup.state()
    command = AdminCommand(kind=AdminKind.SETUP, actor="web:" + web.auth.sessions()[0].id,
        expected_hash=state.base_hash, idempotency_key="revoke-001", patch=state.patch, acknowledged=True)
    before = (profiled.tmp_path / "config.yaml").read_bytes()
    web.auth.revoke(web.auth.sessions()[0].id)
    assert cfg.execute(command).status == ResultStatus.UNAUTHORIZED
    assert (profiled.tmp_path / "config.yaml").read_bytes() == before


def test_profile_crud_guards_references_and_stable_ids(profiled):
    web = profiled.web
    page = web.browser.request("GET", "/einstellungen/zielprofile").body.decode()
    assert "Standardprofil 1" in page and "Postfach 2" in page
    form = web.form("/einstellungen/zielprofile", action="/einstellungen/zielprofile/speichern", number="2", field="label")
    assert web.browser.request("POST", "/einstellungen/zielprofile/speichern", {**form, "value": "Work"}).status == 303
    state = profiled.runtime.setup.state()
    assert state.patch["target_profiles"][0]["label"] == "Work"
    assert web.browser.request("POST", "/einstellungen/zielprofile/speichern", {**form, "version": str(state.version), "key": "remove-001", "action": "remove"}).status == 409
    assert web.browser.request("POST", "/einstellungen/zielprofile/speichern", {**form, "version": str(state.version), "key": "id-000001", "field": "id", "value": "3"}).status == 409
    discard(profiled)
    form = web.form("/einstellungen/zielprofile", action="/einstellungen/zielprofile/speichern", index=-1)
    values = dict(id="3", label="Weitere", calendar_provider="google", google_calendar="primary", task_provider="todoist", todoist_project="inbox")
    assert web.browser.request("POST", "/einstellungen/zielprofile/speichern", {**form, **values}).status == 303
    assert "Profil entfernen" in web.browser.request("GET", "/einstellungen/zielprofile").body.decode()
    remove = web.form("/einstellungen/zielprofile", action="/einstellungen/zielprofile/speichern", number="3", index=-1)
    assert web.browser.request("POST", "/einstellungen/zielprofile/speichern", remove).status == 303
