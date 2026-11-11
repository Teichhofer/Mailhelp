"""5.7.2 (S3): one page per topic, a preview before the explicit confirmation, field errors."""
import pytest
import yaml

from mailhelp.config import Topic
from mailhelp.storage import CorruptState
from mailhelp.web.topic_drafts import TopicDraft, draft_id, owner, proposed_id
from tests.fakes.shared_web_actions import web as web  # noqa: F401
from tests.fakes.shared_web_auth import Browser
from tests.fakes.shared_web_v12 import configure
from tests.fakes.topic_forms import confirmation, hidden, preview, save


@pytest.fixture
def topics(web, tmp_path):
    configure(web, tmp_path)
    entries = [Topic(id="school", name="Schule", description="Schulpost", enabled=True,
                     examples=["Elternabend; Klasse 3"], mailboxes=[1]),
               Topic(id="club", name="Verein", description="Vereinspost", enabled=True)]
    (tmp_path / "topics.yaml").write_text(yaml.safe_dump({"topics": [item.model_dump() for item in entries]}),
                                          encoding="utf-8")
    return web, tmp_path


def editor(web):
    return web.site.archive.settings.topic_site.editing


def actor(web):
    return "web:" + web.auth.sessions()[0].id


def saved(path, name="topics.yaml"):
    return yaml.safe_load((path / name).read_text(encoding="utf-8"))["topics"]


def test_the_editor_has_german_labels_help_a_switch_and_a_read_only_id(topics):
    web, _path = topics
    page = web.browser.request("GET", "/themen/relevant/school").body.decode()
    for label in ("Name", "Beschreibung", "Beispiele", "Ausschlüsse", "Aktiv"):
        assert f">{label}</label>" in page or f"> {label}</label>" in page
    assert "Ein typischer Betreff oder Satz je Zeile" in page and "Woran erkennt man das Thema?" in page
    assert 'type="checkbox" name="enabled" value="yes" checked' in page
    assert "Themen-ID: <code>school</code>" in page and 'id="topic-id"' not in page
    assert 'name="enabled" value="true"' not in page and ">id<" not in page
    # The examples are one per line; the semicolon stays inside the entry.
    assert ">Elternabend; Klasse 3</textarea>" in page
    assert "Geltungsbereich" in page and "Themen-YAML nur zum Lesen" in page
    assert 'action="/themen/pruefen"' in page and 'name="confirm"' not in page
    new = web.browser.request("GET", "/themen/ausschluss/neu").body.decode()
    assert "<h1>Neues Thema</h1>" in new and 'id="topic-id"' in new and "Aus dem Namen vorgeschlagen" in new


def test_preview_shows_before_and_after_and_only_confirmation_writes(topics):
    web, path = topics
    before = (path / "topics.yaml").read_text(encoding="utf-8")
    shown = preview(web, "/themen/relevant/school", name="Schule", description="Schulpost und Elternbriefe",
                    examples="Elternabend; Klasse 3\n\n  Zeugnis  ")
    page = shown.body.decode()
    assert "<h1>Änderung prüfen</h1>" in page and '<th scope="col">Bisher</th><th scope="col">Neu</th>' in page
    # 5.7.3: only changed fields are open, lists line by line; the rest is folded away.
    assert page.count('<span class="badge warn">geändert</span>') == 2  # description and examples
    assert "Geänderte Felder (2)" in page and "Unveränderte Felder anzeigen (4)" in page
    assert '<span class="diff-mark">+ neu:</span> Zeugnis' in page and "<li>Elternabend; Klasse 3</li>" in page
    assert 'name="confirm" value="yes" required' in page and "Weiter bearbeiten" in page
    web.run()
    assert (path / "topics.yaml").read_text(encoding="utf-8") == before, "Die Vorschau schreibt nichts"
    data = confirmation(shown)
    unconfirmed = {key: value for key, value in data.items() if key != "confirm"}
    assert web.browser.request("POST", "/themen/speichern", unconfirmed).status == 422
    assert web.browser.request("POST", "/themen/speichern", {**data, "expected_hash": "x"}).status == 422
    response = web.browser.request("POST", "/themen/speichern", data)
    assert response.status == 303 and response.headers["Location"].startswith("/aktion/")
    web.run()
    topic = saved(path)[0]
    assert topic["examples"] == ["Elternabend; Klasse 3", "Zeugnis"] and topic["mailboxes"] == [1]
    assert topic["description"] == "Schulpost und Elternbriefe"
    # Repeating the identical confirmation is the same action, never a second write.
    assert web.browser.request("POST", "/themen/speichern", data).headers["Location"] == response.headers["Location"]


def test_an_unchanged_topic_needs_no_confirmation(topics):
    web, path = topics
    shown = preview(web, "/themen/relevant/school", name="Schule", description="Schulpost",
                    examples="Elternabend; Klasse 3")
    assert "<h1>Keine Änderung</h1>" in shown.body.decode() and 'action="/themen/speichern"' not in shown.body.decode()
    state = editor(web).load(draft_id(actor(web), "relevant", "school"), actor(web))
    form = {"csrf": web.auth.csrf_token(web.auth.sessions()[0].id), "draft_id": draft_id(actor(web), "relevant", "school"),
            "draft_version": str(state.version), "key": state.key, "expected_hash": state.expected_hash, "confirm": "yes"}
    assert web.browser.request("POST", "/themen/speichern", form).status == 422


def test_a_new_topic_gets_an_id_from_its_name_and_ids_stay_unique(topics):
    web, path = topics
    assert proposed_id("Größere Ausflüge!") == "groessere-ausfluege" and proposed_id("!!!") == "thema"
    assert save(web, "/themen/relevant/neu", name="Größere Ausflüge", description="Ausflüge").status == 303
    web.run()
    assert saved(path)[-1]["id"] == "groessere-ausfluege" and "mailboxes" not in saved(path)[-1]
    taken = preview(web, "/themen/ausschluss/neu", id="club", name="Werbung", description="Werbung")
    assert taken.status == 422 and "Diese Themen-ID ist bereits vergeben." in taken.body.decode()
    assert 'aria-invalid="true"' in taken.body.decode()


def test_field_errors_keep_the_input_for_correction(topics):
    web, path = topics
    response = preview(web, "/themen/relevant/school", name="", description="Neu beschrieben")
    page = response.body.decode()
    assert response.status == 422 and 'role="alert">Name:' in page and ">Neu beschrieben</textarea>" in page
    response = preview(web, "/themen/relevant/school", id="other", name="Schule", description="Schulpost")
    assert response.status == 422 and "Die bestehende Themen-ID darf nicht geändert werden." in response.body.decode()
    response = preview(web, "/themen/relevant/school", name="Schule", description="Schulpost", enabled="ja")
    assert response.status == 422 and "Ungültiger Aktivierungswert." in response.body.decode()
    too_many = "\n".join(f"Beispiel {index}" for index in range(31))
    assert preview(web, "/themen/relevant/school", name="Schule", description="x", examples=too_many).status == 422
    # The last active relevant topic cannot be switched off; the error is shown at the switch.
    assert save(web, "/themen/relevant/club", name="Verein", description="Vereinspost", enabled="").status == 303
    web.run()
    response = preview(web, "/themen/relevant/school", name="Schule", description="Schulpost", enabled="")
    assert response.status == 422 and 'role="alert">Aktiv:' in response.body.decode()
    assert saved(path)[0]["enabled"] is True


def test_a_changed_file_is_a_conflict_with_a_reload_link(topics):
    web, path = topics
    shown = preview(web, "/themen/relevant/school", name="Schule", description="Geändert")
    form = hidden(web.browser.request("GET", "/themen/relevant/school").body.decode(), "/themen/pruefen")
    new_form = hidden(web.browser.request("GET", "/themen/relevant/neu").body.decode(), "/themen/pruefen")
    (path / "topics.yaml").write_text((path / "topics.yaml").read_text(encoding="utf-8") + "\n", encoding="utf-8")
    values = {"name": "Schule", "description": "Neu", "examples": "", "exclusions": "", "enabled": "yes"}
    response = web.browser.request("POST", "/themen/pruefen", {**form, **values})
    assert response.status == 409 and 'href="/themen/relevant/school">Neu laden' in response.body.decode()
    response = web.browser.request("POST", "/themen/pruefen", {**new_form, **values, "id": "neu-x"})
    assert response.status == 409 and 'href="/themen/relevant/neu">Neu laden' in response.body.decode()
    assert web.browser.request("POST", "/themen/speichern", confirmation(shown)).status == 409
    # A preview of an older revision is no longer offered as pending, and the editor shows the file.
    assert "Vorschau anzeigen" not in web.browser.request("GET", "/themen").body.decode()
    assert ">Schulpost</textarea>" in web.browser.request("GET", "/themen/relevant/school").body.decode()


def test_a_file_changed_during_validation_is_reported(topics, monkeypatch):
    web, _path = topics
    from mailhelp.configuration import ConfigurationConflict
    service = web.site.archive.configuration
    monkeypatch.setattr(service, "candidate", lambda command: (_ for _ in ()).throw(ConfigurationConflict("x")))
    response = preview(web, "/themen/relevant/school", name="Schule", description="Neu")
    assert response.status == 409 and "Datei während der Prüfung geändert" in response.body.decode()


def test_pending_previews_are_listed_until_their_command_is_queued(topics):
    web, path = topics
    shown = preview(web, "/themen/relevant/school", name="Schule", description="Entwurf")
    overview = web.browser.request("GET", "/themen").body.decode()
    identity = draft_id(actor(web), "relevant", "school")
    assert f'/themen/entwurf/{identity}">Schule: Vorschau anzeigen' in overview and "Änderung ausstehend" in overview
    resumed = web.browser.request("GET", f"/themen/entwurf/{identity}")
    assert resumed.status == 200 and "Geänderte Felder (2)" in resumed.body.decode()
    # Reopening the editor keeps the previewed values for further editing.
    assert ">Entwurf</textarea>" in web.browser.request("GET", "/themen/relevant/school").body.decode()
    assert web.browser.request("POST", "/themen/speichern", confirmation(shown)).status == 303
    assert "Vorschau anzeigen" not in web.browser.request("GET", "/themen").body.decode()
    web.run()
    assert saved(path)[0]["description"] == "Entwurf"


def test_the_same_key_returns_the_same_preview_and_a_reused_key_is_refused(topics):
    web, _path = topics
    form = hidden(web.browser.request("GET", "/themen/relevant/school").body.decode(), "/themen/pruefen")
    values = {**form, "name": "Schule", "description": "Erste", "examples": "", "exclusions": "", "enabled": "yes"}
    first = web.browser.request("POST", "/themen/pruefen", values)
    assert first.status == 200 and web.browser.request("POST", "/themen/pruefen", values).status == 200
    assert hidden(first.body.decode(), "/themen/speichern")["draft_version"] == "1"
    response = web.browser.request("POST", "/themen/pruefen", {**values, "description": "Zweite"})
    assert response.status == 409 and "Idempotenzschlüssel bereits anders verwendet." in response.body.decode()
    # An older editor tab (older draft version) cannot overwrite the newer preview.
    response = web.browser.request("POST", "/themen/pruefen", {**values, "key": "b" * 32, "description": "Alt"})
    assert response.status == 409 and "Ein neuerer Entwurf liegt vor." in response.body.decode()
    stale = confirmation(first)
    preview(web, "/themen/relevant/school", name="Schule", description="Dritte")
    assert web.browser.request("POST", "/themen/speichern", stale).status == 409


def test_previews_belong_to_the_session_and_expire(topics):
    web, _path = topics
    store = web.site.views.store
    foreign = draft_id("web:other", "relevant", "school")
    store.save("topic-draft-" + foreign, TopicDraft(version=1, owner=owner("web:other"), created_at=1).model_dump())
    assert web.browser.request("GET", f"/themen/entwurf/{foreign}").status == 403
    assert web.browser.request("POST", "/themen/speichern", {
        "csrf": web.auth.csrf_token(web.auth.sessions()[0].id), "draft_id": foreign, "draft_version": "1",
        "key": "k", "expected_hash": "", "confirm": "yes"}).status == 403
    with pytest.raises(PermissionError):
        editor(web).load("not-a-draft", actor(web))
    own = draft_id(actor(web), "relevant", "school")
    store.save("topic-draft-" + own, TopicDraft(version=1, owner=owner("web:other"), created_at=1).model_dump())
    assert web.browser.request("GET", "/themen/relevant/school").status == 403
    # A preview older than 24 hours is discarded; its version still counts up.
    preview(web, "/themen/ausschluss/neu", id="ads", name="Werbung", description="Werbung")
    identity = draft_id(actor(web), "ausschluss", "")
    editor(web).clock = lambda: 10 ** 12
    state = editor(web).load(identity, actor(web))
    assert state.topic is None and state.version == 2
    assert web.browser.request("GET", f"/themen/entwurf/{identity}").status == 422
    assert "Vorschau anzeigen" not in web.browser.request("GET", "/themen").body.decode()


def test_authorization_is_checked_again_before_saving_a_preview_and_a_command(topics, monkeypatch):
    web, path = topics
    shown = preview(web, "/themen/relevant/school", name="Schule", description="Neu")
    service = web.site.archive.configuration
    monkeypatch.setattr(service, "authorize", lambda _actor: False)
    assert preview(web, "/themen/relevant/school", name="Schule", description="Anders").status == 403
    assert web.browser.request("POST", "/themen/speichern", confirmation(shown)).status == 403
    assert Browser(web.app).request("GET", "/themen/relevant/school").status == 303
    assert Browser(web.app).request("POST", "/themen/pruefen", {}).status == 403
    calls = []
    monkeypatch.setattr(service, "authorize", lambda _actor: calls.append(1) or len(calls) < 2)
    assert web.browser.request("POST", "/themen/speichern", confirmation(shown)).status == 403
    assert len(web.commands.queued()) == 0
    web.run()
    assert saved(path)[0]["description"] == "Schulpost"


def test_damaged_forms_drafts_and_files_never_write(topics, monkeypatch):
    web, path = topics
    form = hidden(web.browser.request("GET", "/themen/relevant/school").body.decode(), "/themen/pruefen")
    values = {**form, "name": "Schule", "description": "Neu", "examples": "", "exclusions": "", "enabled": "yes"}
    assert web.browser.request("POST", "/themen/pruefen", {**values, "draft_version": "x"}).status == 422
    response = web.browser.request("POST", "/themen/pruefen", {**values, "kind": "other"})
    assert response.status == 422 and "Ungültiges oder veraltetes Formular." in response.body.decode()
    response = web.browser.request("POST", "/themen/pruefen", {**values, "original_id": "missing"})
    assert response.status == 404
    store = web.site.views.store
    original = store.save
    monkeypatch.setattr(store, "save", lambda *args: (_ for _ in ()).throw(OSError("voll")))
    response = web.browser.request("POST", "/themen/pruefen", values)
    assert response.status == 503 and "Entwurf nicht gespeichert" in response.body.decode()
    monkeypatch.setattr(store, "save", original)
    shown = preview(web, "/themen/relevant/school", name="Schule", description="Neu")
    data = confirmation(shown)
    assert web.browser.request("POST", "/themen/speichern", {**data, "draft_version": "x"}).status == 422
    assert web.browser.request("POST", "/themen/speichern", {**data, "draft_id": "x"}).status == 403
    from mailhelp.review.inbox import CommandConflict
    monkeypatch.setattr(web.site.commands, "existing", lambda command: (_ for _ in ()).throw(CommandConflict("x")))
    assert web.browser.request("POST", "/themen/speichern", data).status == 409
    monkeypatch.undo()
    load = store.load_model
    def broken(name, *args):
        if name.startswith("topic-draft-"):
            raise CorruptState("kaputt")
        return load(name, *args)
    monkeypatch.setattr(store, "load_model", broken)
    assert web.browser.request("POST", "/themen/speichern", data).status == 503
    assert web.browser.request("GET", f"/themen/entwurf/{data['draft_id']}").status == 503
    assert web.browser.request("GET", "/themen/relevant/school").status == 400
    assert "Vorschau anzeigen" not in web.browser.request("GET", "/themen").body.decode()
    response = web.browser.request("POST", "/themen/pruefen", {**values, "key": "c" * 32})
    assert response.status == 503
    monkeypatch.setattr(store, "load_model", load)
    (path / "topics.yaml").write_text("topics: [", encoding="utf-8")
    response = web.browser.request("POST", "/themen/pruefen", values)
    assert response.status == 503 and "Themendatei oder Ablage nicht lesbar" in response.body.decode()
    assert web.browser.request("POST", "/themen/speichern", data).status == 409
    assert (path / "topics.yaml").read_text(encoding="utf-8") == "topics: ["


def test_without_configuration_the_editor_is_unavailable(topics):
    web, _path = topics
    form = hidden(web.browser.request("GET", "/themen/relevant/school").body.decode(), "/themen/pruefen")
    web.site.archive.configuration = None
    assert web.browser.request("POST", "/themen/pruefen", form).status == 503
    assert web.browser.request("POST", "/themen/speichern", {**form, "draft_id": "x"}).status == 503
