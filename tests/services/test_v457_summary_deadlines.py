"""Deadlines in the summary (Planung Fristen in der Zusammenfassung, 4.5.7 to 4.5.9).

Regression: the real model omitted ``deadlines`` in 6 of 11 answers. The schema only
required ``sentences``, and the stored default turned the omission into "no deadline".
"""
from pathlib import Path

import pytest
import yaml

from mailhelp.mailbox.imap import FetchedMail
from mailhelp.models import MailState, Summary, SummaryAnswer
from mailhelp.processing.analysis import Analyzer, LlmSchemaValidationFailed
from mailhelp.storage import JsonStore
from tests.fakes.shared_core import prompt_config
from tests.fakes.shared_profiles import ACCOUNT_ONE
from tests.fakes.shared_self_mail import orchestrator, own_settings
from tests.fakes.shared_services import AnalyzerStub

ROOT = Path(__file__).parents[2]


class Answers:
    """Simulated provider: returns the given raw answers and records each request."""

    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def complete(self, model, parameters, system, payload, **metadata):
        self.requests.append((payload, metadata))
        return f"call-{len(self.requests)}", self.answers.pop(0)


def test_an_omitted_deadline_list_is_a_schema_error_and_is_repaired():
    client = Answers({"sentences": ["Bitte Belege bis 30.09.2026 einreichen."]},
                     {"deadlines": ["30.09.2026"], "sentences": ["Bitte Belege bis 30.09.2026 einreichen."]})
    call, summary = Analyzer(client, prompt_config(), 1).summary({"text": "x"})
    assert (call, summary.deadlines) == ("call-2", ["30.09.2026"])
    repair, metadata = client.requests[1]
    assert "deadlines" in repair["previous_validation_error"] and metadata["retry_type"] == "schema_repair"
    assert client.requests[0][1]["response_schema"] is SummaryAnswer


def test_without_a_repair_allowance_the_omission_fails_instead_of_reading_as_no_deadline():
    client = Answers({"sentences": ["Satz."]})
    with pytest.raises(LlmSchemaValidationFailed):
        Analyzer(client, prompt_config(), 0).summary({"text": "x"})


def test_an_explicitly_empty_list_still_means_no_deadline():
    client = Answers({"deadlines": [], "sentences": ["Die Stadt kündigt eine Sanierung an."]})
    assert Analyzer(client, prompt_config(), 0).summary({"text": "x"})[1] == Summary(
        sentences=["Die Stadt kündigt eine Sanierung an."])


def test_the_model_schema_requires_deadlines_first_while_stored_states_keep_the_default():
    schema = SummaryAnswer.model_json_schema()
    assert list(schema["properties"]) == ["deadlines", "sentences"]
    assert schema["required"] == ["deadlines", "sentences"] and "description" not in schema
    assert Summary.model_validate({"sentences": ["Alt."]}).deadlines == []  # states before 4.5.8


class Recording(AnalyzerStub):
    def __init__(self):
        super().__init__("relevant")
        self.summarized = []

    def summary(self, m):
        self.summarized.append(m)
        return super().summary(m)


@pytest.mark.parametrize(("sender", "perspective"), [("ich@private.example.test", True),
                                                     ("Verein <info@verein.example.test>", False)])
def test_only_an_own_note_reaches_the_summary_with_its_perspective(tmp_path, sender, perspective):
    raw = (f"From: {sender}\r\nSubject: Sommerfest\r\nDate: Sat, 07 Nov 2026 10:00:00 +0000\r\n\r\n"
           "Ich bin angemeldet und nehme teil.").encode()
    with JsonStore(tmp_path / "data") as store:
        run = orchestrator(store, own_settings(tmp_path))
        run.analyzer = analyzer = Recording()
        state = MailState.model_validate(run.process(FetchedMail("INBOX", 1, 1, raw, account_id=ACCOUNT_ONE)).state)
    (mail,) = analyzer.summarized
    assert ("perspective" in mail) is perspective
    assert "perspective" not in state.mail  # never stored


def summary_prompt(path):
    return " ".join(yaml.safe_load(path.read_text(encoding="utf-8"))["prompts"]["summary"]["system_prompt"].split())


def test_the_summary_prompt_names_what_is_no_deadline():
    prompt = summary_prompt(ROOT / "prompts.yaml")
    assert "in dieser Reihenfolge enthalten, auch wenn die Liste leer ist" in prompt
    assert prompt.index('- "deadlines"') < prompt.index('- "sentences"')
    # Header dates of a forwarding are no deadlines (real run: "Mon, 2 Nov 2026").
    assert "„Datum:“, „Gesendet:“ und „Date:“ einer weitergeleiteten oder zitierten Nachricht" in prompt
    # The user's decision of 8 November 2026: no registration deadline once registered.
    assert "eine Anmeldefrist, wenn die Mail zeigt, dass die nutzende Person bereits angemeldet ist" in prompt
    assert "Das Datum der Veranstaltung bleibt in der Liste." in prompt
    assert '"perspective" mit "self_mail": true' in prompt
    assert prompt.index('{"deadlines":[],"sentences":') > 0


def test_the_shipped_template_matches_the_repository_prompts():
    """Regression 4.5.9: 4.5.2 and 4.5.3 changed only prompts.yaml, so new installs got old prompts."""
    shipped = ROOT / "src" / "mailhelp" / "defaults" / "prompts.yaml"
    assert shipped.read_bytes().replace(b"\r\n", b"\n") == (ROOT / "prompts.yaml").read_bytes().replace(b"\r\n", b"\n")
