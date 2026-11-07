"""Observable state and consent invariants exposed by the 4.1 mutation audit."""
import errno
import json
import os
import stat
import tempfile
from datetime import UTC, date, datetime, time, tzinfo
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from mailhelp import storage
from mailhelp.domain.mail import MailState
from mailhelp.domain.processing import TelegramDialogState
from mailhelp.domain.proposal import (
    KnownTemporalFacts,
    ProposalRevisionDelta,
    _check_revision_permissions,
    _revision_day,
    _revision_interval,
    apply_proposal_revision,
    invalidate_creation_permissions,
    required_revision_questions,
)
from mailhelp.domain.proposal_sources import ProposalReference
from mailhelp.domain.temporal import TemporalFact
from mailhelp.external.confirmed import _with_external_result, execute_confirmed
from mailhelp.external.contracts import PreparedWrite, TargetWriter
from mailhelp.llm.adapter import PermanentError, UncertainWriteError
from mailhelp.storage import AlreadyRunning, CorruptState, JsonStore, atomic_replace
from tests.fakes.factories import build_mail_state, build_proposal


def test_every_delete_and_touch_advances_exactly_one_revision_without_changing_archive(tmp_path):
    store = JsonStore(tmp_path)
    store.save("mail-one", {"value": "Grüße"})
    store.save("mail-two", {"value": 2})
    archive = store.archive_revision
    revision = store.revision
    for operation in (lambda: store.delete("mail-one"), lambda: store.delete("mail-one"), store.touch, store.touch):
        operation()
        revision += 1
        assert store.revision == revision and store.archive_revision == archive
        assert store.load("mail-one") is None and store.load("mail-two") == {"value": 2}


def test_running_instance_error_identifies_the_locked_directory(tmp_path):
    error = AlreadyRunning(tmp_path)
    assert error.directory == tmp_path
    assert str(error) == f"Datenverzeichnis wird bereits verwendet: {tmp_path}"


@pytest.mark.parametrize("status", ["pending_confirmation", "needs_clarification", "confirmed"])
def test_local_revision_revokes_every_special_creation_permission_and_web_receipt(status):
    previous = build_proposal(status=status).model_copy(update={
        "explicit_create_fallback_confirmed": True,
        "explicit_non_binding_create_confirmed": True,
        "explicit_duplicate_create_confirmed_version": 1,
        "confirmed_web_actor": "web:synthetic-session",
    })
    result = invalidate_creation_permissions(previous)
    assert result.explicit_create_fallback_confirmed is False
    assert result.explicit_non_binding_create_confirmed is False
    assert result.explicit_duplicate_create_confirmed_version is None
    assert result.confirmed_web_actor is None
    assert (result.id, result.source_mail_id, result.version) == (previous.id, previous.source_mail_id, previous.version)
    assert previous.explicit_create_fallback_confirmed is True
    assert previous.explicit_non_binding_create_confirmed is True
    assert previous.explicit_duplicate_create_confirmed_version == 1
    assert previous.confirmed_web_actor == "web:synthetic-session"
    assert result.status == ("confirmed" if status == "confirmed" else "pending_confirmation")


@pytest.mark.parametrize("classification,question", [
    ("new", None),
    ("non_binding", "Soll der nicht bindende Hinweis dennoch als neuer Eintrag angelegt werden?"),
    ("already_completed", "Der Eintrag ist bereits abgeschlossen und nicht direkt ausführbar."),
    ("change", "Welcher bestehende Eintrag soll geändert werden?"),
    ("cancellation", "Welcher bestehende Eintrag soll storniert werden?"),
    ("recurring", "Wiederkehrende Einträge werden nicht automatisch angelegt."),
    ("unsupported", "Diese Art von Eintrag wird nicht unterstützt."),
])
def test_classification_questions_are_stable_keys_for_answered_question(classification, question):
    # The exact text is a stored identifier: revision deltas must answer an existing question.
    item = build_proposal(classification=classification)
    assert required_revision_questions(item) == ([] if question is None else [question])


@pytest.mark.parametrize("changes,question", [
    ({"duplicate_check_failed": True}, "Dublettenprüfung nicht verfügbar; vor einer Anlage erneut prüfen."),
    ({"responsibility": "other"}, "Ist die Nutzerin oder der Nutzer für diesen Eintrag zuständig?"),
    ({"certainty": "uncertain"}, "Ist die extrahierte Information sicher belegt?"),
    ({"certainty": "contradictory"}, "Wie soll der Widerspruch in den Angaben aufgelöst werden?"),
])
def test_fact_questions_are_stable_keys_and_only_appear_when_required(changes, question):
    item = build_proposal().model_copy(update=changes)
    assert required_revision_questions(item) == [question]
    assert required_revision_questions(build_proposal()) == []


@pytest.mark.parametrize("field,message", [
    ("explicit_create_fallback_confirmed", "Die Ersatz-Neuanlage erfordert eine deterministische ausdrückliche Bestätigung"),
    ("explicit_non_binding_create_confirmed", "Ein nicht bindender Hinweis erfordert eine deterministische ausdrückliche Bestätigung"),
])
def test_only_explicit_deterministic_consent_can_change_creation_permissions(field, message):
    for value in (True, False):
        with pytest.raises(ValueError) as error:
            _check_revision_permissions(build_proposal(), {field: value}, False)
        assert str(error.value) == message
        assert _check_revision_permissions(build_proposal(), {field: value}, True) is None


def test_resolving_a_day_keeps_a_known_clock_and_checks_the_new_start():
    item = build_proposal(kind="event", status="needs_clarification", open_questions=["Wann?"],
                          known_temporal_facts=KnownTemporalFacts(start_time=time(9)))
    day = date(2026, 11, 6)
    changes = {"temporal_date": day}
    known = _revision_day(item, changes)
    assert known == KnownTemporalFacts(date=day, start_time=time(9))
    assert changes == {"known_temporal_facts": known}
    assert item.known_temporal_facts.date is None
    with pytest.raises(ValueError, match="start widerspricht"):
        _revision_day(item, {"temporal_date": day, "start": datetime(2026, 11, 7, 9, tzinfo=UTC)})
    all_day = build_proposal(kind="event", status="needs_clarification", all_day=True, open_questions=["Wann?"],
                            known_temporal_facts=KnownTemporalFacts(date=day))
    assert _revision_day(all_day, {"end": day}) == all_day.known_temporal_facts
    with pytest.raises(ValueError, match="end widerspricht"):
        _revision_day(all_day, {"end": date(2026, 11, 7)})


@pytest.mark.parametrize("invalid_id", [None, "", True, False])
def test_external_receipts_require_a_real_nonempty_identifier(invalid_id):
    with pytest.raises(ValueError) as error:
        _with_external_result(build_proposal(status="writing"), {"id": invalid_id})
    assert str(error.value) == "Externe Integration: benötigter Schlüsselpfad id fehlt"


@pytest.mark.parametrize("key", ["url", "html_url", "htmlLink"])
def test_external_receipts_keep_the_provider_link_and_zero_is_a_valid_identifier(key):
    result = _with_external_result(build_proposal(status="writing"), {"id": 0, key: "https://synthetic.test/action"})
    assert (result.status, result.external_id, result.external_link) == ("created", "0", "https://synthetic.test/action")


def test_rejected_creation_has_no_read_or_write_side_effect_and_a_clear_reason():
    # object() has no provider methods: touching a provider would fail this test.
    messages = [
        (build_proposal(responsibility="other"), "Nur neue, sichere und eigene Vorschläge oder ausdrücklich bestätigte Ersatz-Neuanlagen dürfen extern angelegt werden"),
        (build_proposal(), "Schreiben erfordert vollständige, bestätigte Vorschlagsversion"),
    ]
    saved = []
    for item, message in messages:
        with pytest.raises(ValueError) as error:
            execute_confirmed(item, object(), saved.append)
        assert str(error.value) == message
    assert saved == []


def test_saved_state_is_readable_unicode_sorted_json_with_one_trailing_newline(tmp_path):
    store = JsonStore(tmp_path)
    store.save("state", {"z": 2, "a": "Grüße"})
    assert (tmp_path / "state.json").read_bytes() == '{\n  "a": "Grüße",\n  "z": 2\n}\n'.encode()
    assert not (tmp_path / "state.tmp").exists()
    assert store.revision == 1 and store.archive_revision == 0
    store.save("mail-first", {"first": True})
    assert store.revision == 2 and store.archive_revision == 1
    store.save("web-session", {"session": True})
    assert store.revision == 2 and store.archive_revision == 1


@pytest.mark.parametrize("name", ["..", "../mail-one", "bad/name", "bad\\name", "", "name\n", "a.b", "a:b"])
def test_invalid_state_names_never_touch_existing_files(tmp_path, name):
    store = JsonStore(tmp_path)
    store.save("Valid-State_Z9", {"safe": True})
    for operation in (lambda: store.load(name), lambda: store.save(name, {}), lambda: store.delete(name)):
        with pytest.raises(ValueError, match="^Ungültiger Zustandsname$"):
            operation()
    assert store.load("Valid-State_Z9") == {"safe": True} and store.revision == 1


def test_external_write_uses_the_confirmed_version_key_and_persists_writing_before_create():
    events = []
    item = build_proposal(version=7, status="confirmed")
    key = f"mailhelp:{item.source_mail_id}:p1:v7"
    class Writer:
        def reconcile(self, received_key):
            events.append(("reconcile", received_key))
            return None
        def create(self, proposal, received_key):
            events.append(("create", received_key, proposal.status))
            return {"id": "external", "url": "https://synthetic.test/action"}
    def persist(proposal):
        events.append(("persist", proposal.status))
    created, result = execute_confirmed(item, Writer(), persist, authorize=lambda: True)
    assert events == [("reconcile", key), ("persist", "writing"), ("create", key, "writing"), ("persist", "created")]
    assert created.version == 7 and item.status == "confirmed"
    assert created.external_id == "external" and result["id"] == "external"


@pytest.mark.parametrize("changes,message", [
    ({"start": None}, "Ein vollständiger Termin benötigt Beginn und Ende"),
    ({"end": None}, "Ein vollständiger Termin benötigt Beginn und Ende"),
    ({"known_temporal_facts": KnownTemporalFacts(date=date(2026, 11, 6))},
     "Unvollständige Zeitfakten dürfen nicht mit Terminintervallen gemischt werden"),
    ({"end": datetime(2026, 11, 6, 9, tzinfo=UTC)}, "Terminende muss nach dem Beginn liegen"),
    ({"end": datetime(2026, 11, 6, 8, tzinfo=UTC)}, "Terminende muss nach dem Beginn liegen"),
    ({"all_day": True}, "Ganztägige Termine benötigen reine Datumswerte"),
    ({"duration_is_upper_bound": True}, "Eine Dauer-Obergrenze benötigt eine Dauer"),
    ({"due": date(2026, 11, 6)}, "Termine dürfen keine Aufgabenfrist enthalten"),
    ({"start": datetime(2026, 11, 6, 9), "end": datetime(2026, 11, 6, 10)},
     "Zeitgebundene Termine benötigen einen eindeutigen UTC-Offset"),
    ({"start": None, "open_questions": ["Wann?"], "known_temporal_facts": KnownTemporalFacts(date=date(2026, 11, 6))},
     "Unvollständige Zeitfakten dürfen nicht mit Terminintervallen gemischt werden"),
    ({"start": date(2026, 11, 6), "end": date(2026, 11, 7)},
     "Zeitgebundene Termine benötigen Datums- und Zeitwerte"),
])
def test_invalid_event_intervals_report_the_specific_business_error(changes, message):
    values = {"kind": "event", "start": datetime(2026, 11, 6, 9, tzinfo=UTC),
              "end": datetime(2026, 11, 6, 10, tzinfo=UTC), **changes}
    with pytest.raises(ValidationError) as error:
        build_proposal(**values)
    assert [item["msg"] for item in error.value.errors()] == [f"Value error, {message}"]


def test_dialog_references_preserve_mail_proposal_and_exact_version():
    state = TelegramDialogState(mail_id="a" * 24, proposal_id="question", version=7)
    assert state.reference() == ("a" * 24, "question", 7)
    with pytest.raises(AssertionError):
        TelegramDialogState().reference()


@pytest.mark.parametrize("changes,message", [
    ({"merge_review_required": True}, "Ein ungeprüfter Zusatz benötigt seine kanonische Referenz"),
    ({"default_duration_minutes": 60}, "Standarddauer benötigt ein zeitgebundenes Terminintervall und Herkunft"),
    ({"status": "merged"}, "Zusammengeführte Vorschläge benötigen eine kanonische Referenz"),
    ({"status": "merged", "canonical_ref": ProposalReference(mail_id="a" * 24, proposal_id="p1")},
     "Ein Vorschlag darf nicht auf sich selbst verweisen"),
    ({"status": "simulated", "external_id": "external"}, "Ein simulierter Vorschlag darf kein externes Ergebnis enthalten"),
    ({"simulation_notified": True}, "Eine Simulation darf nur im simulierten Zustand als gemeldet markiert werden"),
    ({"target_event_id": "existing"}, "Nur Termine unterstützen Terminaktualisierungen"),
    ({"is_cancellation": True}, "Eine Stornierung erfordert eine Ziel-Event-ID"),
    ({"status": "already_exists", "open_questions": ["Wer?"]}, "Ein bereits vorhandener Eintrag darf keine offenen Fragen enthalten"),
    ({"status": "already_exists"}, "Ein bereits vorhandener Eintrag benötigt Duplikat-Informationen"),
    ({"status": "pending_confirmation", "open_questions": ["Wer?"]}, "Nur vollständige neue Vorschläge dürfen bestätigt werden"),
    ({"start": datetime(2026, 11, 6, 9, tzinfo=UTC)}, "Aufgaben dürfen keine Kalenderzeit enthalten"),
    ({"end": datetime(2026, 11, 6, 10, tzinfo=UTC)}, "Aufgaben dürfen keine Kalenderzeit enthalten"),
    ({"all_day": True}, "Aufgaben dürfen keine Kalenderzeit enthalten"),
    ({"duration_minutes": 60}, "Nur Termine dürfen eine Dauer enthalten"),
    ({"due": datetime(2026, 11, 6, 9)}, "Zeitgebundene Aufgabenfristen benötigen einen eindeutigen UTC-Offset"),
    ({"known_temporal_facts": KnownTemporalFacts(date=date(2026, 11, 6))}, "Nur Termine dürfen bekannte Zeitfakten enthalten"),
])
def test_invalid_task_lifecycle_and_authority_report_the_specific_business_error(changes, message):
    with pytest.raises(ValidationError) as error:
        build_proposal(**changes)
    assert [item["msg"] for item in error.value.errors()] == [f"Value error, {message}"]


@pytest.mark.parametrize("suffix", ["corrupt", "invalid"])
@pytest.mark.parametrize("name", ["proposal-one", "mail-one", "reconciliation-merge-one",
                                 "action-ledger", "command-inbox", "telegram-inbox"])
def test_quarantined_authority_blocks_both_read_modes_instead_of_becoming_a_default(tmp_path, name, suffix):
    path = tmp_path / f"{name}.{suffix}"
    path.write_text("synthetic damaged authority", encoding="utf-8")
    store = JsonStore(tmp_path)
    for read in (store.load, store.peek):
        with pytest.raises(CorruptState) as error:
            read(name, {"default": True})
        assert str(error.value) == f"Isolierter Zustand muss repariert werden: {name}.json"
    assert path.read_text() == "synthetic damaged authority"


@pytest.mark.parametrize("raw", [b"{", b"\xff"])
def test_peeking_never_moves_damaged_json_but_loading_quarantines_it(tmp_path, raw):
    path = tmp_path / "mail-bad.json"
    path.write_bytes(raw)
    store = JsonStore(tmp_path)
    with pytest.raises(CorruptState) as error:
        store.peek("mail-bad")
    assert str(error.value) == "Beschädigter Zustand: mail-bad.json" and path.read_bytes() == raw
    with pytest.raises(CorruptState) as error:
        store.load("mail-bad")
    assert str(error.value) == "Beschädigter Zustand isoliert: mail-bad.corrupt"
    assert not path.exists() and path.with_suffix(".corrupt").read_bytes() == raw


@pytest.mark.parametrize("multiple", [False, True])
def test_peek_model_preserves_invalid_source_and_load_model_quarantines_only_that_source(tmp_path, multiple):
    store = JsonStore(tmp_path)
    value = build_mail_state().model_dump(mode="json")
    value["id"] = "invalid"
    if multiple:
        value["analysis_round"] = 0
    store.save("mail-bad", value)
    original = (tmp_path / "mail-bad.json").read_bytes()
    with pytest.raises(CorruptState) as error:
        store.peek_model("mail-bad", MailState)
    assert str(error.value) == "Schemawidriger Zustand: mail-bad.json"
    assert (tmp_path / "mail-bad.json").read_bytes() == original
    with pytest.raises(CorruptState) as error:
        store.load_model("mail-bad", MailState)
    locations = "id, analysis_round" if multiple else "id"
    assert str(error.value) == f"Schemawidriger Zustand isoliert: mail-bad.invalid; Schlüsselpfad: {locations}"
    assert (tmp_path / "mail-bad.invalid").read_bytes() == original


def test_missing_models_return_the_exact_default_without_writing_it(tmp_path):
    store = JsonStore(tmp_path)
    default = build_mail_state()
    for read in (store.peek_model, store.load_model):
        assert read("mail-missing", MailState) is None
        assert read("mail-missing", MailState, default) is default
    assert store.names() == []


def test_invalid_root_is_quarantined_with_a_root_location_instead_of_a_field_name(tmp_path):
    store = JsonStore(tmp_path)
    store.save("dialog", [])
    with pytest.raises(CorruptState) as error:
        store.load_model("dialog", TelegramDialogState)
    assert str(error.value) == "Schemawidriger Zustand isoliert: dialog.invalid; Schlüsselpfad: <root>"
    assert not (tmp_path / "dialog.json").exists()
    assert json.loads((tmp_path / "dialog.invalid").read_text()) == []


@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt])
def test_atomic_replace_keeps_the_original_and_removes_temporary_files_on_any_failure(tmp_path, monkeypatch, failure):
    path = tmp_path / "nested" / "more" / "config.yaml"
    atomic_replace(path, "vorher: Grüße\n")
    monkeypatch.setattr(storage, "os", SimpleNamespace(**vars(storage.os)))
    def fail(*args):
        raise failure("synthetic replacement failure")
    monkeypatch.setattr(storage.os, "replace", fail)
    with pytest.raises(failure, match="synthetic replacement failure"):
        atomic_replace(path, "nachher: falsch\n")
    assert path.read_bytes() == "vorher: Grüße\n".encode()
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize("remaining", [[], ["Andere offene Frage"]])
def test_a_revision_answers_one_question_advances_one_version_and_revokes_duplicate_consent(remaining):
    item = build_proposal(version=7, open_questions=["Welche Aufgabe?", *remaining],
                          explicit_duplicate_create_confirmed_version=7)
    delta = ProposalRevisionDelta(answered_question="Welche Aufgabe?", changes={"title": "Neue Aufgabe"})
    result = apply_proposal_revision(item, delta)
    assert (result.id, result.source_mail_id, result.version, result.title) == (item.id, item.source_mail_id, 8, "Neue Aufgabe")
    assert result.open_questions == remaining and result.explicit_duplicate_create_confirmed_version is None
    assert result.status == ("needs_clarification" if remaining else "pending_confirmation")
    assert item.version == 7 and item.title != result.title and item.open_questions == ["Welche Aufgabe?", *remaining]
    assert item.explicit_duplicate_create_confirmed_version == 7


def test_revision_of_an_unknown_question_never_changes_the_proposal():
    item = build_proposal(open_questions=["Wer?"])
    original = item.model_dump()
    with pytest.raises(ValueError) as error:
        apply_proposal_revision(item, ProposalRevisionDelta(answered_question="Was?", changes={"title": "Falsch"}))
    assert str(error.value) == "Die beantwortete Frage ist im Vorschlag nicht offen"
    assert item.model_dump() == original


def test_revision_derives_new_business_questions_without_duplicating_existing_ones():
    question = "Ist die Nutzerin oder der Nutzer für diesen Eintrag zuständig?"
    for remaining in ([], [question]):
        item = build_proposal(open_questions=["Wer?", *remaining])
        result = apply_proposal_revision(item, ProposalRevisionDelta(answered_question="Wer?", changes={"responsibility": "other"}))
        assert result.open_questions == [question] and result.status == "needs_clarification"


def test_an_incomplete_interval_retains_the_clock_until_start_and_end_are_known():
    day = date(2026, 11, 6)
    start, end = datetime(2026, 11, 6, 9, tzinfo=UTC), datetime(2026, 11, 6, 10, tzinfo=UTC)
    known = KnownTemporalFacts(date=day, start_time=time(9))
    item = build_proposal(kind="event", open_questions=["Wann?"], known_temporal_facts=known)
    half = {"start": start}
    _revision_interval(item, half, known)
    assert half == {"known_temporal_facts": KnownTemporalFacts(date=day, start=start)}
    complete = {"start": start, "end": end}
    _revision_interval(item, complete, known)
    assert complete == {"start": start, "end": end, "known_temporal_facts": None}
    assert item.known_temporal_facts == known and known.start_time == time(9)
    all_day = {"all_day": True, "start": day}
    _revision_interval(item, all_day, known)
    assert all_day == {"all_day": True, "start": day, "known_temporal_facts": None}


def test_revision_never_changes_a_confirmed_clock_but_leaves_date_only_resolution_to_the_day_guard():
    start = datetime(2026, 11, 6, 9, tzinfo=UTC)
    item = build_proposal(kind="event", start=start, end=datetime(2026, 11, 6, 10, tzinfo=UTC))
    for known in (None, KnownTemporalFacts(start=start)):
        with pytest.raises(ValueError) as error:
            _revision_interval(item, {"start": datetime(2026, 11, 6, 11, tzinfo=UTC)}, known)
        assert str(error.value) == "Ein bestätigter Terminbeginn darf nicht verändert werden"
        unchanged = {"start": start}
        _revision_interval(item, unchanged, known)
        assert item.start == start
    all_day = build_proposal(kind="event", all_day=True, start=date(2026, 11, 6), end=date(2026, 11, 7))
    changes = {"start": date(2026, 11, 8)}
    _revision_interval(all_day, changes, None)
    assert changes == {"start": date(2026, 11, 8)} and all_day.start == date(2026, 11, 6)


@pytest.mark.parametrize("name,archive,operational", [
    ("mail-one", True, True), ("analysis-one", True, True), ("history-one", True, True),
    ("proposal-one", True, True), ("command-inbox", False, False), ("web-session", False, False),
])
def test_each_state_category_invalidates_exactly_the_relevant_cache(tmp_path, name, archive, operational):
    store = JsonStore(tmp_path)
    for count in (1, 2):
        store.save(name, {"value": count})
        assert store.revision == count * operational and store.archive_revision == count * archive


def test_revoking_non_binding_creation_reopens_the_consent_question_without_duplicates():
    question = "Soll der nicht bindende Hinweis dennoch als neuer Eintrag angelegt werden?"
    for previous_questions in ([], [question], ["Zusatzfrage"]):
        item = build_proposal(classification="non_binding", explicit_non_binding_create_confirmed=True,
                              status="needs_clarification" if previous_questions else "pending_confirmation",
                              open_questions=previous_questions)
        result = invalidate_creation_permissions(item)
        expected = previous_questions if question in previous_questions else [*previous_questions, question]
        assert result.open_questions == expected and result.status == "needs_clarification"
        assert result.explicit_non_binding_create_confirmed is False
        assert item.open_questions == previous_questions and item.explicit_non_binding_create_confirmed is True


@pytest.mark.parametrize("field", ["pending_sources", "matching_candidates"])
def test_additional_sources_require_the_same_stable_mapping_question(field):
    item = build_proposal(status="needs_clarification", **{field: [ProposalReference(mail_id="b" * 24, proposal_id="source")]})
    assert required_revision_questions(item) == ["Zuordnung der zusätzlichen Quelle prüfen."]


def test_incomplete_event_questions_distinguish_a_confirmed_start_from_an_unresolved_clock():
    item = build_proposal(kind="event", open_questions=["Wann?"])
    assert required_revision_questions(item) == ["Wann beginnt der Termin?", "Wann endet der Termin?"]
    known = item.model_copy(update={"known_temporal_facts": KnownTemporalFacts(start=datetime(2026, 11, 6, 9, tzinfo=UTC))})
    assert required_revision_questions(known) == ["Wann endet der Termin?"]
    clock_only = item.model_copy(update={"known_temporal_facts": KnownTemporalFacts(start_time=time(9))})
    assert required_revision_questions(clock_only) == ["Wann beginnt der Termin?", "Wann endet der Termin?"]


def test_revision_day_keeps_existing_authoritative_dates_and_rejects_conflicting_fields():
    day, other = date(2026, 11, 6), date(2026, 11, 7)
    fact = TemporalFact(normalized_date=day, year_source="explicit_mail", status="resolved")
    item = build_proposal(kind="event", open_questions=["Wann?"], temporal_fact=fact)
    for field in ("temporal_date", "start", "due"):
        with pytest.raises(ValueError) as error:
            _revision_day(item, {field: other})
        assert str(error.value) == f"{field} widerspricht dem validierten Datum 2026-11-06"
    changes = {"temporal_date": day}
    assert _revision_day(item, changes) is None and changes == {}
    complete = build_proposal(kind="event", start=datetime(2026, 11, 6, 9, tzinfo=UTC), end=datetime(2026, 11, 6, 10, tzinfo=UTC))
    changes = {"temporal_date": day}
    assert _revision_day(complete, changes) is None and changes == {}
    unknown = build_proposal(kind="event", open_questions=["Wann?"])
    changes = {"temporal_date": day}
    assert _revision_day(unknown, changes) == KnownTemporalFacts(date=day)
    assert changes == {"known_temporal_facts": KnownTemporalFacts(date=day)}
    assert _revision_day(item, {"end": datetime(2026, 11, 7, 1, tzinfo=UTC)}) is None
    with pytest.raises(ValueError, match="^end widerspricht dem validierten Datum 2026-11-06$"):
        _revision_day(item.model_copy(update={"all_day": True}), {"end": datetime(2026, 11, 7, 1, tzinfo=UTC)})


@pytest.mark.parametrize("status", ["confirmed", "writing", "uncertain"])
def test_dry_run_clears_external_receipts_and_persists_the_simulation_without_contacting_a_provider(status):
    item = build_proposal(status=status, external_id="stale-id", external_link="https://synthetic.test/stale")
    saved = []
    result, receipt = execute_confirmed(item, object(), saved.append, test_mode=True)
    assert result.status == "simulated" and result.external_id is None and result.external_link is None
    assert saved == [result] and receipt == {"simulation": True}
    assert item.external_id == "stale-id" and item.status == status


def test_repeating_a_completed_simulation_neither_contacts_nor_saves_again():
    item = build_proposal(status="simulated")
    saved = []
    for _ in range(2):
        result, receipt = execute_confirmed(item, object(), saved.append)
        assert result is item and receipt == {"simulation": True}
    assert saved == []


@pytest.mark.parametrize("mode", ["write", "already_present", "revoked", "wrong_profile", "wrong_provider"])
def test_profile_two_and_the_last_authorization_check_are_enforced_at_the_write_boundary(mode):
    events, saved = [], []
    class Writer(TargetWriter):
        service, role, label, target, target_profile = "todoist", "tasks", "Synthetic", "inbox", 2
        def check_access(self): pass
        def close(self): pass
        def reconcile(self, key):
            events.append("reconcile")
            return None
        def prepare(self, proposal, key):
            events.append("prepare")
            assert proposal.status == "confirmed" and key.endswith(":v7")
            return PreparedWrite(lambda: events.append("operation") or {"id": "external"},
                                 requires_write=mode != "already_present")
    item = build_proposal(version=7, status="confirmed", target_profile=1 if mode == "wrong_profile" else 2,
                          target_provider="microsoft_todo" if mode == "wrong_provider" else "todoist")
    result, receipt = execute_confirmed(item, Writer(), saved.append, authorize=lambda: mode != "revoked")
    if mode in {"wrong_profile", "wrong_provider"}:
        assert result is item and receipt == {"target_mismatch": True} and events == [] and saved == []
    elif mode == "revoked":
        assert result is item and receipt == {"authorization_invalid": True}
        assert events == ["reconcile", "prepare"] and saved == []
    else:
        assert result.status == "created" and receipt == {"id": "external"}
        assert result.external_link is None
        assert events == ["reconcile", "prepare", "operation"]
        assert [proposal.status for proposal in saved] == (["created"] if mode == "already_present" else ["writing", "created"])


def test_state_inventory_is_sorted_and_ignores_folders_temporary_files_and_quarantine(tmp_path):
    store = JsonStore(tmp_path)
    for name in ("mail-z", "mail-A", "other"):
        store.save(name, {"name": name})
    (tmp_path / "mail-folder.json").mkdir()
    for name in ("mail-pending.tmp", "mail-bad.corrupt", "mail-invalid.invalid"):
        (tmp_path / name).write_text("synthetic")
    assert store.names("mail-") == ["mail-A", "mail-z"]
    assert store.names() == ["mail-A", "mail-z", "other"]


def test_peek_migrates_only_in_memory_and_load_persists_the_migration_once(tmp_path):
    store = JsonStore(tmp_path)
    value = build_mail_state().model_dump(mode="json")
    value["schema_version"] = 8
    store.save("mail-legacy", value)
    path = tmp_path / "mail-legacy.json"
    original, revision = path.read_bytes(), store.revision
    peeked = store.peek_model("mail-legacy", MailState)
    assert peeked.schema_version == 9 and path.read_bytes() == original and store.revision == revision
    loaded = store.load_model("mail-legacy", MailState)
    assert loaded == peeked and store.load("mail-legacy")["schema_version"] == 9
    assert store.revision == revision + 1
    assert store.load_model("mail-legacy", MailState) == loaded and store.revision == revision + 1


@pytest.mark.parametrize("failure,status", [
    (PermanentError("synthetic refusal"), "failed"),
    (httpx.HTTPStatusError("synthetic refusal", request=httpx.Request("POST", "https://synthetic.test"),
                           response=httpx.Response(400)), "failed"),
    (UncertainWriteError("synthetic lost response"), "uncertain"),
    (httpx.ReadTimeout("synthetic timeout"), "uncertain"),
    (httpx.ConnectError("synthetic transport failure"), "uncertain"),
])
def test_write_failures_persist_the_exact_recoverable_status(failure, status):
    item, saved = build_proposal(status="confirmed"), []
    class Writer:
        def reconcile(self, key): return None
        def create(self, proposal, key): raise failure
    result, receipt = execute_confirmed(item, Writer(), saved.append, authorize=lambda: True)
    assert result.status == status and receipt == {} and saved[-1] is result
    assert [proposal.status for proposal in saved] == ["writing", status]
    assert result.version == item.version and result.id == item.id and item.status == "confirmed"


def test_unclassified_write_failure_is_reconciled_on_restart_and_never_repeated():
    item, saved, writes = build_proposal(status="confirmed"), [], []
    class Writer:
        def reconcile(self, key): return None
        def create(self, proposal, key):
            writes.append(key)
            raise RuntimeError("synthetic unexpected failure")
    writer = Writer()
    with pytest.raises(RuntimeError, match="synthetic unexpected failure"):
        execute_confirmed(item, writer, saved.append)
    assert [proposal.status for proposal in saved] == ["writing"]
    for _ in range(2):
        result, receipt = execute_confirmed(saved[-1], writer, saved.append)
        assert result.status == "uncertain" and receipt == {}
    assert len(writes) == 1 and [proposal.status for proposal in saved] == ["writing", "uncertain", "uncertain"]


def test_a_confirmed_record_with_unanswered_questions_cannot_contact_a_provider():
    saved = []
    item = build_proposal(status="confirmed", open_questions=["Wer?"])
    with pytest.raises(ValueError, match="^Schreiben erfordert vollständige, bestätigte Vorschlagsversion$"):
        execute_confirmed(item, object(), saved.append)
    assert saved == []


def test_lock_metadata_replaces_a_long_stale_record_without_trailing_bytes(tmp_path):
    path = tmp_path / ".lock"
    path.write_text('{"pid":2147483647,"stale":"old diagnostic content"}', encoding="ascii")
    with JsonStore(tmp_path) as store:
        assert store.lock is not None
    assert json.loads(path.read_text(encoding="ascii")) == {"pid": os.getpid()}
    assert store.lock is None


def test_save_flushes_and_syncs_the_file_before_replace_and_then_syncs_the_directory(tmp_path, monkeypatch):
    events = []
    original = storage.os
    proxy = SimpleNamespace(**vars(original))
    def sync(descriptor):
        info = original.fstat(descriptor)
        if stat.S_ISREG(info.st_mode):
            assert info.st_size > 0  # the buffered text was flushed before fsync
            events.append("file_sync")
        else:
            assert stat.S_ISDIR(info.st_mode) and events[-1] == "replace"
            events.append("directory_sync")
        original.fsync(descriptor)
    def replace(source, target):
        assert events == ["file_sync"]
        original.replace(source, target)
        events.append("replace")
    proxy.fsync, proxy.replace = sync, replace
    monkeypatch.setattr(storage, "os", proxy)
    JsonStore(tmp_path).save("state", {"content": "Grüße"})
    assert events == (["file_sync", "replace"] if os.name == "nt" else ["file_sync", "replace", "directory_sync"])


@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EAGAIN, errno.EDEADLK, errno.EIO])
def test_lock_retry_is_bounded_reports_its_directory_and_closes_the_descriptor(tmp_path, monkeypatch, error_number):
    attempts, sleeps = [], []
    store = JsonStore(tmp_path)
    def acquire(descriptor):
        attempts.append(descriptor)
        assert len(attempts) <= 4, "Lock retry exceeded its bounded attempts"
        raise OSError(error_number, "synthetic lock failure")
    monkeypatch.setattr(store, "_acquire_lock", acquire)
    monkeypatch.setattr(storage, "time", SimpleNamespace(sleep=sleeps.append))
    with pytest.raises(AlreadyRunning if error_number != errno.EIO else OSError) as error:
        store.__enter__()
    if error_number == errno.EIO:
        assert error.value.errno == errno.EIO and len(attempts) == 1 and sleeps == []
    else:
        assert error.value.directory == tmp_path
        assert str(error.value) == f"Datenverzeichnis wird bereits verwendet: {tmp_path}"
        assert len(attempts) == 4 and len(sleeps) == 3 and all(0 < delay <= 0.1 for delay in sleeps)
    assert store.lock is None
    with pytest.raises(OSError) as closed:
        os.fstat(attempts[0])
    assert closed.value.errno == errno.EBADF


def test_lock_can_be_acquired_after_the_last_transient_failure(tmp_path, monkeypatch):
    attempts, sleeps = [], []
    store = JsonStore(tmp_path)
    original = store._acquire_lock
    def acquire(descriptor):
        attempts.append(descriptor)
        assert len(attempts) <= 4, "Lock retry exceeded its bounded attempts"
        if len(attempts) < 4:
            raise OSError(errno.EACCES, "synthetic delayed release")
        original(descriptor)
    monkeypatch.setattr(store, "_acquire_lock", acquire)
    monkeypatch.setattr(storage, "time", SimpleNamespace(sleep=sleeps.append))
    with store as entered:
        assert entered is store and store.lock == attempts[-1]
    assert len(attempts) == 4 and len(sleeps) == 3 and store.lock is None


def test_exit_closes_descriptor_zero_and_repeating_exit_is_harmless(tmp_path, monkeypatch):
    closed = []
    proxy = SimpleNamespace(**vars(storage.os))
    proxy.close = closed.append
    monkeypatch.setattr(storage, "os", proxy)
    store = JsonStore(tmp_path)
    store.lock = 0  # fd 0 is valid when stdin was closed before the store opened
    store.__exit__()
    store.__exit__()
    assert closed == [0] and store.lock is None


def test_atomic_staging_stays_on_the_target_volume_when_system_temp_is_elsewhere(tmp_path, monkeypatch):
    alternate = tmp_path / "other-volume"
    alternate.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(alternate))
    proxy = SimpleNamespace(**vars(storage.os))
    original = storage.os.replace
    def replace(source, target):
        if Path(source).parent != Path(target).parent:
            raise OSError(errno.EXDEV, "synthetic different temporary volume")
        original(source, target)
    proxy.replace = replace
    monkeypatch.setattr(storage, "os", proxy)
    path = tmp_path / "config" / "settings.yaml"
    atomic_replace(path, "name: Grüße\n")
    assert path.read_bytes() == "name: Grüße\n".encode() and list(alternate.iterdir()) == []


@pytest.mark.parametrize("kind", ["atomic", "state"])
def test_utf8_is_preserved_even_on_a_machine_with_an_ascii_default_encoding(tmp_path, monkeypatch, kind):
    # Simulate a different OS default at the I/O boundary; explicit encodings keep real semantics.
    original_fdopen, original_open = storage.os.fdopen, Path.open
    proxy = SimpleNamespace(**vars(storage.os))
    def fdopen(descriptor, *args, **kwargs):
        kwargs["encoding"] = kwargs.get("encoding") or "ascii"
        kwargs["newline"] = kwargs.get("newline") if kwargs.get("newline") is not None else "\r\n"
        return original_fdopen(descriptor, *args, **kwargs)
    def open_path(path, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if path.name in {"state.json", "state.tmp"} and "b" not in mode:
            kwargs["encoding"] = kwargs.get("encoding") or "ascii"
            if "w" in mode:
                kwargs["newline"] = kwargs.get("newline") if kwargs.get("newline") is not None else "\r\n"
        return original_open(path, *args, **kwargs)
    proxy.fdopen = fdopen
    monkeypatch.setattr(storage, "os", proxy)
    monkeypatch.setattr(Path, "open", open_path)
    if kind == "atomic":
        path = tmp_path / "settings.yaml"
        atomic_replace(path, "name: Grüße\n")
        assert path.read_bytes() == "name: Grüße\n".encode()
    else:
        store = JsonStore(tmp_path)
        store.save("state", {"name": "Grüße"})
        assert store.load("state") == {"name": "Grüße"}
        assert "Grüße".encode() in (tmp_path / "state.json").read_bytes()
        assert b"\r" not in (tmp_path / "state.json").read_bytes()


def test_valid_standard_duration_and_duration_upper_bound_keep_the_complete_event():
    values = {"kind": "event", "start": datetime(2026, 11, 6, 9, tzinfo=UTC), "end": datetime(2026, 11, 6, 10, tzinfo=UTC)}
    standard = build_proposal(**values, end_origin="standard", default_duration_minutes=60)
    upper = build_proposal(**values, duration_minutes=60, duration_is_upper_bound=True)
    assert standard.default_duration_minutes == 60 and standard.end_origin == "standard"
    assert upper.duration_is_upper_bound and upper.duration_minutes == 60
    assert standard.start == upper.start == values["start"] and standard.end == upper.end == values["end"]


def test_a_timezone_object_without_an_offset_is_not_a_confirmed_instant():
    class NoOffset(tzinfo):
        def utcoffset(self, value): return None
    zone = NoOffset()
    with pytest.raises(ValidationError, match="Zeitgebundene Termine benötigen einen eindeutigen UTC-Offset"):
        build_proposal(kind="event", start=datetime(2026, 11, 6, 9, tzinfo=zone), end=datetime(2026, 11, 6, 10, tzinfo=zone))
    with pytest.raises(ValidationError, match="Zeitgebundene Aufgabenfristen benötigen einen eindeutigen UTC-Offset"):
        build_proposal(due=datetime(2026, 11, 6, 9, tzinfo=zone))


@pytest.mark.parametrize("field,classification", [("explicit_create_fallback_confirmed", "change"),
                                                  ("explicit_non_binding_create_confirmed", "non_binding")])
def test_public_revision_api_requires_explicit_deterministic_consent_for_special_creation(field, classification):
    item = build_proposal(kind="event", classification=classification, open_questions=["Neu anlegen?"],
                          start=datetime(2026, 11, 6, 9, tzinfo=UTC), end=datetime(2026, 11, 6, 10, tzinfo=UTC))
    delta = ProposalRevisionDelta(answered_question="Neu anlegen?", changes={field: True})
    with pytest.raises(ValueError, match="deterministische ausdrückliche Bestätigung"):
        apply_proposal_revision(item, delta)
    result = apply_proposal_revision(item, delta, allow_create_fallback=True)
    assert getattr(result, field) is True and result.status == "pending_confirmation" and result.open_questions == []
    assert result.version == item.version + 1 and result.classification == classification


def test_revision_cannot_reclassify_an_existing_change_as_new_but_can_edit_its_title():
    item = build_proposal(classification="change", open_questions=["Was ändern?"])
    with pytest.raises(ValueError) as error:
        apply_proposal_revision(item, ProposalRevisionDelta(answered_question="Was ändern?", changes={"classification": "new"}))
    assert str(error.value) == "Eine Terminänderung darf nicht als neuer Termin eingestuft werden"
    result = apply_proposal_revision(item, ProposalRevisionDelta(answered_question="Was ändern?", changes={"title": "Geändert"}))
    assert result.classification == "change" and result.title == "Geändert" and result.status == "needs_clarification"


def test_public_revision_composes_partial_time_facts_without_losing_or_replacing_a_confirmed_start():
    start, end = datetime(2026, 11, 6, 9, tzinfo=UTC), datetime(2026, 11, 6, 10, tzinfo=UTC)
    known = KnownTemporalFacts(date=start.date(), start_time=time(9))
    item = build_proposal(kind="event", known_temporal_facts=known, open_questions=["Wann beginnt der Termin?"])
    for changes in ({"title": "Neuer Titel"}, {"all_day": True}):
        revised = apply_proposal_revision(item, ProposalRevisionDelta(answered_question="Wann beginnt der Termin?", changes=changes))
        assert revised.known_temporal_facts == known
    first = apply_proposal_revision(item, ProposalRevisionDelta(answered_question="Wann beginnt der Termin?", changes={"start": start}))
    assert first.start is None and first.known_temporal_facts == KnownTemporalFacts(date=start.date(), start=start)
    assert first.open_questions == ["Wann endet der Termin?"]
    with pytest.raises(ValueError, match="Ein bestätigter Terminbeginn darf nicht verändert werden"):
        apply_proposal_revision(first, ProposalRevisionDelta(answered_question="Wann endet der Termin?",
                               changes={"start": end, "end": datetime(2026, 11, 6, 11, tzinfo=UTC)}))
    complete = apply_proposal_revision(first, ProposalRevisionDelta(answered_question="Wann endet der Termin?", changes={"end": end}))
    assert (complete.start, complete.end, complete.known_temporal_facts) == (start, end, None)
    assert complete.open_questions == [] and complete.status == "pending_confirmation" and complete.version == 3


def test_same_day_datetime_revision_is_not_confused_with_a_conflicting_date():
    day = date(2026, 11, 6)
    item = build_proposal(kind="event", open_questions=["Wann?"], temporal_fact=TemporalFact(normalized_date=day, status="resolved"))
    changes = {"start": datetime(2026, 11, 6, 9, tzinfo=UTC)}
    assert _revision_day(item, changes) is None and changes["start"].date() == day


@pytest.mark.parametrize("status", ["confirmed", "writing", "uncertain"])
def test_reconciliation_persists_the_real_receipt_and_does_not_repeat_an_existing_write(status):
    item, saved = build_proposal(status=status, version=7), []
    receipt = {"id": "found", "url": "https://synthetic.test/found"}
    class Writer:
        def reconcile(self, key):
            assert key == f"mailhelp:{item.source_mail_id}:{item.id}:v7"
            return receipt
        def create(self, *args): pytest.fail("An existing result must never be created again")
    result, actual = execute_confirmed(item, Writer(), saved.append)
    assert actual is receipt and saved == [result]
    assert (result.status, result.external_id, result.external_link, result.version) == ("created", "found", receipt["url"], 7)
    assert item.status == status


def test_store_creates_all_missing_parent_directories_and_peek_keeps_its_default(tmp_path):
    default = {"synthetic": "default"}
    with JsonStore(tmp_path / "one" / "two" / "data") as store:
        assert store.peek("absent", default) is default
        assert store.load("absent", default) is default
        assert store.names() == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits have no corresponding Windows ACL semantics")
def test_new_lock_files_are_private_even_with_a_permissive_umask(tmp_path):
    previous = os.umask(0)
    try:
        with JsonStore(tmp_path):
            assert stat.S_IMODE((tmp_path / ".lock").stat().st_mode) == 0o600
    finally:
        os.umask(previous)


def test_an_all_day_flag_cannot_erase_an_already_confirmed_clock_during_revision():
    start = datetime(2026, 11, 6, 9, tzinfo=UTC)
    item = build_proposal(kind="event", all_day=True, open_questions=["Wann endet der Termin?"],
                          known_temporal_facts=KnownTemporalFacts(date=start.date(), start=start))
    delta = ProposalRevisionDelta(answered_question="Wann endet der Termin?", changes={
        "all_day": False, "start": datetime(2026, 11, 6, 10, tzinfo=UTC),
        "end": datetime(2026, 11, 6, 11, tzinfo=UTC)})
    with pytest.raises(ValueError, match="Ein bestätigter Terminbeginn darf nicht verändert werden"):
        apply_proposal_revision(item, delta)
    assert item.known_temporal_facts.start == start and item.version == 1
