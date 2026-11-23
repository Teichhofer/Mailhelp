"""8.5: settings in section forms – several values reviewed and taken over together."""
import yaml

from mailhelp.web.settings_pages import NO_DEFAULT, SETTING_PREFIX, default_value
from tests.fakes.settings_sections import change_setting, review_fields, section_fields
from tests.fakes.shared_web_v12 import configure

SAVE = "/einstellungen/speichern"


def area(web, key):
    return web.browser.request("GET", f"/einstellungen?bereich={key}").body.decode()


def saved(tmp_path):
    return yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))


def test_two_values_of_a_section_are_reviewed_and_taken_over_in_one_step(web, tmp_path):
    service, _metrics, _lifecycle, active, _calls = configure(web, tmp_path)
    form = section_fields(area(web, "allgemein"), "poll_interval_seconds")
    form.update({SETTING_PREFIX + "poll_interval_seconds": "45", SETTING_PREFIX + "timezone": "Europe/Berlin"})
    review = web.browser.request("POST", SAVE, form)
    page = review.body.decode()
    assert review.status == 200 and "2 Änderungen werden gemeinsam übernommen" in page
    assert "Abrufintervall (Sekunden)" in page and "Zeitzone" in page and "nach Neustart" in page
    assert 'href="/einstellungen?bereich=allgemein">Abbrechen und zurück</a>' in page
    assert web.commands.queued() == []  # the review saves nothing
    confirmed = web.browser.request("POST", SAVE, review_fields(page))
    assert confirmed.status == 303 and len(web.commands.queued()) == 1
    web.run()
    file = saved(tmp_path)
    assert (file["poll_interval_seconds"], file["timezone"]) == (45, "Europe/Berlin")
    assert active[-1].poll_interval_seconds == 45


def test_a_single_change_and_an_unchanged_form(web, tmp_path):
    configure(web, tmp_path)
    form = section_fields(area(web, "allgemein"), "poll_interval_seconds")
    unchanged = web.browser.request("POST", SAVE, form)
    assert unchanged.status == 200 and "Keine Änderung" in unchanged.body.decode()
    assert 'href="/einstellungen?bereich=allgemein"' in unchanged.body.decode()
    lost = web.browser.request("POST", SAVE, {**form, "bereich": "unbekannt"})
    assert 'href="/einstellungen"' in lost.body.decode()
    review = web.browser.request("POST", SAVE, {**form, SETTING_PREFIX + "poll_interval_seconds": "40"})
    assert "1 Änderung wird übernommen" in review.body.decode()


def test_an_invalid_value_names_its_setting_and_saves_nothing(web, tmp_path):
    configure(web, tmp_path)
    before = saved(tmp_path)
    form = section_fields(area(web, "allgemein"), "timezone")
    refused = web.browser.request("POST", SAVE, {**form, SETTING_PREFIX + "timezone": "Bad/Zone",
                                                 SETTING_PREFIX + "poll_interval_seconds": "40"})
    page = refused.body.decode()
    assert refused.status == 422 and "Ungültiger Wert bei: Zeitzone" in page and "Abrufintervall" not in page
    assert saved(tmp_path) == before and web.commands.queued() == []


def test_values_valid_alone_but_not_together_are_all_named(web, tmp_path, monkeypatch):
    configure(web, tmp_path)
    configuration = web.site.archive.configuration
    original = configuration.candidate

    def together(command):
        if len(command.patch) > 1:
            raise ValueError("zusammen ungültig")
        return original(command)
    monkeypatch.setattr(configuration, "candidate", together)
    form = section_fields(area(web, "allgemein"), "timezone")
    refused = web.browser.request("POST", SAVE, {**form, SETTING_PREFIX + "timezone": "Europe/Berlin",
                                                 SETTING_PREFIX + "poll_interval_seconds": "40"})
    assert refused.status == 422 and "Abrufintervall (Sekunden), Zeitzone" in refused.body.decode()


def test_conflicts_unknown_settings_and_broken_forms_are_refused(web, tmp_path):
    configure(web, tmp_path)
    form = section_fields(area(web, "allgemein"), "timezone")
    stale = {**form, "expected_hash": "0" * 64, SETTING_PREFIX + "timezone": "Europe/Berlin"}
    assert web.browser.request("POST", SAVE, stale).status == 409
    assert web.browser.request("POST", SAVE, {**form, SETTING_PREFIX + "imap_password": "x"}).status == 422
    broken = {key: value for key, value in form.items() if key != "expected_hash"}
    assert web.browser.request("POST", SAVE, {**broken, SETTING_PREFIX + "timezone": "Europe/Berlin"}).status == 422
    web.site.archive.configuration = None
    assert web.browser.request("POST", SAVE, form).status == 503


def test_a_changed_value_can_be_reset_to_its_default(web, tmp_path):
    configure(web, tmp_path)
    path = tmp_path / "config.yaml"
    raw = saved(tmp_path)
    raw["retention"]["history_days"] = 7
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    page = area(web, "daten")
    default = default_value("retention.history_days")
    assert f"angepasst (Standard: {default})" in page
    assert 'name="zuruecksetzen" value="retention.history_days"' in page
    form = section_fields(page, "retention.history_days")
    review = web.browser.request("POST", SAVE, {**form, "zuruecksetzen": "retention.history_days"})
    assert "1 Änderung wird übernommen" in review.body.decode() and "unwiderruflich" in review.body.decode()
    assert web.browser.request("POST", SAVE, review_fields(review.body.decode())).status == 303
    web.run()
    assert saved(tmp_path)["retention"]["history_days"] == default
    assert web.browser.request("POST", SAVE, {**form, "zuruecksetzen": "timezone"}).status == 422
    assert web.browser.request("POST", SAVE, {**form, "zuruecksetzen": "gibt.es.nicht"}).status == 422


def test_a_text_reset_and_typed_values_never_report_an_unchanged_change(web, tmp_path):
    configure(web, tmp_path)
    path = tmp_path / "config.yaml"
    raw = saved(tmp_path)
    raw["targets"]["todoist_project"] = "2345"
    raw["language"] = "en"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    form = section_fields(area(web, "antworten"), "targets.todoist_project")
    unchanged = web.browser.request("POST", SAVE, form)  # "2345" stays text, an empty folder stays None
    assert "Keine Änderung" in unchanged.body.decode()
    general = section_fields(area(web, "allgemein"), "language")
    review = web.browser.request("POST", SAVE, {**general, "zuruecksetzen": "language"})
    assert 'name="setting:language" value="de"' in review.body.decode()


def test_taking_over_the_language_sets_the_language_cookie(web, tmp_path):
    configure(web, tmp_path)
    response = change_setting(web, "language", "en")
    assert response.status == 303 and any(item.startswith("mailhelp_lang=en") for item in response.cookies)


def test_the_former_areas_lead_to_their_new_place(web):
    for former, current in (("abruf", "allgemein"), ("briefing", "benachrichtigungen"), ("system", "erweitert")):
        answer = web.browser.request("GET", f"/einstellungen?bereich={former}")
        assert answer.status == 308 and answer.headers["Location"] == f"/einstellungen?bereich={current}"


def test_areas_have_a_phone_chooser_the_timeouts_table_and_technical_details(web, tmp_path):
    configure(web, tmp_path)
    page = area(web, "erweitert")
    assert '<form method="get" action="/einstellungen" class="settings-chooser">' in page
    assert '<option value="erweitert" selected>Erweitert</option>' in page
    assert '<table class="timeouts-table">' in page and 'aria-label="IMAP: Zeitlimit (s)"' in page
    assert page.count('data-settings-savebar') == 3
    general = area(web, "allgemein")
    assert "<summary>Technische Details</summary>" in general and "<code>timezone</code>" in general
    assert 'href="/hilfe?einstellung=timezone">Dazu fragen</a>' in general


def test_the_default_of_every_setting_is_found_or_marked_as_required():
    assert default_value("language") == "de" and default_value("timezone") is NO_DEFAULT
    assert default_value("limits.max_attachment_bytes") not in (None, NO_DEFAULT)
    assert default_value("gibt_es_nicht") is NO_DEFAULT
    assert default_value("language.nicht") is NO_DEFAULT  # below a plain value
    assert default_value("vision.enabled.nicht") is NO_DEFAULT


def test_the_default_walk_reads_values_below_a_plain_dictionary(monkeypatch):
    from pydantic import BaseModel

    from mailhelp.web import settings_pages

    class Model(BaseModel):
        table: dict = {"a": {"b": 2}}
    monkeypatch.setattr(settings_pages, "Settings", Model)
    assert default_value("table.a.b") == 2 and default_value("table.x") is NO_DEFAULT


def test_an_emptied_optional_value_is_no_change_and_search_rows_show_pending_values(web, tmp_path):
    configure(web, tmp_path)
    form = section_fields(area(web, "ki"), "metrics.exchange_rate_date")
    assert form[SETTING_PREFIX + "metrics.exchange_rate_date"] == ""  # not set
    assert "Keine Änderung" in web.browser.request("POST", SAVE, form).body.decode()
    raw = saved(tmp_path)
    raw["poll_interval_seconds"] = 33
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    page = web.browser.request("GET", "/einstellungen?suche=Abrufintervall").body.decode()
    assert "gespeichert – wird an der nächsten sicheren Stelle übernommen" in page
