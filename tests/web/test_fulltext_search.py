"""Full-text search over mail text and attachment text (Planung 2.3, 5)."""
from shared_web_details import with_mail
from web_scenario import mail_id

from mailhelp.review.queries import ArchiveQueries, ArchiveQuery
from mailhelp.review.search import FIELD_LIMIT, MAIL_LIMIT, Hit, bounded, excerpt, fold, terms


def test_folding_treats_case_umlauts_accents_and_spacing_alike():
    assert fold("Größe  der\nStraße") == fold("GROESSE der strasse") == "groesse der strasse"
    assert fold("Café Æsop ø") == "cafe aesop oe" and fold("ﬁle") == "file"
    assert terms('Rechnung "Herr Müller"  ') == ["rechnung", "herr mueller"]
    assert terms('"" " "') == []


def test_excerpt_shows_the_original_spelling_with_context():
    text = "A" * 80 + " Bitte die Rechnung von Frau Müller bis Freitag bezahlen. " + "B" * 80
    hit = excerpt([("Betreff", "Info"), ("Mailtext", text)], [fold("mueller")])
    start = text.index("Müller")
    end = start + len("Müller")
    assert hit == Hit("Mailtext", "…" + text[start - 60:start], "Müller", text[end:end + 60] + "…")
    assert excerpt([("Betreff", "Info")], ["fehlt"]) is None and excerpt([("Betreff", "x")], []) is None
    short = excerpt([("Anhang", "Größe")], [fold("groesse")])
    assert short == Hit("Anhang", "", "Größe", "")


def test_index_fields_are_bounded():
    huge = "x" * (FIELD_LIMIT + 10)
    fields = bounded([("a", huge), ("b", "  "), ("c", huge), ("d", huge)])
    assert [label for label, _ in fields] == ["a", "c"]
    assert sum(len(text) for _, text in fields) == MAIL_LIMIT


def test_search_finds_body_and_attachment_text_and_shows_where(web):
    with_mail(web.store, 1, text="Die Klassenfahrt kostet 120 Euro.\nBitte bis Freitag überweisen.",
              extracted_attachments=[{"filename": "Elternbrief.pdf", "text": "Treffpunkt: Hauptbahnhof <Gleis 3>"}])
    queries = ArchiveQueries(web.store)
    items, total = queries.search(ArchiveQuery(q="ueberweisen klassenfahrt"))
    assert total == 1 and items[0]["id"] == mail_id(1)
    assert items[0]["hit"].where == "Mailtext" and items[0]["hit"].match == "überweisen"
    items, _ = queries.search(ArchiveQuery(q="hauptbahnhof"))
    assert items[0]["hit"].where == "Anhang „Elternbrief.pdf“"
    assert queries.search(ArchiveQuery(q="elternbrief"))[1] == 1
    assert queries.search(ArchiveQuery(q="hauptbahnhof", scope="meta"))[1] == 0
    assert queries.search(ArchiveQuery(q='"kostet 120 Euro"'))[1] == 1
    assert queries.search(ArchiveQuery(q='"120 kostet"'))[1] == 0
    assert queries.search(ArchiveQuery(q="hauptbahnhof freitag"))[1] == 1
    assert queries.search(ArchiveQuery(q="hauptbahnhof mittwoch"))[1] == 0
    # A term never matches across two fields.
    assert queries.search(ArchiveQuery(q='"überweisen elternbrief"'))[1] == 0
    page = web.browser.request("GET", "/mails?q=Gleis").body.decode()
    assert "Gefunden in Anhang „Elternbrief.pdf“" in page and "<mark>Gleis</mark>" in page
    assert "&lt;" in page and "<Gleis" not in page
    meta = web.browser.request("GET", "/mails?q=Gleis&scope=meta").body.decode()
    assert "Keine gespeicherte Mail passt" in meta and 'value="meta" selected' in meta
    assert web.browser.request("GET", "/mails?scope=alles").status == 422


def test_metadata_still_found_after_retention_removed_the_text(web):
    with_mail(web.store, 1, text="Geheimer Inhalt")
    queries = ArchiveQueries(web.store)
    assert queries.search(ArchiveQuery(q="geheimer"))[1] == 1
    state = web.store.load("mail-" + mail_id(1))
    state["mail"] = None
    web.store.save("mail-" + mail_id(1), state)
    assert queries.search(ArchiveQuery(q="geheimer"))[1] == 0
    subject = queries.items()[0]["subject"]
    found, _ = queries.search(ArchiveQuery(q=subject.split()[0], scope="meta"))
    assert found and found[0]["hit"].where in {"Betreff", "Absender"}
    assert queries.search(ArchiveQuery())[0][0]["hit"] is None
