"""Proposal revisions: allowed fields, temporal facts and token limits."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from mailhelp.config import OutputTokenRetry
from mailhelp.domain.proposal import (
    Proposal,
    ProposalRevisionChanges,
    ProposalRevisionDelta,
    ProposalStatus,
    apply_proposal_revision,
)
from mailhelp.domain.revision_errors import ContradictoryRevision
from mailhelp.llm.openrouter import InvalidJson, ProviderResponseInvalid
from mailhelp.processing.analysis import (
    Analyzer,
    LlmInvalidJson,
    LlmProviderResponseInvalid,
    LlmSchemaValidationFailed,
    validate_revision_successor,
)
from tests.fakes.shared_core import prompt_config, proposal
from tests.fakes.shared_services import (
    FakeCompleter,
    RetrySequence,
)


def test_analyzer_revises_proposal_with_separate_inputs_and_retries():
    original=proposal(open_questions=["Welcher Titel?"])
    valid={"answered_question":"Welcher Titel?","changes":{"title":"Neu"}}
    client=FakeCompleter([{"answered_question":"Welcher Titel?","changes":{"id":"other"}},valid])
    call,revised=Analyzer(client,prompt_config(),1).revise_proposal(original,"Welcher Titel?","Neu")
    assert call=="2" and revised.title=="Neu" and original.title=="Tun"
    assert client.calls==2

    class Malformed:
        def __init__(self, error): self.error=error
        def complete(self, *args, **kwargs): raise self.error
    with pytest.raises(LlmProviderResponseInvalid) as provider_error:
        Analyzer(Malformed(ProviderResponseInvalid("message_missing")),prompt_config(),1).revise_proposal(original,"Welcher Titel?","a")
    assert provider_error.value.step == "proposal_revision"
    with pytest.raises(LlmInvalidJson) as json_error:
        Analyzer(Malformed(InvalidJson()),prompt_config(),1).revise_proposal(original,"Welcher Titel?","a")
    assert json_error.value.step == "proposal_revision"

    # The application owns the question identity and replaces an untrusted LLM
    # value before applying the otherwise strictly validated delta.
    _, corrected = Analyzer(FakeCompleter([
        {"answered_question":"Autorisierte Antwort","changes":{"title":"Neu"}}
    ]), prompt_config()).revise_proposal(original, "Welcher Titel?", "Autorisierte Antwort")
    assert corrected.title == "Neu"
    assert corrected.open_questions == []

    failures=[None,
              {"answered_question":"Welcher Titel?","changes":{"status":"created"}},
              {"answered_question":"Welcher Titel?","changes":{"title":""}}]
    for invalid in failures:
        with pytest.raises(LlmSchemaValidationFailed):
            Analyzer(FakeCompleter([invalid,invalid]),prompt_config()).revise_proposal(original,"Welcher Titel?","a")

    class CapturingCompleter:
        def __init__(self): self.payload=None
        def complete(self, model, parameters, system, payload, **_metadata):
            self.payload=payload
            return "call",valid
    capturing=CapturingCompleter()
    Analyzer(capturing,prompt_config()).revise_proposal(original,"Welcher Titel?","Autorisierte Antwort")
    assert "id" not in capturing.payload["proposal_fields"]
    assert capturing.payload["question"]=="Welcher Titel?"
    assert capturing.payload["normalized_answer"]=="Autorisierte Antwort"
    assert "status" not in capturing.payload["allowed_changes"]


def test_proposal_revision_prompt_covers_date_schema_and_output_budget():
    step = yaml.safe_load(Path("prompts.yaml").read_text(encoding="utf-8"))["prompts"]["proposal_revision"]

    assert step["parameters"] == {"temperature": 0.0, "max_tokens": 4000}
    assert step["output_token_retry"]["parameters"]["max_tokens"] == 4000
    prompt = step["system_prompt"]
    assert "reines Kalenderdatum" in prompt
    assert "all_day=true" in prompt
    assert "ISO-8601-Zeitpunkte mit eindeutigem UTC-Offset" in prompt
    assert "Erfinde oder errate keinen UTC-Offset" in prompt
    flat_prompt = " ".join(prompt.split())
    assert '"Z" und "+00:00" bedeuten ausdrücklich UTC' in flat_prompt
    assert "proposal_fields.start, proposal_fields.end oder known_temporal_facts.start" in flat_prompt
    assert 'gib "changes": {} aus' in prompt
    assert "berechnet die Anwendung lokal" in prompt
    assert "enthält niemals normalized_answer" in step["output_token_retry"]["system_prompt"]
    interpretation = yaml.safe_load(Path("prompts.yaml").read_text(
        encoding="utf-8"))["prompts"]["telegram_answer_interpretation"]
    assert '"JJJJ-MM-TT HH:MM"' in interpretation["system_prompt"]
    assert interpretation["parameters"]["max_tokens"] == 4000
    assert interpretation["output_token_retry"]["parameters"]["max_tokens"] == 4000
    assert "drei Feldern" in interpretation["output_token_retry"]["system_prompt"]
    assert "change_fields" not in interpretation["output_token_retry"]


def test_telegram_answer_interpretation_and_clarification_use_separate_fields():
    original = proposal(open_questions=["Welches Datum?"])
    interpreting = RetrySequence([{
        "usable": True, "normalized_answer": "1. Oktober 2026", "reason": "Datum erkannt"
    }])
    _, interpreted = Analyzer(interpreting, prompt_config()).interpret_telegram_answer(
        original, "Welches Datum?", "am ersten Oktober")
    assert interpreted.normalized_answer == "1. Oktober 2026"
    assert interpreting.payloads[0] == {
        "proposal_fields": {"due": None}, "temporal_fact": None,
        "question": "Welches Datum?", "authorized_answer": "am ersten Oktober",
    }

    clarifying = RetrySequence([{"message": "Bitte nenne das Datum im Format TT.MM.JJJJ."}])
    _, clarification = Analyzer(clarifying, prompt_config()).clarify_telegram_answer(
        "Welches Datum?", "irgendwann", "kein eindeutiges Datum",
        current_date=date(2026, 9, 25))
    assert clarification.message.startswith("Bitte nenne")
    assert clarifying.payloads[0] == {
        "question": "Welches Datum?", "authorized_answer": "irgendwann",
        "interpretation_reason": "kein eindeutiges Datum",
        "context": {"current_date": "2026-09-25"},
    }
    without_context = RetrySequence([{"message": "Bitte nenne das Datum."}])
    Analyzer(without_context, prompt_config()).clarify_telegram_answer(
        "Welches Datum?", "irgendwann", "kein eindeutiges Datum")
    assert "context" not in without_context.payloads[0]


def test_telegram_answer_interpretation_is_deterministic_or_uses_one_changed_token_fallback():
    original = proposal(open_questions=["Welches Datum?"])
    for question, answer, normalized in (
            ("Welches Datum?", "01.10.2026", "2026-10-01"),
            ("Welche Uhrzeit?", "9 Uhr", "09:00"),
            ("Wann?", "9:00 bis 10:30", "09:00 bis 10:30")):
        deterministic = RetrySequence([])
        call_id, interpreted = Analyzer(
            deterministic, prompt_config()).interpret_telegram_answer(
                original, question, answer)
        assert call_id == "deterministic"
        assert interpreted.normalized_answer == normalized
        assert deterministic.payloads == []

    for question in (
            "Ist die extrahierte Information sicher belegt?",
            "Ist die Nutzerin oder der Nutzer für diesen Eintrag zuständig?",
    ):
        for answer, normalized in (
                ("Ja", "Ja"), ("  NEIN! ", "Nein"),
                ("Es passt alles", "Ja"), ("Alles passt.", "Ja")):
            deterministic = RetrySequence([])
            call_id, interpreted = Analyzer(
                deterministic, prompt_config()).interpret_telegram_answer(
                    original, question, answer)
            assert call_id == "deterministic"
            assert interpreted.usable
            assert interpreted.normalized_answer == normalized
            assert deterministic.payloads == []

    cfg = prompt_config()
    cfg.prompts["telegram_answer_interpretation"].parameters = {
        "temperature": 0.0, "max_tokens": 500}
    cfg.prompts["telegram_answer_interpretation"].output_token_retry = OutputTokenRetry(
        system_prompt="Nur usable, normalized_answer und reason als JSON.",
        parameters={"max_tokens": 180})
    client = RetrySequence([
        ProviderResponseInvalid("output_token_limit"),
        {"usable": True, "normalized_answer": "1. Oktober", "reason": "eindeutig"},
    ])
    result = Analyzer(client, cfg, provider_retries=3).interpret_telegram_answer(
        original, "Welches Datum?", "am ersten Oktober")[1]
    assert result.usable
    assert client.systems == [
        cfg.prompts["telegram_answer_interpretation"].system_prompt,
        "Nur usable, normalized_answer und reason als JSON.",
    ]
    assert client.parameters == [
        {"temperature": 0.0, "max_tokens": 500},
        {"temperature": 0.0, "max_tokens": 500},
    ]
    assert client.payloads[1] == client.payloads[0]

    exhausted = RetrySequence([
        ProviderResponseInvalid("output_token_limit"),
        ProviderResponseInvalid("output_token_limit"),
    ])
    with pytest.raises(LlmProviderResponseInvalid, match="output_token_limit"):
        Analyzer(exhausted, cfg, provider_retries=3).interpret_telegram_answer(
            original, "Welches Datum?", "am ersten Oktober")
    assert len(exhausted.payloads) == 2

    invalid_date = RetrySequence([{
        "usable": False, "normalized_answer": None, "reason": "ungültiges Datum"}])
    assert not Analyzer(invalid_date, prompt_config()).interpret_telegram_answer(
        original, "Welches Datum?", "31.02.2026")[1].usable


@pytest.mark.parametrize("original, changes, expected", [
    (proposal(open_questions=["Welche Frist?"]),
     {"due":"2026-10-01T17:00:00+02:00"}, "2026-10-01T17:00:00+02:00"),
    (proposal(kind="event",open_questions=["Wann?"],start=None,end=None),
     {"start":"2026-10-02T09:00:00+02:00","end":"2026-10-02T10:00:00+02:00"},
     "2026-10-02T09:00:00+02:00"),
])
def test_analyzer_revision_validates_task_deadlines_and_event_times(original, changes, expected):
    question=original.open_questions[0]
    raw={"answered_question":question,"changes":changes}
    revised=Analyzer(FakeCompleter([raw]),prompt_config()).revise_proposal(original,question,"Antwort")[1]
    value=revised.due if revised.kind.value=="task" else revised.start
    assert value.isoformat()==expected


def test_revision_token_limit_uses_reduced_route_and_can_exhaust():
    cfg=prompt_config()
    cfg.prompts["proposal_revision"].output_token_retry=OutputTokenRetry(
        system_prompt="short", parameters={"max_tokens": 50}, change_fields=["title"])
    original=proposal(open_questions=["Titel?"])
    client=RetrySequence([ProviderResponseInvalid("output_token_limit"),
                          {"answered_question":"Titel?","changes":{"title":"Kurz"}}])
    revised=Analyzer(client,cfg,provider_retries=0).revise_proposal(original,"Titel?","Kurz")[1]
    assert revised.title == "Kurz"
    assert client.payloads[1]["proposal_fields"] == {"title":"Tun"}

    exhausted=RetrySequence([ProviderResponseInvalid("output_token_limit"),
                             ProviderResponseInvalid("output_token_limit")])
    with pytest.raises(LlmProviderResponseInvalid, match="output_token_limit"):
        Analyzer(exhausted,cfg,provider_retries=0).revise_proposal(original,"Titel?","Kurz")

    with pytest.raises(ValueError, match="nicht offen"):
        Analyzer(FakeCompleter([]),cfg).revise_proposal(original,"Andere?","x")
    with pytest.raises(ValueError, match="nicht offen"):
        apply_proposal_revision(original, ProposalRevisionDelta(
            answered_question="Andere?", changes={"title":"x"}))

    with pytest.raises(ValidationError):
        OutputTokenRetry(system_prompt="x", parameters={"messages": []}, change_fields=["title"])

    invalid=original.model_copy(update={"id":"other","version":2})
    with pytest.raises(ValueError,match="Revisionsidentität"):
        validate_revision_successor(original,invalid)

    class Logged(FakeCompleter):
        class Log:
            def __init__(self): self.events=[]
            def event(self,*args,**kwargs): self.events.append((args,kwargs))
        def __init__(self,values):
            super().__init__(values)
            self.logger=self.Log()
    logged=Logged([{"answered_question":"Titel?","changes":{"title":"Neu"}}])
    Analyzer(logged,cfg).revise_proposal(original,"Titel?","Neu")
    assert logged.logger.events[0][0][2] == "proposal_revision_delta_applied"


def test_regression_revision_rejects_changes_outside_allowed_fields():
    """Regression 2026-10-08 (B1): a date answer changed the responsibility.

    The provider returned ``{"responsibility": "unclear"}`` although only
    ``start``, ``end`` and ``all_day`` were allowed, and it was applied.
    """
    question = "Welches konkrete Datum ist mit „Morgen oder am Mittwoch“ gemeint?"
    original = proposal(kind="event", status="needs_clarification",
                        open_questions=[question])
    outside = {"answered_question": question, "changes": {"responsibility": "unclear"}}
    with pytest.raises(LlmSchemaValidationFailed):
        Analyzer(FakeCompleter([outside, outside]), prompt_config()).revise_proposal(
            original, question, "06.10.2026 oder 07.10.2026")

    # The violation is reported to the model like any other validation error,
    # and an allowed delta from the repair attempt is accepted unchanged.
    client = RetrySequence([
        {"answered_question": question,
         "changes": {"responsibility": "user", "start": "2026-10-07", "all_day": True}},
        {"answered_question": question, "changes": {"start": "2026-10-07", "all_day": True}},
    ])
    revised = Analyzer(client, prompt_config()).revise_proposal(original, question, "2026-10-07")[1]
    assert "responsibility" in client.payloads[1]["previous_validation_error"]
    assert revised.responsibility == original.responsibility
    assert revised.start == date(2026, 10, 7)


def test_revision_payload_carries_resolved_temporal_fact_read_only():
    base = proposal(open_questions=["Welches Datum?"]).model_dump()
    original = Proposal.model_validate({**base, "temporal_fact": {
        "raw_text": "21. Oktober", "normalized_date": "2026-10-21",
        "year_source": "mail_context", "status": "resolved"}})
    client = RetrySequence([{"answered_question": "Welches Datum?",
                             "changes": {"due": "2026-10-21"}}])
    Analyzer(client, prompt_config()).revise_proposal(original, "Welches Datum?", "21.10.26")
    assert client.payloads[0]["proposal_fields"]["temporal_fact"]["normalized_date"] == "2026-10-21"


def test_revision_payload_preserves_known_start_as_read_only_context():
    original = proposal(
        kind="event", status="needs_clarification",
        open_questions=["Wann endet der Termin?"],
        known_temporal_facts={
            "date": "2026-10-09", "start": "2026-10-09T19:00:00+02:00"})
    client = RetrySequence([ProviderResponseInvalid("output_token_limit"), {
        "answered_question": "Wann endet der Termin?",
        "changes": {"end": "2026-10-09T21:00:00+02:00"}}])
    cfg = prompt_config()
    cfg.prompts["proposal_revision"].output_token_retry = OutputTokenRetry(
        system_prompt="short", parameters={"max_tokens": 4000}, change_fields=["end"])

    revised = Analyzer(client, cfg, provider_retries=0).revise_proposal(
        original, "Wann endet der Termin?", "2026-10-09 21:00")[1]

    assert client.payloads[0]["proposal_fields"]["known_temporal_facts"] == {
        "date": "2026-10-09", "start": "2026-10-09T19:00:00+02:00"}
    assert client.payloads[1]["proposal_fields"]["known_temporal_facts"] == {
        "date": "2026-10-09", "start": "2026-10-09T19:00:00+02:00"}
    assert revised.start.isoformat() == "2026-10-09T19:00:00+02:00"
    assert revised.end.isoformat() == "2026-10-09T21:00:00+02:00"


def test_revision_accepts_date_only_all_day_start_with_known_date():
    original = proposal(
        kind="event", status="needs_clarification", all_day=False,
        open_questions=["Wann beginnt der Termin?", "Wann endet der Termin?"],
        known_temporal_facts={"date": "2026-11-26"},
    )
    client = RetrySequence([{
        "answered_question": "26.11.26 Ganztags",
        "changes": {"start": "2026-11-26", "all_day": True},
    }])

    revised = Analyzer(client, prompt_config()).revise_proposal(
        original, "Wann beginnt der Termin?", "26.11.26 Ganztags"
    )[1]

    assert revised.start == date(2026, 11, 26)
    assert revised.all_day is True
    assert revised.known_temporal_facts is None
    assert revised.open_questions == ["Wann endet der Termin?"]


def test_revision_rejects_change_away_from_resolved_temporal_fact():
    base = proposal(open_questions=["Welches Datum?"]).model_dump()
    original = Proposal.model_validate({**base, "temporal_fact": {
        "raw_text": "21. Oktober", "normalized_date": "2026-10-21",
        "year_source": "mail_context", "status": "resolved"}})
    with pytest.raises(ValueError, match="validierten Datum 2026-10-21"):
        apply_proposal_revision(original, ProposalRevisionDelta(
            answered_question="Welches Datum?", changes={"due": "2110-10-21"}))


def test_change_revision_cannot_authorize_or_disguise_a_create_fallback():
    question = "Welcher bestehende Eintrag soll geändert werden?"
    original = proposal(classification="change", status="needs_clarification",
                        open_questions=[question])
    with pytest.raises(ValueError, match="ausdrückliche Bestätigung"):
        apply_proposal_revision(original, ProposalRevisionDelta(
            answered_question=question,
            changes={"explicit_create_fallback_confirmed": True}))
    with pytest.raises(ValueError, match="nicht als neuer Termin"):
        apply_proposal_revision(original, ProposalRevisionDelta(
            answered_question=question, changes={"classification": "new"}))

    non_binding_question = (
        "Soll der nicht bindende Hinweis dennoch als neuer Eintrag angelegt werden?"
    )
    non_binding = proposal(
        classification="non_binding", status="needs_clarification",
        open_questions=[non_binding_question],
    )
    with pytest.raises(ValueError, match="deterministische ausdrückliche Bestätigung"):
        apply_proposal_revision(non_binding, ProposalRevisionDelta(
            answered_question=non_binding_question,
            changes={"explicit_non_binding_create_confirmed": True},
        ))


def test_partial_event_revision_promotes_start_to_known_fact():
    original = proposal(kind="event", status="needs_clarification",
                        open_questions=["Wann beginnt der Termin?"],
                        known_temporal_facts={"date": "2026-10-21"})
    revised = apply_proposal_revision(original, ProposalRevisionDelta(
        answered_question="Wann beginnt der Termin?",
        changes={"start": "2026-10-21T12:00:00+02:00"}))
    assert revised.start is None
    assert revised.known_temporal_facts.start.isoformat() == "2026-10-21T12:00:00+02:00"
    assert revised.open_questions == ["Wann endet der Termin?"]
    completed = apply_proposal_revision(revised, ProposalRevisionDelta(
        answered_question="Wann endet der Termin?",
        changes={"end": "2026-10-21T13:00:00+02:00"}))
    assert completed.known_temporal_facts is None
    assert completed.start.isoformat() == "2026-10-21T12:00:00+02:00"
    assert completed.end.isoformat() == "2026-10-21T13:00:00+02:00"
    unchanged = apply_proposal_revision(
        original.model_copy(update={"open_questions": ["Welcher Titel?"]}),
        ProposalRevisionDelta(answered_question="Welcher Titel?",
                              changes={"title": "Neuer Titel"}))
    assert unchanged.known_temporal_facts == original.known_temporal_facts


@pytest.mark.parametrize("end", [
    "2026-10-09T23:00:00+02:00",
    "2026-10-10T01:00:00+02:00",
])
def test_event_revision_accepts_same_or_immediately_following_end_day(end):
    original = proposal(kind="event", status="needs_clarification",
                        open_questions=["Wann endet der Termin?"],
                        known_temporal_facts={
                            "date": "2026-10-09",
                            "start": "2026-10-09T22:00:00+02:00"})
    revised = apply_proposal_revision(original, ProposalRevisionDelta(
        answered_question=original.open_questions[0], changes={"end": end}))
    assert revised.start.isoformat() == "2026-10-09T22:00:00+02:00"
    assert revised.end.isoformat() == end


@pytest.mark.parametrize("changes", [
    {"end": "2026-10-09T22:00:00+02:00"},
    {"end": "2026-10-09T21:00:00+02:00"},
    {"end": "2026-10-11T01:00:00+02:00"},
    {"start": "2026-10-09T21:00:00+02:00", "end": "2026-10-09T23:00:00+02:00"},
    {"start": "2026-10-10T22:00:00+02:00", "end": "2026-10-10T23:00:00+02:00"},
])
def test_event_revision_rejects_invalid_end_or_changed_confirmed_start(changes):
    original = proposal(kind="event", status="needs_clarification",
                        open_questions=["Wann endet der Termin?"],
                        known_temporal_facts={
                            "date": "2026-10-09",
                            "start": "2026-10-09T22:00:00+02:00"})
    with pytest.raises(ValueError):
        apply_proposal_revision(original, ProposalRevisionDelta(
            answered_question=original.open_questions[0], changes=changes))


def test_all_day_revision_does_not_allow_a_timed_following_day_end():
    original = proposal(kind="event", all_day=True, status="needs_clarification",
                        open_questions=["Wann endet der Termin?"],
                        temporal_fact={"raw_text": "09.10.2026",
                                       "normalized_date": "2026-10-09",
                                       "year_source": "explicit_mail", "status": "resolved"})
    with pytest.raises(ValueError, match="validierten Datum"):
        apply_proposal_revision(original, ProposalRevisionDelta(
            answered_question=original.open_questions[0],
            changes={"end": "2026-10-10T01:00:00+02:00"}))


def test_revision_successor_keeps_confirmed_start_but_allows_next_day_end():
    original = proposal(kind="event", status="needs_clarification",
                        open_questions=["Wann endet der Termin?"],
                        start="2026-10-09T22:00:00+02:00", end=None,
                        temporal_fact={"raw_text": "09.10.2026",
                                       "normalized_date": "2026-10-09",
                                       "year_source": "explicit_mail", "status": "resolved"})
    revised = apply_proposal_revision(original, ProposalRevisionDelta(
        answered_question=original.open_questions[0],
        changes={"end": "2026-10-10T01:00:00+02:00"}))
    assert validate_revision_successor(original, revised) == revised
    changed = revised.model_copy(update={"start": revised.start.replace(hour=21)})
    with pytest.raises(ContradictoryRevision, match="bestätigter Terminbeginn"):
        validate_revision_successor(original, changed)

@pytest.mark.parametrize(("kind","question","expected"), [
    ("task","Ist die Person zuständig?",["responsibility"]),
    ("task","Ist das sicher belegt?",["certainty"]),
    ("task","Wie wird der Widerspruch aufgelöst?",["certainty"]),
    ("task","Welcher bestehende Eintrag?",["classification"]),
    ("event","Wann beginnt es?",["start","end","all_day"]),
    ("task","Welche Frist gilt?",["due"]),
    ("task","Welcher Titel?",["title"]),
    ("task","Welche Beschreibung?",["description"]),
    ("event","Welcher Ort?",["location"]),
    ("event","Welcher Video-Link?",["video_link"]),
    ("task","Welches Zielprojekt?",["target"]),
    ("task","Bitte beliebig ändern",list(ProposalRevisionChanges.model_fields)),
])
def test_revision_context_is_limited_to_the_concrete_question(kind,question,expected):
    item=proposal(kind=kind,open_questions=[question],
                  start=None if kind == "event" else None,
                  end=None if kind == "event" else None)
    assert Analyzer._revision_fields(item,question) == expected


def test_local_delta_apply_derives_every_invariant_question():
    import mailhelp.domain.proposal as models
    event=proposal(kind="event",open_questions=["Änderung?"],start=None,end=None,
                   responsibility="other",certainty="contradictory",
                   classification="recurring")
    questions=models.required_revision_questions(event)
    assert any("beginnt" in value for value in questions)
    assert any("endet" in value for value in questions)
    assert any("zuständig" in value for value in questions)
    assert any("Widerspruch" in value for value in questions)
    assert any("Wiederkehrende" in value for value in questions)

    for classification in ("non_binding","already_completed","change",
                           "cancellation","unsupported"):
        item=proposal(open_questions=["x"],classification=classification,
                      status="needs_clarification")
        assert models.required_revision_questions(item)
    uncertain=proposal(open_questions=["x"],certainty="uncertain",
                       status="needs_clarification")
    assert "sicher belegt" in models.required_revision_questions(uncertain)[0]

    partial=apply_proposal_revision(
        proposal(kind="event",open_questions=["Wann?"],start=None,end=None),
        ProposalRevisionDelta(answered_question="Wann?",changes={
            "start":"2026-10-02T09:00:00+02:00"}))
    assert partial.version == 2 and partial.status == ProposalStatus.NEEDS_CLARIFICATION
    assert partial.open_questions == ["Wann endet der Termin?"]
    duplicate=apply_proposal_revision(
        proposal(kind="event",open_questions=["Andere?","Wann endet der Termin?"],
                 start="2026-10-02T09:00:00+02:00",end=None),
        ProposalRevisionDelta(answered_question="Andere?",changes={"title":"Neu"}))
    assert duplicate.open_questions == ["Wann endet der Termin?"]
