"""Mailhelp 2.0 in the browser: split view, shortcuts, undo, quick filters, lightbox, Web-Push."""
from __future__ import annotations

import base64
import re

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from PIL import Image
from playwright.sync_api import expect
from shared_vision import image_bytes
from shared_vision import mail as raw_mail
from web_scenario import mail_id

from checks import audit
from conftest import item, sign_in
from mailhelp.attachments import AttachmentCache
from mailhelp.models import MailState, Proposal
from mailhelp.webpush import PushService
from pages import MASTER, PANE, Overview, SettingsPage


def selected(page):
    return Overview(page).selected


def toast(page):
    return Overview(page).toast


def without_load_errors(page, *fragments):
    page.errors[:] = [error for error in page.errors if not any(part in error for part in fragments)]


def test_split_view_follows_the_keyboard_and_shows_help(page, mailhelp):
    if page.device != "desktop":
        return
    sign_in(page, mailhelp)
    # The first open item is selected at once; ids in the pane stay unique.
    expect(selected(page)).to_have_attribute("id", f"r-{mail_id(7)}")
    expect(page.locator(f"{PANE} #detail-r-{mail_id(7)}")).to_be_visible()
    assert page.locator(f"#r-{mail_id(7)}").count() == 1
    assert audit(page, "v20-split-desktop", False) == []
    page.keyboard.press("k")  # Stays on the first item.
    expect(selected(page)).to_have_attribute("id", f"r-{mail_id(7)}")
    page.keyboard.press("j")
    expect(selected(page)).to_have_attribute("id", f"v-{mail_id(1)}-elternabend")
    expect(page.locator(f"{PANE} #detail-v-{mail_id(1)}-elternabend")).to_be_visible()
    page.keyboard.press("ArrowDown")
    expect(selected(page)).to_have_attribute("id", f"v-{mail_id(1)}-formular")
    page.keyboard.press("ArrowUp")
    expect(selected(page)).to_have_attribute("id", f"v-{mail_id(1)}-elternabend")
    expect(page.locator(PANE)).not_to_have_attribute("aria-busy", "true")
    # Modifier keys and unknown keys are left to the browser.
    page.keyboard.press("Control+j")
    page.keyboard.press("z")
    expect(selected(page)).to_have_attribute("id", f"v-{mail_id(1)}-elternabend")
    # Enter on a summary keeps its native meaning and does not confirm.
    summary = page.locator(PANE).locator("summary").filter(has_text="Beleg vollständig anzeigen")
    summary.focus()
    page.keyboard.press("Enter")
    expect(page.locator(f"{PANE} details[open] .full")).to_be_visible()
    expect(toast(page)).to_be_hidden()
    # The help panel; keys do nothing while it is open.
    page.locator("body").focus()
    page.keyboard.press("?")
    help_panel = page.get_by_role("dialog", name="Tastenkürzel")
    expect(help_panel).to_contain_text("Bestätigen")
    assert audit(page, "v20-hilfe-desktop", False) == []
    page.keyboard.press("j")
    expect(selected(page)).to_have_attribute("id", f"v-{mail_id(1)}-elternabend")
    page.keyboard.press("Escape")
    expect(help_panel).to_have_count(0)
    page.keyboard.press("?")
    page.get_by_role("dialog", name="Tastenkürzel").get_by_role("button", name="Schließen").click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    # A relevance question cannot be confirmed or edited with a shortcut.
    page.keyboard.press("k")
    expect(selected(page)).to_have_attribute("id", f"r-{mail_id(7)}")
    expect(page.locator(f"{PANE} #detail-r-{mail_id(7)}")).to_be_visible()
    page.keyboard.press("c")
    expect(toast(page)).to_contain_text("nicht möglich")
    page.keyboard.press("e")
    expect(toast(page)).to_contain_text("nicht möglich")
    # E opens the edit form of the selected proposal.
    page.keyboard.press("j")
    page.keyboard.press("j")
    expect(page.locator(f"{PANE} #detail-v-{mail_id(1)}-formular")).to_be_visible()
    page.keyboard.press("e")
    page.wait_for_url(f"**/vorschlag/{mail_id(1)}/formular/bearbeiten")
    assert page.errors == []


def test_shortcut_confirm_can_be_undone_and_reject_is_sent_after_five_seconds(page, mailhelp):
    if page.device != "desktop":
        return
    # This dedicated test keeps the real five-second default; other tests use the test server's short delay.
    page.route("**/", lambda route: route.fulfill(response=route.fetch(),
               body=route.fetch().text().replace(' data-undo-ms="1000"', '')))
    sign_in(page, mailhelp)
    # The login ends with a redirect, which the route does not see: load the page itself.
    page.goto(f"{mailhelp.url}/")
    assert page.evaluate("document.body.dataset.undoMs") is None
    item(page, f"#v-{mail_id(1)}-elternabend")
    page.locator("body").focus()
    page.keyboard.press("c")
    expect(toast(page)).to_contain_text("„Elternabend Klasse 4b“ wird bestätigt.")
    expect(selected(page)).to_have_class(re.compile("leaving"))
    expect(page.locator(PANE)).to_have_attribute("inert", "")
    page.keyboard.press("j")  # No navigation while an action is pending.
    expect(selected(page)).to_have_attribute("id", f"v-{mail_id(1)}-elternabend")
    toast(page).get_by_role("button", name="Rückgängig").click()
    expect(toast(page)).to_have_text("Rückgängig gemacht – es wurde nichts gesendet.")
    expect(selected(page)).not_to_have_class(re.compile("leaving"))
    page.wait_for_timeout(5500)
    assert mailhelp.writer.created == [] and "/?ergebnis=" not in page.url
    page.locator("body").focus()
    with page.expect_event("framenavigated", timeout=20000,
                           predicate=lambda frame: "?ergebnis=" in frame.url):
        page.keyboard.press("x")
        # Still nothing sent after three seconds: the real default is five.
        page.wait_for_timeout(3000)
        assert "/?ergebnis=" not in page.url
    expect(Overview(page).notice).to_contain_text("Vorschlag verworfen.")
    expect(page.locator(f"#v-{mail_id(1)}-elternabend")).to_have_count(0)
    assert mailhelp.writer.created == [] and page.errors == []


def test_undo_on_phone_cards_and_the_thumb_zone(page, mailhelp):
    if page.device == "desktop":
        return
    sign_in(page, mailhelp)
    formular = page.locator(f"#v-{mail_id(1)}-formular")
    actions = formular.locator(".actions")
    # Reject left, confirm right: the main action lies in the natural thumb zone.
    first = page.locator(f"#v-{mail_id(1)}-elternabend .actions")
    assert first.evaluate("(node) => getComputedStyle(node).position") == "sticky"
    primary = first.get_by_role("button", name="Im Kalender anlegen").bounding_box()
    danger = first.get_by_role("button", name="Verwerfen").bounding_box()
    assert min(primary["height"], danger["height"]) >= 48
    assert (danger["y"], danger["x"]) < (primary["y"], primary["x"]) or danger["x"] < primary["x"]
    actions.get_by_role("button", name="Verwerfen").click()
    expect(toast(page)).to_contain_text("wird verworfen")
    expect(formular).to_have_class(re.compile("leaving"))
    # A second action waits until the first is sent or undone.
    page.locator(f"#v-{mail_id(1)}-elternabend").get_by_role("button", name="Im Kalender anlegen").click()
    expect(toast(page)).to_contain_text("„Einverständniserklärung Klassenfahrt zurückgeben“")
    page.get_by_role("link", name="Termine").click()
    expect(toast(page)).to_contain_text("Zuerst die laufende Aktion")
    page.keyboard.press("j")
    toast(page).click()  # Clicking the message itself does nothing.
    expect(toast(page)).to_contain_text("Zuerst die laufende Aktion")
    page.goto(page.url)
    assert mailhelp.writer.created == [] and page.errors == []


def test_quick_filter_chips_update_the_list_and_the_address(page, mailhelp):
    sign_in(page, mailhelp)
    page.get_by_role("link", name="Termine").click()
    page.wait_for_url("**/offen?filter=events")
    chip = page.get_by_role("link", name="Termine")
    expect(chip).to_have_attribute("aria-current", "true")
    expect(chip).to_be_focused()
    expect(page.locator(f"#v-{mail_id(1)}-formular")).to_have_count(0)
    expect(page.locator(f"#v-{mail_id(1)}-elternabend")).to_have_count(1)
    if page.device == "desktop":
        expect(selected(page)).to_have_attribute("id", f"v-{mail_id(1)}-elternabend")
    assert audit(page, f"v20-filter-{page.device}", page.mobile) == []
    page.get_by_role("link", name="Duplikate").click()
    page.wait_for_url("**/offen?filter=duplicates")
    expect(page.locator("article.card")).to_have_count(0)
    page.keyboard.press("j")  # Nothing to select.
    page.go_back()
    page.wait_for_url("**/offen?filter=events")
    expect(page.get_by_role("link", name="Termine")).to_have_attribute("aria-current", "true")
    page.goto(f"{mailhelp.url}/mails")
    page.get_by_role("link", name="Aufgaben").click()
    page.wait_for_url("**/mails?filter=tasks")
    expect(page.get_by_role("heading", name="Mails")).to_be_visible()
    page.route("**/verlauf?filter=*", lambda route: route.abort())
    page.goto(f"{mailhelp.url}/verlauf")
    page.get_by_role("link", name="Klärung nötig").click()
    expect(toast(page)).to_contain_text("Filter nicht geladen")
    without_load_errors(page, "ERR_FAILED")
    assert page.errors == []


def test_split_view_guards_typed_text_failures_and_viewport_changes(page, mailhelp):
    if page.device != "desktop":
        return
    page.set_viewport_size({"width": 900, "height": 900})
    sign_in(page, mailhelp)
    expect(page.locator(".split-view")).to_have_count(1)
    expect(selected(page)).to_have_count(0)
    page.set_viewport_size({"width": 1366, "height": 900})
    expect(selected(page)).to_have_attribute("id", f"r-{mail_id(7)}")
    page.set_viewport_size({"width": 1200, "height": 900})
    # Typed but unsent text is never discarded by selecting another item or filtering.
    dentist = item(page, f"#v-{mail_id(2)}-zahnarzt")
    dentist.get_by_label("Wann beginnt der Termin?").fill("10 Uhr")
    page.locator(f"{MASTER} #v-{mail_id(1)}-formular").click(position={"x": 12, "y": 12})
    expect(toast(page)).to_contain_text("Ungespeicherte Änderungen")
    page.get_by_role("link", name="Aufgaben").click()
    expect(toast(page)).to_contain_text("Zuerst die laufende Aktion oder Eingabe")
    dentist.get_by_label("Wann beginnt der Termin?").press("j")
    expect(selected(page)).to_have_attribute("id", f"v-{mail_id(2)}-zahnarzt")
    # Clicks into forms of the pane or on links that open new tabs are not selections.
    page.goto(f"{mailhelp.url}/")
    page.route(f"**/vorschlag/{mail_id(4)}/boese", lambda route: route.fulfill(status=500, body="Fehler"))
    page.locator(f"{MASTER} #v-{mail_id(4)}-boese").click(position={"x": 12, "y": 12})
    expect(toast(page)).to_contain_text("Details nicht geladen")
    page.locator(f"{MASTER} h2").first.click()
    without_load_errors(page, "500")
    assert page.errors == []


def test_image_preview_opens_in_a_zoomable_lightbox(page, mailhelp):
    raw = raw_mail(("aushang.png", "image", "png", image_bytes(Image.new("RGB", (900, 1200), "white"))))
    entries = [{"filename": "aushang.png", "vision": "read", "text": "Sommerfest am 12.07."}]
    AttachmentCache(mailhelp.store).prepare(mail_id(1), raw, entries)
    state = mailhelp.store.load_model(f"mail-{mail_id(1)}", MailState)
    state.mail["extracted_attachments"] = entries
    mailhelp.store.save(f"mail-{mail_id(1)}", state.model_dump(mode="json"))
    sign_in(page, mailhelp)
    if page.device == "desktop":
        item(page, f"#v-{mail_id(1)}-elternabend")
        scope = page.locator(PANE)
    else:
        page.goto(f"{mailhelp.url}/vorschlag/{mail_id(1)}/elternabend")
        scope = page
    link = scope.get_by_role("link", name="aushang.png vergrößern")
    expect(link.locator("img")).to_be_visible()
    expect(scope.get_by_text("aushang.png · 900 × 1200 px")).to_be_visible()
    scope.get_by_text("Erkannten Text anzeigen").click()
    expect(scope.get_by_text("Sommerfest am 12.07.")).to_be_visible()
    assert audit(page, f"v20-bild-{page.device}", page.mobile) == []
    link.click()
    dialog = page.get_by_role("dialog", name="Bildanhang vergrößert")
    image = dialog.locator("img")
    expect(image).to_be_visible()
    assert image.evaluate("(node) => node.complete && node.naturalWidth") == 900
    image.click()
    expect(image).to_have_class("zoomed")
    image.click()
    expect(image).not_to_have_class("zoomed")
    dialog.get_by_role("button", name="Schließen").click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(link).to_be_focused()
    assert page.errors == []


def decide_everything(store):
    for number, pid in ((1, "elternabend"), (1, "formular"), (2, "zahnarzt"), (3, "fest"), (4, "boese")):
        name = f"proposal-{mail_id(number)}-{pid}"
        store.save(name, {**store.load_model(name, Proposal).model_dump(mode="json"), "status": "rejected"})
    state = store.load_model(f"mail-{mail_id(7)}", MailState)
    state.awaiting_relevance, state.relevance_dialog = False, None
    store.save(f"mail-{mail_id(7)}", state.model_dump(mode="json"))


def test_inbox_zero_is_shown_when_everything_is_decided(page, mailhelp):
    decide_everything(mailhelp.store)
    sign_in(page, mailhelp)
    expect(page.get_by_role("heading", name="Alles erledigt! Keine offenen Entscheidungen.")).to_be_visible()
    expect(page.locator(".inbox-zero")).to_contain_text("Letzte verarbeitete Mail")
    assert page.locator(".split-view").count() == 0
    assert audit(page, f"v20-inbox-zero-{page.device}", page.mobile) == []
    assert page.errors == []


PUSH_STUB = """
window.__push = {permission: "granted", existing: null, subscribed: null, unsubscribed: 0, options: null};
const manager = {
  getSubscription: () => Promise.resolve(window.__push.existing),
  subscribe: (options) => { window.__push.options = options; return Promise.resolve(window.__push.subscribed); }
};
Object.defineProperty(navigator, "serviceWorker", {configurable: true, value: {
  register: () => Promise.resolve(null), ready: Promise.resolve({pushManager: manager})}});
Notification.requestPermission = () => Promise.resolve(window.__push.permission);
window.__subscription = (json) => ({toJSON: () => json,
  unsubscribe: () => { window.__push.unsubscribed += 1; return Promise.resolve(true); }});
"""


def subscription_json(endpoint="https://fcm.googleapis.com/fcm/send/synthetic"):
    key = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    encode = lambda value: base64.urlsafe_b64encode(value).decode().rstrip("=")
    return {"endpoint": endpoint, "keys": {"p256dh": encode(key), "auth": encode(b"a" * 16)}}


def test_web_push_opt_in_on_the_settings_page(page, mailhelp):
    if page.device != "desktop":
        return
    page.add_init_script(PUSH_STUB)
    sign_in(page, mailhelp)
    page.goto(f"{mailhelp.url}/einstellungen")
    status = page.locator("#push-status")
    enable = page.get_by_role("button", name="Push aktivieren")
    disable = page.get_by_role("button", name="Push deaktivieren")
    assert audit(page, "v20-push-einstellungen", False) == []
    page.evaluate("window.__push.permission = 'denied'")
    enable.click()
    expect(status).to_have_text("Benachrichtigungen wurden im Browser nicht erlaubt.")
    page.evaluate("window.__push.permission = 'granted'")
    enable.click()  # Web-Push is switched off in config.yaml.
    expect(status).to_have_text("Web-Push ist auf dem Server nicht eingeschaltet.")
    sent = []
    mailhelp.site.experience.push = PushService(mailhelp.store, mailhelp.auth, "mailto:ops@example.test",
                                                sender=lambda **kwargs: sent.append(kwargs))
    page.evaluate("(json) => { window.__push.subscribed = window.__subscription(json); }", subscription_json())
    enable.click()
    expect(status).to_have_text("Push ist auf diesem Gerät aktiviert.")
    assert page.evaluate("window.__push.options.applicationServerKey.length") == 65
    devices = mailhelp.store.load("push-subscriptions")["devices"]
    assert len(devices) == 1
    mailhelp.site.experience.push.notify()
    assert len(sent) == 1 and "Elternabend" not in sent[0]["data"]
    # An existing subscription of the browser is registered again, not replaced.
    page.evaluate("window.__push.existing = window.__push.subscribed; window.__push.subscribed = null")
    enable.click()
    expect(status).to_have_text("Push ist auf diesem Gerät aktiviert.")
    page.evaluate("(json) => { window.__push.existing = window.__subscription(json); }",
                  subscription_json("https://evil.example/push"))
    enable.click()
    expect(status).to_have_text("Nicht gespeichert. Bitte Anmeldung prüfen und erneut versuchen.")
    page.evaluate("(json) => { window.__push.existing = window.__subscription(json); }", subscription_json())
    disable.click()
    expect(status).to_have_text("Push ist auf diesem Gerät deaktiviert.")
    assert page.evaluate("window.__push.unsubscribed") == 1
    assert mailhelp.store.load("push-subscriptions")["devices"] == {}
    page.evaluate("window.__push.existing = null")
    disable.click()
    expect(status).to_have_text("Push ist auf diesem Gerät deaktiviert.")
    page.add_init_script("Object.defineProperty(window, 'isSecureContext', {value: false});")
    page.reload()
    page.get_by_role("button", name="Push aktivieren").click()
    expect(page.locator("#push-status")).to_contain_text("Push benötigt HTTPS")
    without_load_errors(page, "400", "503")
    assert page.errors == []


class Drafts:
    """A simulated IMAP connection that records APPEND commands."""

    def __init__(self):
        self.writes = []

    def select(self, folder, readonly):
        return "OK", []

    def uid(self, *args):
        return "OK", [b""]

    def append(self, *args):
        self.writes.append(args)
        return "OK", []


class Writer:
    """Simulated draft_reply step: one synthetic text per reply intent."""

    TEXTS = {"accept": "Vielen Dank, ich komme gerne zum Elternabend.",
             "decline": "Leider kann ich am Elternabend nicht teilnehmen.",
             "question": "Findet der Elternabend im Klassenzimmer statt?"}

    def __init__(self):
        self.calls = []

    def draft_reply(self, mail, intent, personal_info):
        from mailhelp.drafts import ReplyDraft
        self.calls.append(intent)
        return "call", ReplyDraft(text=self.TEXTS[intent])


def with_draft(mailhelp):
    from contextlib import nullcontext

    from mailhelp.drafts import DraftService
    imap = Drafts()
    state = mailhelp.store.load_model(f"mail-{mail_id(1)}", MailState)
    state.mail["headers"].update(message_id="<elternabend@schule.test>")
    mailhelp.store.save(f"mail-{mail_id(1)}", state.model_dump(mode="json"))
    imap.writer = Writer()
    mailhelp.site.experience.drafts = DraftService(mailhelp.store, mailhelp.auth.active, lambda: nullcontext(imap),
                                                   "ich@example.test", analyzer=imap.writer)
    return imap


def edit_and_save_draft(page, imap):
    reply = page.locator("#antwort")
    for label in ("Zusagen", "Absagen", "Rückfrage"):
        expect(reply.get_by_role("button", name=label)).to_be_visible()
    expect(page.get_by_label("Antworttext")).to_have_count(0)
    # Cancel discards a generated draft without touching the mailbox.
    reply.get_by_role("button", name="Absagen").click()
    expect(page.get_by_label("Antworttext")).to_have_value("Leider kann ich am Elternabend nicht teilnehmen.")
    page.get_by_role("button", name="Abbrechen").click()
    expect(page.get_by_label("Antworttext")).to_have_count(0)
    assert imap.writes == []
    page.locator("#antwort").get_by_role("button", name="Zusagen").click()
    expect(page.get_by_role("heading", name="Entwurf: Zusage")).to_be_visible()
    editor = page.get_by_label("Antworttext")
    expect(editor).to_have_value("Vielen Dank, ich komme gerne zum Elternabend.")
    editor.fill("Vielen Dank, wir kommen zu zweit.")
    page.get_by_role("button", name="Als Entwurf im Postfach speichern").click()
    expect(page.get_by_text("Im Postfach gespeichert.")).to_be_visible()
    assert imap.writer.calls == ["decline", "accept"]
    assert len(imap.writes) == 1 and b"wir kommen zu zweit" in imap.writes[0][3]
    assert b"In-Reply-To: <elternabend@schule.test>" in imap.writes[0][3]


def test_reply_draft_is_generated_edited_and_saved_to_the_mailbox(page, mailhelp):
    imap = with_draft(mailhelp)
    sign_in(page, mailhelp)
    page.goto(f"{mailhelp.url}/mail/{mail_id(1)}")
    assert audit(page, f"v20-entwurf-{page.device}", page.mobile) == []
    edit_and_save_draft(page, imap)
    assert audit(page, f"v20-entwurf-gespeichert-{page.device}", page.mobile) == []
    assert page.errors == []


def test_reply_buttons_announce_the_running_generation(page, mailhelp):
    """The model call takes a moment: the buttons lock and the status says so."""
    if page.device != "desktop":
        return
    with_draft(mailhelp)
    sign_in(page, mailhelp)
    page.goto(f"{mailhelp.url}/mail/{mail_id(1)}")
    page.route("**/entwurf", lambda route: route.abort("aborted"))
    reply = page.locator("#antwort")
    reply.get_by_role("button", name="Rückfrage").click()
    expect(reply.get_by_text("Entwurf wird erstellt …")).to_be_visible()
    expect(reply.get_by_role("button", name="Zusagen")).to_be_disabled()
    page.unroute("**/entwurf")
    assert page.errors == []


def test_every_2_0_function_works_without_javascript(browser, mailhelp):
    from conftest import DEVICES, Page
    imap = with_draft(mailhelp)
    context = browser.new_context(locale="de-DE", timezone_id="Europe/Berlin", java_script_enabled=False,
                                  **DEVICES["desktop"])
    page = Page(context.new_page(), "desktop")
    try:
        sign_in(page, mailhelp)
        expect(page.locator(".split-view")).to_have_count(0)
        page.get_by_role("link", name="Aufgaben").click()
        page.wait_for_url("**/offen?filter=tasks")
        expect(page.locator(f"#v-{mail_id(1)}-elternabend")).to_have_count(0)
        page.get_by_role("link", name="Alle").click()
        card = page.locator(f"#v-{mail_id(1)}-elternabend")
        card.get_by_role("button", name="Im Kalender anlegen").click()
        expect(Overview(page).notice).to_contain_text("Angelegt.", timeout=15000)
        assert mailhelp.writer.created == ["Elternabend Klasse 4b"]
        page.goto(f"{mailhelp.url}/vorschlag/{mail_id(1)}/formular")
        page.get_by_text("Technische LLM-Analyse & Metriken").click()
        expect(page.get_by_role("heading", name="Zusammenfassung")).to_be_visible()
        page.goto(f"{mailhelp.url}/mail/{mail_id(1)}")
        edit_and_save_draft(page, imap)
        page.goto(f"{mailhelp.url}/briefing")
        expect(page.get_by_text("Noch kein Tagesüberblick verfügbar.")).to_be_visible()
        assert page.errors == []
    finally:
        context.close()


def test_script_steps_that_end_in_a_navigation(page, mailhelp):
    """Each navigation is cancelled (ERR_ABORTED keeps the document), so the
    steps right before it can be checked and their script coverage collected."""
    if page.device != "desktop":
        return
    imap = with_draft(mailhelp)
    sign_in(page, mailhelp)
    # The undo time is over: the normal form is sent with locked buttons.
    page.route("**/aktion", lambda route: route.abort("aborted"))
    pane = item(page, f"#v-{mail_id(1)}-formular")
    pane.get_by_role("button", name="Verwerfen").click()
    expect(toast(page)).to_have_text("„Einverständniserklärung Klassenfahrt zurückgeben“ wird verworfen …",
                                     timeout=10000)
    expect(pane.get_by_role("button", name="Verwerfen")).to_be_disabled()
    page.unroute("**/aktion")
    # E follows the edit link of the selected proposal.
    page.goto(f"{mailhelp.url}/")
    page.route("**/bearbeiten", lambda route: route.abort("aborted"))
    item(page, f"#v-{mail_id(1)}-formular")
    page.locator("body").focus()
    with page.expect_request("**/formular/bearbeiten"):
        page.keyboard.press("e")
    # Back after a quick filter reloads the page for the address shown.
    page.goto(f"{mailhelp.url}/")
    page.get_by_role("link", name="Termine").click()
    page.wait_for_url("**/offen?filter=events")
    # A 204 keeps the document alive until the popstate callback has returned.
    # Collecting only at navigation start can miss that callback on Windows.
    page.route(f"{mailhelp.url}/", lambda route: route.fulfill(status=204))
    with page.expect_response(f"{mailhelp.url}/") as back:
        page.go_back()
    assert back.value.status == 204 and page.url == f"{mailhelp.url}/"
    page.collect()
    page.unroute(f"{mailhelp.url}/")
    # A filter answered with an error status (e.g. an expired session) is reported.
    page.goto(f"{mailhelp.url}/")
    page.route("**/offen?filter=tasks", lambda route: route.fulfill(status=503, body="weg"))
    page.get_by_role("link", name="Aufgaben").click()
    expect(toast(page)).to_contain_text("Filter nicht geladen")
    # The pressed button of a form with two actions is sent although buttons are locked.
    mailhelp.site.experience.drafts.generate(mailhelp.auth.sessions()[0].id, mail_id(1), 0, "gen-0001", "accept")
    page.goto(f"{mailhelp.url}/mail/{mail_id(1)}")
    page.route("**/entwurf", lambda route: route.abort("aborted"))
    with page.expect_request("**/entwurf") as sent:
        page.get_by_role("button", name="Abbrechen").click()
    assert "mode=cancel" in sent.value.post_data
    assert page.locator('form:has(#draft-editor) input[type="hidden"][name="mode"]').get_attribute("value") == "cancel"
    expect(page.get_by_role("button", name="Abbrechen")).to_be_disabled()
    assert imap.writes == []
    without_load_errors(page, "503", "ERR_ABORTED")
    assert page.errors == []


def test_personal_information_is_saved_with_line_breaks(page, mailhelp):
    """The text area keeps line breaks through the confirmation step into config.yaml."""
    sign_in(page, mailhelp)
    settings = SettingsPage(page, mailhelp.url).open()
    setting = settings.expand("Persönliche Angaben für Antworten")
    assert audit(page, f"v20-persoenlich-{page.device}", page.mobile) == []
    settings.propose(setting, "Max Mustermann\nElternbeirat Klasse 4b")
    expect(page.locator("main pre")).to_have_text("Max Mustermann\nElternbeirat Klasse 4b")
    settings.confirm()
    expect(page.locator("main")).to_contain_text("persönliche Angaben übernommen", timeout=10000)
    assert mailhelp.site.archive.configuration.active.personal_info == "Max Mustermann\nElternbeirat Klasse 4b"
    assert page.errors == []


def background_change(page, mailhelp, revision):
    """Change the store and let the page check at once instead of after 15 seconds."""
    mailhelp.store.save("synthetic-background-state", {"revision": revision})
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")


def page_fetch(mailhelp):
    """The script's own request for the overview, not a navigation."""
    return lambda response: response.url == f"{mailhelp.url}/" and response.request.resource_type == "fetch"


def refresh_in_background(page, mailhelp, revision):
    """A background change that the split view loads in place; returns once the list is new."""
    page.evaluate("document.querySelector('.master-pane').dataset.old = 'yes'")
    with page.expect_response(page_fetch(mailhelp)):
        background_change(page, mailhelp, revision)
    expect(page.locator(f"{MASTER}[data-old]")).to_have_count(0)


def test_split_selection_survives_background_refresh_and_missing_item(page, mailhelp):
    """Regression: a changed store revision used to jump back to the first card,
    and reloading the whole document made the page flash."""
    if page.device != "desktop":
        return
    sign_in(page, mailhelp)
    identity = f"v-{mail_id(1)}-formular"
    item(page, "#" + identity)
    page.evaluate("window.sameDocument = true")
    for revision in range(2):
        page.evaluate("document.querySelector('.master-pane').scrollTop = 40")
        refresh_in_background(page, mailhelp, revision)
        expect(selected(page)).to_have_attribute("id", identity)
        expect(page.locator(f"{PANE} #detail-{identity}")).to_be_visible()
        assert page.evaluate("document.querySelector('.master-pane').scrollTop") == 40
        # The page now carries the new revision: the next check finds nothing new.
        stand = page.evaluate("fetch('/api/stand').then(response => response.json())")
        assert page.evaluate("document.body.dataset.fingerprint") == stand["fingerprint"]
    assert page.evaluate("window.sameDocument") is True
    # Only the selection is framed; the item shown in Telegram keeps just its badge.
    current = page.locator(f"{MASTER} article.current")
    expect(current).to_contain_text("Aktuell in Telegram")
    assert current.evaluate("card => getComputedStyle(card).borderTopWidth") == "1px"
    assert current.evaluate("card => getComputedStyle(card).outlineStyle") == "none"
    # A manual reload also retains the selection, including after resizing.
    page.set_viewport_size({"width": 900, "height": 900})
    page.reload()
    expect(selected(page)).to_have_count(0)
    page.set_viewport_size({"width": 1366, "height": 900})
    expect(selected(page)).to_have_attribute("id", identity)
    # An item removed in the background falls back to a remaining card.
    name = f"proposal-{mail_id(1)}-formular"
    proposal = mailhelp.store.load_model(name, Proposal)
    mailhelp.store.save(name, {**proposal.model_dump(mode="json"), "status": "rejected"})
    page.reload()
    expect(selected(page)).to_have_attribute("id", f"r-{mail_id(7)}")
    assert mailhelp.writer.created == [] and page.errors == []


def test_background_refresh_waits_for_undo_and_falls_back_to_a_reload(page, mailhelp):
    if page.device != "desktop":
        return
    # The real five-second undo time leaves room for a refresh during the countdown.
    page.route("**/", lambda route: route.fulfill(response=route.fetch(),
               body=route.fetch().text().replace(' data-undo-ms="1000"', '')))
    sign_in(page, mailhelp)
    page.goto(f"{mailhelp.url}/")
    item(page, f"#v-{mail_id(1)}-elternabend")
    page.locator("body").focus()
    page.keyboard.press("x")
    expect(selected(page)).to_have_class(re.compile("leaving"))
    with page.expect_response(page_fetch(mailhelp)):
        background_change(page, mailhelp, 0)
    page.wait_for_timeout(300)
    # The pending action keeps its card and form; the list is not replaced meanwhile.
    expect(selected(page)).to_have_class(re.compile("leaving"))
    toast(page).get_by_role("button", name="Rückgängig").click()
    refresh_in_background(page, mailhelp, 1)
    expect(selected(page)).to_have_attribute("id", f"v-{mail_id(1)}-elternabend")
    expect(selected(page)).not_to_have_class(re.compile("leaving"))
    # A refresh that cannot be loaded (e.g. a server error) becomes a normal reload.
    # That reload is answered with 204, so the document and its script coverage stay.
    reloads = []

    def hold(route):
        if route.request.resource_type == "fetch":
            route.fulfill(status=503, body="weg")
            return
        reloads.append(route.request.url)
        route.fulfill(status=204)

    page.route(f"{mailhelp.url}/", hold)
    background_change(page, mailhelp, 2)
    for _ in range(50):
        if reloads:
            break
        page.wait_for_timeout(100)
    assert reloads == [f"{mailhelp.url}/"]
    # Preserve the failed fetch and reload counters before the next navigation.
    page.collect()
    page.unroute(f"{mailhelp.url}/")
    # Without the detail pane (narrow window) new data reloads the page as before.
    page.set_viewport_size({"width": 900, "height": 900})
    with page.expect_event("framenavigated", predicate=lambda frame: frame == page.main_frame):
        background_change(page, mailhelp, 3)
    without_load_errors(page, "503")
    assert mailhelp.writer.created == [] and page.errors == []


def test_background_refresh_to_inbox_zero(page, mailhelp):
    if page.device != "desktop":
        return
    sign_in(page, mailhelp)
    item(page, f"#v-{mail_id(1)}-formular")
    decide_everything(mailhelp.store)
    with page.expect_response(page_fetch(mailhelp)):
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    expect(page.get_by_role("heading", name="Alles erledigt! Keine offenen Entscheidungen.")).to_be_visible()
    expect(page.locator(".split-view")).to_have_count(0)
    assert page.errors == []


def test_setting_help_hover_keyboard_touch_and_escape(page, mailhelp):
    from mailhelp.web.setting_help import SETTING_HELP
    sign_in(page, mailhelp)
    page.goto(f"{mailhelp.url}/einstellungen")
    controls = page.locator(".info-trigger")
    expect(controls).to_have_count(len(SETTING_HELP) + 2)
    trigger = page.get_by_role("button", name="Info zu Abrufintervall (Sekunden)", exact=True)
    tip = page.locator("#help-poll_interval_seconds")
    expect(tip).to_be_hidden()
    # All controls describe exactly one help text; reading never posts a form.
    sent = []
    page.on("request", lambda request: sent.append(request.url) if request.method == "POST" else None)
    if page.device == "desktop":
        trigger.hover()
        expect(tip).to_have_text(SETTING_HELP["poll_interval_seconds"])
        expect(tip).to_be_visible()
        tip.hover()  # The bubble remains readable when the pointer enters it.
        expect(tip).to_be_visible()
        page.keyboard.press("Escape")  # Hover must be dismissible without first focusing the trigger.
        expect(tip).to_be_hidden()
        page.get_by_role("heading", name="Einstellungen", exact=True).hover()
        trigger.hover()
        expect(tip).to_be_visible()
        page.get_by_role("heading", name="Einstellungen", exact=True).hover()
        expect(tip).to_be_hidden()
    trigger.click()
    expect(tip).to_be_visible()
    expect(page.locator("details.setting[open]")).to_have_count(0)
    trigger.press("Escape")
    expect(tip).to_be_hidden()
    trigger.press("Tab")
    trigger.focus()
    expect(tip).to_be_visible()
    trigger.press("a")  # Other keys do not dismiss the explanation.
    expect(tip).to_be_visible()
    assert audit(page, f"setting-help-{page.device}", page.mobile) == []
    box = tip.bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= page.viewport_size["width"]
    page.emulate_media(color_scheme="dark")
    assert audit(page, f"setting-help-dark-{page.device}", page.mobile) == []
    assert sent == [] and mailhelp.writer.created == [] and page.errors == []
