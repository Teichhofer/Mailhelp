"""Topic overview and lossless edits through the existing AdminCommand writer."""
import pytest
import yaml

from mailhelp.config import Topic
from mailhelp.configuration import file_hash
from tests.fakes.shared_web_actions import web as web
from tests.fakes.shared_web_auth import Browser
from tests.fakes.shared_web_v12 import configure


def catalog(topics):
    web, path = topics
    entries = [Topic(id="school", name="Schule", description="Erster Satz. Zweiter Satz.", enabled=True,
                     examples=["Rechnung; März"], mailboxes=[1, 52]),
               Topic(id="disabled", name="A deaktiviert", description="Lang " * 45, enabled=False),
               Topic(id="neu", name="Neues bestehendes Thema", description="Bestehend", enabled=True)]
    entries += [Topic(id=f"topic-{index}", name=f"Thema {index:02}", description="Beschreibung", enabled=True)
                for index in range(45)]
    entries[-1].mailboxes = []
    (path / "topics.yaml").write_text(yaml.safe_dump({"topics": [item.model_dump() for item in entries]}),
                                       encoding="utf-8")
    return web, path


@pytest.fixture
def topics(web, tmp_path):
    configure(web, tmp_path)
    return web, tmp_path


def fields(topics, **changes):
    web, path = topics
    return {"csrf": web.auth.csrf_token(web.auth.sessions()[0].id), "key": "topic-regression",
            "expected_hash": file_hash(path / "topics.yaml"), "category": "relevant",
            "original_id": "school", "id": "school", "name": "Schule", "description": "Präzise Schulregeln",
            "enabled": "true", "examples": "Beispiel", "exclusions": "", "confirm": "yes",
            "list_format": "lines", **changes}


def test_editing_a_topic_keeps_its_mailbox_scope_even_if_the_form_omits_it(topics):
    web, path = topics
    raw = yaml.safe_load((path / "topics.yaml").read_text(encoding="utf-8"))
    raw["topics"][0]["mailboxes"] = [1]
    (path / "topics.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert web.browser.request("POST", "/themen/speichern", fields(topics)).status == 303
    web.run()
    saved = yaml.safe_load((path / "topics.yaml").read_text(encoding="utf-8"))["topics"][0]
    assert saved["mailboxes"] == [1]


def test_a_semicolon_inside_a_newline_separated_example_is_not_a_separator(topics):
    web, path = topics
    form = fields(topics, examples="Treffen; verbindlich\nZweiter Fall", exclusions="Werbung; optional")
    assert web.browser.request("POST", "/themen/speichern", form).status == 303
    web.run()
    saved = yaml.safe_load((path / "topics.yaml").read_text(encoding="utf-8"))["topics"][0]
    assert saved["examples"] == ["Treffen; verbindlich", "Zweiter Fall"]
    assert saved["exclusions"] == ["Werbung; optional"]


def test_catalog_has_counts_links_and_status_without_editing_forms(topics):
    web, _path = catalog(topics)
    html = web.browser.request("GET", "/themen").body.decode()
    assert "Relevante Themen (48)" in html and "Ausschlussthemen (0)" in html
    assert html.count("data-topic-row ") == 48
    assert 'action="/themen/speichern"' not in html and 'name="description"' not in html
    assert html.index("A deaktiviert") > html.index("Thema 44")
    assert "Postfach 52" in html and "alle Postfächer" in html and "…" in html
    assert '/themen/relevant/neu?vorhanden=1' in html and "/static/topics.js" in html
    assert "Erster Satz." in html and "Zweiter Satz." not in html.split('data-label="Beschreibung">')[1].split("</td>")[0]


def test_server_side_search_and_filters_match_examples_without_script(topics):
    web, _path = catalog(topics)
    for query, expected in (("suche=Rechnung", 1), ("status=deaktiviert", 1), ("status=aktiv", 47),
                             ("suche=unbekannt", 0), ("art=ausschluss", 0)):
        html = web.browser.request("GET", "/themen?" + query).body.decode()
        assert f"{expected} von " in html
    assert "Negative Themen für Lern-" in web.browser.request("GET", "/themen?art=ausschluss").body.decode()
    for query in ("art=other", "status=other", "art=relevant&art=ausschluss"):
        assert web.browser.request("GET", "/themen?" + query).status == 400
    assert Browser(web.app).request("GET", "/themen").status == 303


def test_individual_links_and_reserved_new_id_are_operable(topics):
    web, _path = catalog(topics)
    for route in ("/themen/relevant/school", "/themen/relevant/neu?vorhanden=1", "/themen/ausschluss/neu"):
        response = web.browser.request("GET", route)
        # 5.7.2: the editor asks for a preview first; only the preview offers the confirmation.
        page = response.body.decode()
        assert response.status == 200 and 'action="/themen/pruefen"' in page and 'action="/themen/speichern"' not in page
    assert web.browser.request("GET", "/themen/relevant/missing").status == 404
    assert web.browser.request("GET", "/themen/relevant/school?x=1&x=2").status == 400
    assert Browser(web.app).request("GET", "/themen/relevant/school").status == 303


def test_pending_command_badge_is_a_read_only_projection(topics):
    web, _path = topics
    assert web.browser.request("POST", "/themen/speichern", fields(topics)).status == 303
    assert "Änderung ausstehend" in web.browser.request("GET", "/themen").body.decode()
    web.run()
    assert "Änderung ausstehend" not in web.browser.request("GET", "/themen").body.decode()


def test_missing_configuration_or_invalid_topic_documents_never_write(topics):
    web, path = topics
    service = web.site.archive.configuration
    web.site.archive.configuration = None
    assert web.browser.request("GET", "/themen").status == 503
    assert web.browser.request("GET", "/themen/relevant/school").status == 503
    web.site.archive.configuration = service
    (path / "topics.yaml").write_text("topics: [", encoding="utf-8")
    assert web.browser.request("GET", "/themen").status == 400
    assert web.browser.request("GET", "/themen/relevant/school").status == 400
    assert (path / "topics.yaml").read_text(encoding="utf-8") == "topics: ["


def test_legacy_semicolon_forms_remain_compatible(topics):
    web, path = topics
    form = fields(topics, examples="Alt; Zweites")
    del form["list_format"]
    assert web.browser.request("POST", "/themen/speichern", form).status == 303
    web.run()
    assert yaml.safe_load((path / "topics.yaml").read_text(encoding="utf-8"))["topics"][0]["examples"] == ["Alt", "Zweites"]


def test_legacy_forms_without_a_preview_keep_their_checks(topics):
    # 5.7.2: forms opened before the update still post directly; their checks stay unchanged.
    web, path = topics
    before = (path / "topics.yaml").read_text(encoding="utf-8")
    assert web.browser.request("POST", "/themen/speichern", fields(topics, id="other")).status == 422
    assert web.browser.request("POST", "/themen/speichern", fields(topics, expected_hash="0" * 64)).status == 409
    assert web.browser.request("POST", "/themen/speichern", fields(topics, enabled="vielleicht")).status == 422
    web.run()
    assert (path / "topics.yaml").read_text(encoding="utf-8") == before
