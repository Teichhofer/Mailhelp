"""Offline contracts do not claim to measure the quality of a paid model."""
from pathlib import Path

import pytest
import yaml

from mailhelp.config import TargetSettings
from mailhelp.llm.evaluation import evaluate
from mailhelp.models import EventExtraction, TaskExtraction
from mailhelp.proposals.action_normalization import MailDateContext
from mailhelp.proposals.proposal_builder import ProposalBuilder
from tests.fakes.prompt_gate_fakes import gated_corpus, repository_prompts, repository_topics
from tests.fakes.shared_quality_corpus import ExpectedAnswers


def test_noise_examples_and_series_use_the_real_evaluation_and_builder_paths():
    corpus = gated_corpus(repository_topics())
    selected = {item['id']: item for item in corpus['cases'] if item['id'].startswith(('28_', '29_', '30_'))}
    assert len(selected) == 3
    corpus['cases'] = list(selected.values())
    report = evaluate(corpus, repository_prompts(), ExpectedAnswers(corpus), 300)
    assert report['passed'] and report['complete']
    assert selected['29_marketing_download_forward_only']['expected']['task_extraction']['tasks'] == []
    prompts = repository_prompts()
    for stage in ('task_extraction', 'action_router'):
        text = prompts.prompts[stage].system_prompt
        assert 'Whitepaper herunterladen' in text and 'gerne weiterleiten' in text
    expected = selected['30_council_series']['expected']
    items = ProposalBuilder('a' * 24, TargetSettings(todoist_project='tasks', google_calendar='calendar'),
                            MailDateContext(date_context_status='valid', date_header_parsed='2026-11-06T10:00:00+01:00',
                                            imap_received_at=None, user_timezone='Europe/Berlin')).build(
        TaskExtraction.model_validate(expected['task_extraction']).tasks,
        EventExtraction.model_validate(expected['event_extraction']).events)
    assert len({item.title for item in items}) == 11
    assert len({item.series_key for item in items[:10]}) == 1
    assert items[-1].series_key != items[0].series_key


@pytest.mark.parametrize('relative', ['prompts.yaml', 'src/mailhelp/defaults/prompts.yaml'])
def test_checkout_and_packaged_setup_use_the_same_noise_boundaries(relative):
    root = Path(__file__).resolve().parents[2]
    prompts = yaml.safe_load((root / relative).read_text(encoding='utf-8'))['prompts']
    for stage in ('action_router', 'task_extraction'):
        text = prompts[stage]['system_prompt']
        assert 'Whitepaper herunterladen' in text and 'gerne weiterleiten' in text
