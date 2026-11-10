"""5.1 R5: deterministic consistency hints with stable rules, evidence and no automatic action."""
from datetime import UTC, date, datetime

from mailhelp.domain.extraction import ExtractionCountConflict, Summary
from mailhelp.domain.mail import MailState
from mailhelp.domain.processing import ProcessingError
from mailhelp.domain.relevance import Relevance
from mailhelp.review.consistency import Rule, hints
from tests.scenarios.web_scenario import mail_id, proposal

NOW = datetime(2026, 11, 10, 9, tzinfo=UTC)
RELEVANT = Relevance(decision="relevant", topic_ids=[], reason="x")


def state(**fields):
    return MailState(id=mail_id(5), config_fingerprint="f" * 64, created_at=NOW, analysis_round=3,
                     imap={"account_id": "0" * 24, "folder": "INBOX", "uidvalidity": 1, "uid": 5}, **fields)


def mail(**metadata):
    return {"text": "x", "imap_received_at": "2026-11-09T08:00:00+00:00", "metadata": metadata,
            "extracted_attachments": [{"filename": "plan.pdf", "extraction_status": "success"},
                                      {"filename": "scan.pdf", "extraction_status": "error"}]}


def test_a_clean_mail_has_no_hints():
    clean = {"text": "x", "imap_received_at": "2026-11-09T08:00:00+00:00", "metadata": {},
             "extracted_attachments": [{"filename": "plan.pdf", "extraction_status": "success"}]}
    assert hints(state(relevance=RELEVANT, summary=Summary(sentences=["Info"]), mail=clean,
                       proposals=[proposal(5, "a", due=date(2026, 11, 20))])) == ()
    assert hints(state(relevance=RELEVANT, summary=Summary(sentences=["Info"]))) == ()


def test_every_rule_names_its_evidence_and_round_and_appears_once():
    conflict = ExtractionCountConflict(category="task", expected_count=2, actual_count=1,
                                       router_call_id="r", extractor_call_id="t")
    event = proposal(5, "e", kind="event", title="Elternabend", description="Bitte Teilnahme zurückmelden",
                     target="calendar-1", start=datetime(2026, 11, 20, 18, tzinfo=UTC),
                     end=datetime(2026, 11, 20, 19, tzinfo=UTC))
    found = hints(state(relevance=RELEVANT, summary=Summary(sentences=["Info"], deadlines=["Freitag"]),
                        extraction_count_conflicts=[conflict, conflict.model_copy(update={"extractor_call_id": "u"})],
                        proposals=[event, proposal(5, "m", status="merged",
                                                   canonical_ref={"mail_id": mail_id(5), "proposal_id": "e"})],
                        mail=mail(text_shortened=True, attachments_omitted=2),
                        error=ProcessingError(code="internal_error", stage="completion", occurred_at=NOW)))
    assert [(hint.rule, hint.severity) for hint in found] == [
        (Rule.COUNT_CONFLICT, "warn"), (Rule.POSSIBLE_OMISSION, "info"), (Rule.UNASSIGNED_DUTY, "info"),
        (Rule.INCOMPLETE, "warn"), (Rule.INCOMPLETE, "warn"), (Rule.INCOMPLETE, "warn"), (Rule.INCOMPLETE, "warn")]
    assert found[0].text == "Router erwartete 2 Aufgaben; 1 wurde extrahiert." and len(found) == 7
    assert found[1].evidence == "Zusammenfassung: Freitag" and "eine Frist allein ist keine Aufgabe" in found[1].text
    assert found[2].evidence == "Termin „Elternabend“"
    assert {hint.evidence for hint in found[3:]} == {"Gespeicherter Verarbeitungsfehler", "Mailtext", "Anhänge",
                                                     "Anhang „scan.pdf“"}
    assert {hint.analysis_round for hint in found} == {3}


def test_a_deadline_with_a_task_or_an_irrelevant_mail_gives_no_omission_hint():
    summary = Summary(sentences=["Info"], deadlines=["Freitag"])
    assert hints(state(relevance=RELEVANT, summary=summary, proposals=[proposal(5, "a")])) == ()
    irrelevant = Relevance(decision="irrelevant", topic_ids=[], reason="x")
    assert hints(state(relevance=irrelevant, summary=summary)) == ()
    event = proposal(5, "e", kind="event", title="Sommerfest", target="calendar-1",
                     start=datetime(2026, 11, 20, 18, tzinfo=UTC), end=datetime(2026, 11, 20, 19, tzinfo=UTC))
    assert hints(state(relevance=RELEVANT, proposals=[event])) == ()


def test_contradictions_and_deadlines_before_the_mail_are_named():
    found = hints(state(relevance=RELEVANT, mail={"text": "x", "imap_received_at": "2026-11-09T08:00:00+00:00"},
                        proposals=[proposal(5, "w", title="Widerspruch", certainty="contradictory",
                                            open_questions=["?"]),
                                   proposal(5, "f", title="Frist", due=date(2026, 11, 1)),
                                   proposal(5, "g", title="Später", due=datetime(2026, 11, 12, 9, tzinfo=UTC))]))
    assert [(hint.rule, hint.evidence) for hint in found] == [
        (Rule.CONTRADICTION, "Vorschlag „Widerspruch“"), (Rule.CONTRADICTION, "Vorschlag „Frist“")]
    assert found[1].text == "Die Frist liegt vor dem Eingang der Mail."
