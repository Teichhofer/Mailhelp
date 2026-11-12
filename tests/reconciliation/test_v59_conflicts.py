"""5.9.2: contradicting source values are named, stored typed and chosen with one decision."""
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from mailhelp.domain.proposal import (
    ConflictVariant,
    FieldConflict,
    Proposal,
    ProposalRevisionChanges,
    ProposalRevisionDelta,
    apply_proposal_revision,
)
from mailhelp.domain.proposal_sources import ProposalReference, ProposalSource
from mailhelp.proposals import conflicts
from mailhelp.proposals.proposal_merge import merge_facts
from mailhelp.review.editing import ProposalEditPatch, edit_proposal

NOW = datetime(2030, 11, 20, 14, tzinfo=UTC)
END_QUESTION = "Wann endet der Termin?"


def source(number, *, subject="Elternabend", sent=True):
    return ProposalSource(mail_id=f"{number:024x}", proposal_id=f"p_{number}", subject=subject,
                          sent_at=NOW + timedelta(days=number) if sent else None, anchors=["thread"]).model_dump()


def event(number, **changes):
    values = {"id": f"p_{number}", "version": 1, "source_mail_id": f"{number:024x}", "kind": "event",
              "target": "calendar", "target_provider": "google", "title": "Elternabend", "evidence": "Beleg",
              "responsibility": "user", "certainty": "certain", "classification": "new", "start": NOW,
              "end": NOW + timedelta(hours=1), "status": "pending_confirmation", "sources": [source(number)]}
    return Proposal.model_validate({**values, **changes})


def task(number, **changes):
    return event(number, **{"kind": "task", "start": None, "end": None, "due": date(2030, 11, 25), **changes})


def test_regression_a_different_end_names_both_values_instead_of_the_field_key():
    """Regression 5.9.2: the question read "Widerspruch bei end: Angaben aus den Quellen vergleichen."."""
    merged = merge_facts(event(1), event(2, end=NOW + timedelta(hours=2, minutes=30)))
    assert merged.open_questions == ["Widerspruch bei der Endzeit: bisher 15:00 Uhr, laut Mail „Elternabend“ "
                                     "vom 22.11. 16:30 Uhr. Welche Endzeit soll gelten?"]
    assert merged.status == "needs_clarification" and merged.end == NOW + timedelta(hours=1)
    [conflict] = merged.field_conflicts
    assert (conflict.id, conflict.field, conflicts.label(conflict)) == ("interval-2", "interval", "Endzeit")
    assert [variant.origin for variant in conflict.variants] == ["current", "source"]
    assert conflict.variants[1].source == ProposalReference(mail_id=f"{2:024x}", proposal_id="p_2")
    assert conflict.variants[1].end == NOW + timedelta(hours=2, minutes=30)
    assert merge_facts(merged, event(2, end=NOW + timedelta(hours=2, minutes=30))) == merged


def test_start_and_end_form_one_interval_and_other_days_show_their_date():
    moved = merge_facts(event(1), event(2, start=NOW + timedelta(hours=2), end=NOW + timedelta(hours=3)))
    assert moved.open_questions[0].startswith("Widerspruch beim Zeitraum: bisher 14:00–15:00 Uhr, laut Mail")
    assert moved.open_questions[0].endswith("16:00–17:00 Uhr. Welcher Zeitraum soll gelten?")
    later = merge_facts(event(1), event(2, start=NOW + timedelta(days=1), end=NOW + timedelta(days=1, hours=1)))
    assert "bisher 20.11.2030, 14:00–15:00 Uhr" in later.open_questions[0]
    assert "21.11.2030, 14:00–15:00 Uhr" in later.open_questions[0]
    start_only = merge_facts(event(1, end=NOW + timedelta(hours=3)),
                             event(2, start=NOW + timedelta(hours=1), end=NOW + timedelta(hours=3)))
    assert start_only.open_questions[0].startswith("Widerspruch beim Beginn: bisher 14:00 Uhr")


def test_a_start_without_an_end_keeps_the_previous_duration():
    incoming = event(2, start=NOW + timedelta(hours=4), end=None, status="needs_clarification",
                     open_questions=[END_QUESTION])
    merged = merge_facts(event(1), incoming)
    variant = merged.field_conflicts[0].variants[1]
    assert (variant.start, variant.end, variant.derived_end) == (NOW + timedelta(hours=4), NOW + timedelta(hours=5),
                                                                  True)
    assert "18:00–19:00 Uhr (Dauer wie bisher)" in merged.open_questions[0]
    open_end = merge_facts(event(1, end=None, status="needs_clarification", open_questions=[END_QUESTION]), incoming)
    assert open_end.field_conflicts[0].variants[1].end is None
    assert "bisher 14:00 Uhr, laut Mail „Elternabend“ vom 22.11. 18:00 Uhr." in open_end.open_questions[-1]
    later_end = merge_facts(event(1, end=None, status="needs_clarification", open_questions=[END_QUESTION]),
                            event(2, start=NOW + timedelta(hours=4), end=NOW + timedelta(hours=5)))
    # The missing end is taken over from the source; only the start stays contested.
    assert later_end.end == NOW + timedelta(hours=5) and "Widerspruch beim Beginn" in later_end.open_questions[-1]


def test_a_value_the_user_set_is_named_as_such_and_location_and_link_are_compared():
    merged = merge_facts(event(1, location="Aula", protected_fields=["location"]),
                         event(2, location="Turnhalle", video_link="https://meet.example.org/raum/7"))
    assert merged.open_questions == [
        "Widerspruch beim Ort: von dir festgelegt „Aula“, laut Mail „Elternabend“ vom 22.11. „Turnhalle“. "
        "Welcher Ort soll gelten?"]
    linked = merge_facts(event(1, video_link="https://alt.example.org/a"),
                         event(2, video_link="https://meet.example.org/raum/7"))
    link = linked.field_conflicts[0]
    assert link.field == "video_link" and conflicts.button_text(link, link.variants[1]) == "meet.example.org"
    assert conflicts.button_text(link, link.variants[1].model_copy(update={"text": None})) == "keine Angabe"


def test_task_deadlines_conflict_as_dates_or_times():
    merged = merge_facts(task(1), task(2, due=date(2030, 11, 27)))
    assert merged.open_questions == ["Widerspruch bei der Fälligkeit: bisher 25.11.2030, laut Mail „Elternabend“ "
                                     "vom 22.11. 27.11.2030. Welche Fälligkeit soll gelten?"]
    timed = merge_facts(task(1, due=NOW), task(2, due=NOW + timedelta(hours=2)))
    assert "bisher 20.11.2030, 14:00 Uhr" in timed.open_questions[0]
    conflict = timed.field_conflicts[0]
    assert conflicts.value_text(conflict, conflict.variants[0].model_copy(update={"due": None})) == "keine"


def test_further_values_extend_the_conflict_until_three_then_ask_for_an_edit():
    first = merge_facts(task(1), task(2, due=date(2030, 11, 27)))
    second = merge_facts(first, task(3, due=date(2030, 11, 28), sources=[source(3, subject="", sent=True)]))
    conflict = second.field_conflicts[0]
    assert [variant.id for variant in conflict.variants] == ["a", "b", "c"] and conflict.id == "due-2"
    assert second.open_questions == [conflict.question] and "laut Mail vom 23.11. 28.11.2030" in conflict.question
    assert merge_facts(second, task(4, due=date(2030, 11, 27))).field_conflicts == second.field_conflicts
    fourth = merge_facts(second, task(4, due=date(2030, 11, 29)))
    assert fourth.field_conflicts == []
    assert fourth.open_questions == ["Mehrere widersprüchliche Angaben bei der Fälligkeit: bitte den Vorschlag "
                                     "bearbeiten."]


def test_sources_without_subject_or_date_and_partial_time_facts_stay_readable():
    unnamed = merge_facts(task(1), task(2, due=date(2030, 11, 27), sources=[source(2, subject="", sent=False)]))
    assert "laut neuer Mail 27.11.2030" in unnamed.open_questions[0]
    unknown = merge_facts(task(1), task(1, due=date(2030, 11, 27)))
    assert unknown.field_conflicts[0].variants[1].source is None
    partial = {"start": None, "end": None, "status": "needs_clarification", "open_questions": ["Wann beginnt der Termin?"]}
    facts = merge_facts(event(1, known_temporal_facts={"date": date(2030, 11, 20), "start_time": time(18)}, **partial),
                        event(2, known_temporal_facts={"date": date(2030, 11, 21)}, **partial))
    assert ("Widerspruch bei den Zeitangaben: bisher 20.11.2030, 18:00 Uhr, laut neuer Mail 21.11.2030. "
            "Bitte den Termin bearbeiten.") in facts.open_questions
    assert conflicts.temporal_facts_question(None, facts.known_temporal_facts.model_copy(
        update={"date": None, "start_time": None, "start": NOW})).startswith(
        "Widerspruch bei den Zeitangaben: bisher keine Angabe, laut neuer Mail 20.11.2030, 14:00 Uhr.")


def test_value_texts_cover_all_day_open_and_overnight_intervals_in_the_configured_zone():
    def conflict(*variants):
        return FieldConflict(id="interval-1", field="interval", question="?", variants=[
            ConflictVariant(id=ident, origin="current", **values) for ident, values in zip("abc", variants, strict=False)])
    days = conflict({"start": date(2030, 11, 20), "end": date(2030, 11, 21)},
                    {"start": date(2030, 11, 20), "end": date(2030, 11, 23)})
    assert conflicts.value_text(days, days.variants[0]) == "20.11.2030, ganztägig"
    assert conflicts.value_text(days, days.variants[1]) == "20.11.2030 – 22.11.2030, ganztägig"
    late = conflict({"start": NOW, "end": NOW + timedelta(hours=1)},
                    {"start": NOW + timedelta(hours=9), "end": NOW + timedelta(hours=12)}, {"start": None})
    assert conflicts.value_text(late, late.variants[1]) == "20.11.2030, 23:00 Uhr – 21.11.2030, 02:00 Uhr"
    assert conflicts.value_text(late, late.variants[2]) == "ohne Beginn"
    half = conflict({"start": NOW, "end": None}, {"start": NOW + timedelta(hours=1), "end": NOW + timedelta(hours=2)})
    assert conflicts.value_text(half, half.variants[0]) == "14:00 Uhr (Ende offen)"
    zone = ZoneInfo("Europe/Berlin")
    assert conflicts.value_text(late, late.variants[0], zone) == "20.11.2030, 15:00–16:00 Uhr"
    assert conflicts.button_text(late, late.variants[1]) == "20.11.2030, 23:00 Uhr – 21.11.2030, 02:…"
    place = FieldConflict(id="location-1", field="location", question="?", variants=[
        ConflictVariant(id="a", origin="current", text="Aula"), ConflictVariant(id="b", origin="source", text="x" * 50)])
    assert conflicts.button_text(place, place.variants[1]) == "x" * 39 + "…"
    assert conflicts.button_text(place, place.variants[0]) == "Aula"


def test_choosing_a_variant_revises_without_authorizing_and_protects_the_field():
    merged = merge_facts(event(1, explicit_duplicate_create_confirmed_version=1),
                         event(2, end=NOW + timedelta(hours=2, minutes=30)))
    chosen = conflicts.choose(merged, "interval-2", "b")
    assert chosen.end == NOW + timedelta(hours=2, minutes=30) and chosen.version == merged.version + 1
    assert chosen.open_questions == [] and chosen.field_conflicts == [] and chosen.status == "pending_confirmation"
    assert {"start", "end"} <= set(chosen.protected_fields) and chosen.end_origin == "manual"
    assert chosen.explicit_duplicate_create_confirmed_version is None and chosen.confirmed_web_actor is None
    kept = conflicts.choose(merged, "interval-2", "a")
    assert kept.end == merged.end and kept.status == "pending_confirmation"
    for wrong in (("interval-9", "a"), ("interval-2", "c")):
        with pytest.raises(conflicts.ConflictChoiceError, match="nicht mehr offen"):
            conflicts.choose(merged, *wrong)
    with pytest.raises(conflicts.ConflictChoiceError, match="Nur offene"):
        conflicts.choose(chosen.model_copy(update={"status": "rejected"}), "interval-2", "a")


def test_choices_for_deadlines_places_open_ends_and_impossible_values():
    due = merge_facts(task(1), task(2, due=date(2030, 11, 27)))
    assert conflicts.choose(due, "due-2", "b").due == date(2030, 11, 27)
    place = merge_facts(event(1, location="Aula"), event(2, location="Turnhalle", end=NOW + timedelta(hours=2)))
    chosen = conflicts.choose(place, "location-2", "b")
    assert chosen.location == "Turnhalle" and chosen.status == "needs_clarification"
    assert [item.field for item in chosen.field_conflicts] == ["interval"]
    open_end = merge_facts(event(1, end=None, status="needs_clarification", open_questions=[END_QUESTION]),
                           event(2, start=NOW + timedelta(hours=4), end=None, status="needs_clarification",
                                 open_questions=[END_QUESTION]))
    ident = open_end.field_conflicts[0].id
    assert END_QUESTION in conflicts.choose(open_end, ident, "b").open_questions
    without = open_end.model_copy(update={"open_questions": [q for q in open_end.open_questions if q != END_QUESTION]})
    assert conflicts.choose(without, ident, "b").open_questions == [END_QUESTION]
    broken = open_end.model_copy(update={"field_conflicts": [open_end.field_conflicts[0].model_copy(update={
        "variants": [open_end.field_conflicts[0].variants[0],
                     ConflictVariant(id="b", origin="source", start=NOW, end=NOW - timedelta(hours=1))]})]})
    with pytest.raises(conflicts.ConflictChoiceError, match="keinen gültigen"):
        conflicts.choose(broken, ident, "b")


def test_a_conflict_lives_only_with_its_open_question():
    merged = merge_facts(task(1), task(2, due=date(2030, 11, 27)))
    conflict = merged.field_conflicts[0]
    dumped = merged.model_dump()
    assert Proposal.model_validate({**dumped, "open_questions": []}).field_conflicts == []
    built = Proposal(**{**dict(merged), "field_conflicts": [conflict]})
    assert built.field_conflicts == [conflict]
    assert Proposal(**{**dict(merged), "open_questions": ["Andere Frage?"], "status": "needs_clarification",
                       "field_conflicts": [conflict]}).field_conflicts == []


def test_a_direct_edit_or_answer_of_the_field_settles_its_conflict():
    merged = merge_facts(event(1, location="Aula"),
                         event(2, location="Turnhalle", end=NOW + timedelta(hours=2)))
    edited = edit_proposal(merged, ProposalEditPatch(location="Bühne"), "UTC", {"calendar"})
    assert edited.location == "Bühne" and [item.field for item in edited.field_conflicts] == ["interval"]
    assert not any(question.startswith("Widerspruch beim Ort") for question in edited.open_questions)
    interval_question = merged.field_conflicts[0].question
    answered = apply_proposal_revision(merged, ProposalRevisionDelta(
        answered_question=interval_question, changes=ProposalRevisionChanges(location="Bühne")))
    assert answered.field_conflicts == [] and answered.status == "pending_confirmation"
    place_question = merged.field_conflicts[1].question
    same = apply_proposal_revision(merged, ProposalRevisionDelta(
        answered_question=place_question, changes=ProposalRevisionChanges(location="Bühne")))
    assert [item.field for item in same.field_conflicts] == ["interval"]


def test_all_day_against_timed_and_a_fixed_day_name_both_times():
    whole_day = event(2, all_day=True, start=date(2030, 11, 21), end=date(2030, 11, 22))
    merged = merge_facts(event(1), whole_day)
    assert merged.open_questions == ["Ganztägige und zeitgebundene Angaben widersprechen sich: bisher 20.11.2030, "
                                     "14:00–15:00 Uhr, laut neuer Mail 21.11.2030, ganztägig. Bitte den Termin "
                                     "bearbeiten."]
    fixed = event(1, start=None, end=None, status="needs_clarification", open_questions=["Wann beginnt der Termin?"],
                  known_temporal_facts={"date": date(2030, 11, 20)}, protected_fields=["known_temporal_facts"])
    moved = merge_facts(fixed, event(2, start=NOW + timedelta(days=2), end=NOW + timedelta(days=2, hours=1)))
    assert ("Widerspruch zum von dir festgelegten Datum oder Beginn: bisher 20.11.2030, laut neuer Mail "
            "22.11.2030, 14:00–15:00 Uhr. Bitte den Termin bearbeiten.") in moved.open_questions
