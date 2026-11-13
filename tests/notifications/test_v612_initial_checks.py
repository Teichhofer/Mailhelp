"""6.1.2: "Prüfen" in every step of the first setup; checking saves nothing and explains every problem."""
import pytest

from mailhelp.runtime.initial_checks import LIMIT, WINDOW, InitialChecks
from mailhelp.runtime.setup_messages import SetupProblem
from tests.fakes.initial_harness import initial  # noqa: F401  (fixture)
from tests.notifications.test_initial_setup import request

SECRET = "frisch-eingegeben-123"


def check(h, step, **values):
    return request(h, "POST", "/einrichtung/pruefen", h.form(step, **values))


def html(response):
    return response.body.decode()


def snapshot(h):
    env = h.directory / ".env"
    return h.setup.state(), env.read_text(encoding="utf-8") if env.exists() else "", (
        h.directory / "config.yaml").exists()


def test_regression_checking_saves_nothing_and_uses_the_entered_secret_only_for_the_check(initial):
    """Regression 6.1: "Verbindung jetzt prüfen" saved the entered credentials as soon as they worked."""
    h = initial
    h.advance()
    before = snapshot(h)
    seen = []
    h.checks.imap = lambda settings, env: seen.append(env["IMAP_PASSWORD"]) or {
        "folders": ["INBOX"], "inbox": "INBOX", "drafts": ""}
    response = check(h, 2, **{"IMAP_PASSWORD": SECRET, "imap.host": "imap.neu.test"})
    assert response.status == 200 and seen == [SECRET]
    assert snapshot(h) == before
    page = html(response)
    assert SECRET not in page and 'value="imap.neu.test"' in page  # entered values stay, secrets do not
    assert "Geprüft – alles in Ordnung" in page and "Das Postfach ist erreichbar und lesbar." in page


def test_every_step_has_a_check_button_and_step_five_checks_everything(initial):
    h = initial
    h.advance()
    for step in (1, 2, 3, 4):
        assert 'formaction="/einrichtung/pruefen" data-check>Prüfen</button>' in html(
            request(h, "GET", f"/einrichtung/schritt/{step}"))
    assert "Alles prüfen" in html(request(h, "GET", "/einrichtung/schritt/5"))
    overview = html(check(h, 5))
    assert overview.count("✓ Schritt") == 4 and "Zu Schritt 2" in overview
    h.checks.llm = lambda *args: (_ for _ in ()).throw(SetupProblem("llm.key_invalid"))
    failed = html(check(h, 5))
    assert "✗ Schritt 3: KI-Anbieter" in failed and "OpenRouter hat den Schlüssel nicht angenommen." in failed
    h.checks.targets = lambda *args: (_ for _ in ()).throw(RuntimeError(SECRET))
    assert SECRET not in html(check(h, 5)) and "Unerwarteter Fehler" in html(check(h, 5))


@pytest.mark.parametrize(("values", "message", "field"), [
    ({"timezone": "Europa/Berlin", "password": "lang-genug-12"}, "Die Zeitzone ist nicht bekannt.", "timezone"),
    ({"timezone": "Europe/Berlin", "password": "kurz"}, "Das Web-Passwort ist zu kurz.", "password"),
    ({"timezone": "Europe/Berlin", "password": "lang\tgenug-12345"}, "Tabulatoren", "password"),
])
def test_step_one_explains_time_zone_and_password(initial, values, message, field):
    page = html(check(initial, 1, **values))
    assert message in page and f'href="#feld-{field}"' in page
    assert f'id="feld-{field}" aria-invalid="true" aria-describedby="meldung-{field}"' in page


def test_step_one_without_password_keeps_the_saved_one_or_asks_for_one(initial):
    h = initial
    fresh = html(check(h, 1, timezone="Europe/Berlin", password="ein-langes-passwort"))
    assert "Zeitzone und Web-Passwort sind in Ordnung." in fresh and "<dd>Europe/Berlin</dd>" in fresh
    assert "Es ist noch kein Web-Passwort gespeichert." in html(check(h, 1, timezone="Europe/Berlin"))
    h.advance()
    page = html(check(h, 1, timezone="Europe/Berlin"))
    assert "Das gespeicherte Web-Passwort bleibt erhalten." in page and "Zeitzone und Web-Passwort" in page


def test_invalid_values_are_named_by_field_without_pydantic_text(initial):
    h = initial
    h.advance()
    page = html(check(h, 2, **{"imap.port": "abc"}))
    assert "Eine Eingabe hat ein ungültiges Format." in page and 'href="#feld-imap-port"' in page
    page = html(check(h, 2, **{"imap.connection_mode": "magie"}))
    assert 'id="feld-imap-connection-mode" aria-invalid="true"' in page and "literal_error" not in page


def test_problems_of_a_service_name_cause_field_and_remedy(initial):
    h = initial
    h.advance()
    h.checks.imap = lambda *args: (_ for _ in ()).throw(SetupProblem("imap.auth_failed"))
    page = html(check(h, 2))
    assert "Der Server hat die Anmeldung abgelehnt." in page and "App-Passwort" in page
    assert 'id="feld-imap-password" aria-invalid="true"' in page and 'role="alert"' in page
    h.checks.imap = lambda *args: (_ for _ in ()).throw(SetupProblem("imap.folder_missing", detail="INBOX, Archiv"))
    assert "(INBOX, Archiv)" in html(check(h, 2))
    h.checks.imap = lambda *args: {"folders": ["INBOX"], "inbox": "INBOX", "drafts": "", "drafts_missing": True,
                                   "server": "imap.example.test:993 (ssl)"}
    page = html(check(h, 2))
    assert "Geprüft – mit Hinweisen" in page and "Der Entwurfsordner wurde nicht gefunden." in page
    assert "<dt>Entwurfsordner</dt><dd>nicht erkannt</dd>" in page


def test_ai_and_target_facts_and_a_missing_ollama_model(initial):
    h = initial
    h.advance()
    h.checks.llm = lambda *args: {"models": ["openai/x"], "balance": 8.5, "key_remaining": 2.0}
    page = html(check(h, 3))
    assert "<dt>Guthaben</dt><dd>8,50 $</dd>" in page and "<dt>Restlimit des Schlüssels</dt><dd>2,00 $</dd>" in page
    h.checks.llm = lambda *args: {"models": ["openai/x"], "balance": None, "key_remaining": None}
    assert "Guthaben" not in html(check(h, 3))
    assert "<dt>Kalender</dt>" in html(check(h, 4)) or "Kalender und Aufgabenziel" in html(check(h, 4))
    h2 = h
    h2.setup.save(h2.actor, h2.form(3, **{"llm.provider": "ollama", "model": "fehlt:latest"}))
    h2.checks.llm = lambda *args: {"models": ["synthetic:latest"]}
    page = html(check(h2, 3, **{"llm.provider": "ollama", "model": "fehlt:latest"}))
    assert "Das gewählte Ollama-Modell ist nicht installiert." in page and "synthetic:latest" in page
    assert "Installierte Modelle" in html(check(h2, 3, **{"llm.provider": "ollama", "model": "synthetic:latest"}))


def test_ten_checks_per_minute_then_429_and_again_after_a_minute(initial):
    h = initial
    now = [100.0]
    checks = InitialChecks(h.setup, clock=lambda: now[0])
    for _ in range(LIMIT):
        assert checks.check(h.actor, h.form(1, timezone="UTC"))
    limited = checks.check(h.actor, h.form(1, timezone="UTC"))
    assert [item.code for item in limited.findings] == ["limit"]
    assert [item.code for item in checks.check_all(h.actor)[0].findings] == ["limit"]
    now[0] += WINDOW
    assert checks.check(h.actor, h.form(1, timezone="UTC")).findings[0].code != "limit"
    for _ in range(LIMIT + 1):
        response = check(h, 1, timezone="UTC")
    assert response.status == 429 and "Zu viele Prüfungen" in html(response)


def test_checks_need_a_session_csrf_and_a_reachable_step(initial):
    h = initial
    assert request(h, "POST", "/einrichtung/pruefen", h.form(1), token=False).status == 403
    assert request(h, "POST", "/einrichtung/pruefen", {**h.form(1), "csrf": "x"}).status == 403
    assert check(h, 3).status == 400  # step 2 is not saved yet
    assert request(h, "POST", "/einrichtung/pruefen", {**h.form(1), "step": "x"}).status == 400
    with pytest.raises(ValueError):
        InitialChecks(h.setup).check(h.actor, {"step": "7"})
    h.auth.revoke(h.session.id)
    with pytest.raises(PermissionError):
        InitialChecks(h.setup).check(h.actor, h.form(1))


def test_a_failed_save_explains_itself_on_the_same_step_with_the_values_kept(initial, monkeypatch):
    h = initial
    short = request(h, "POST", "/einrichtung/speichern", h.form(1, timezone="Europe/Vienna", password="kurz"))
    page = html(short)
    assert short.status == 409 and "Das Web-Passwort ist zu kurz." in page and 'value="Europe/Vienna"' in page
    h.advance()
    invalid = html(request(h, "POST", "/einrichtung/speichern", h.form(2, **{"imap.connection_mode": "magie"})))
    assert 'id="feld-imap-connection-mode" aria-invalid="true"' in invalid
    stale = html(request(h, "POST", "/einrichtung/speichern", {**h.form(2), "version": "0"}))
    assert "Die Einrichtung wurde inzwischen geändert." in stale
    monkeypatch.setattr(h.setup, "save", lambda *args: (_ for _ in ()).throw(RuntimeError(SECRET)))
    unknown = html(request(h, "POST", "/einrichtung/speichern", h.form(2)))
    assert "Unerwarteter Fehler" in unknown and SECRET not in unknown
    assert request(h, "POST", "/einrichtung/speichern", {**h.form(2), "step": "x"}).status == 409
    monkeypatch.setattr(h.setup, "save", lambda *args: (_ for _ in ()).throw(PermissionError()))
    assert request(h, "POST", "/einrichtung/speichern", h.form(2)).status == 403


def test_a_failed_start_shows_the_overview_of_all_steps(initial):
    h = initial
    h.advance()
    h.checks.imap = lambda *args: (_ for _ in ()).throw(SetupProblem("imap.unreachable"))
    response = request(h, "POST", "/einrichtung/speichern", h.form(5, confirm="yes"))
    page = html(response)
    assert response.status == 409 and "✗ Schritt 2: Postfach" in page and "Zu Schritt 2" in page
    assert not (h.directory / "config.yaml").exists()
    # A session that ends during the final check sees nothing of it.
    h.checks.llm = lambda *args: h.auth.revoke(h.session.id) or {"models": []}
    assert request(h, "POST", "/einrichtung/speichern", h.form(5, confirm="yes")).status == 403
