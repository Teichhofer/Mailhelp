"""7.8 language isolation, installed content and owned explanations."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from mailhelp.helpdocs import HelpUnavailable, load
from mailhelp.i18n import Locale, current, tr, use_locale
from mailhelp.runtime.demo_dataset import packaged, verify


@pytest.mark.parametrize(('question','expected'),[
    ('How do I change the polling interval?', 'web-einstellungen/mailabruf-und-betrieb'),
    ('How do I back up Mailhelp?', 'betrieb/sicherung'),
    ('How do I restart Mailhelp?', 'betrieb/'),
    ('How do I add a second mailbox?', 'konten-verwalten/'),
    ('How do I enable web push notifications?', 'bedienung/'),
    ('What is test mode?', 'bedienung/'),
])
def test_english_help_selects_english_sources_with_stable_ids(question, expected):
    base=load(locale=Locale.EN)
    selected=base.select(question)
    assert any(section.id.startswith(expected) for section in selected), [s.id for s in selected]
    assert all(section.source.startswith('docs/en/') for section in selected)
    assert {s.id for s in base.sections} == {s.id for s in load().sections}
    assert base.locale == Locale.EN


def test_english_help_rejects_a_mismatched_locale_manifest(tmp_path):
    import shutil

    from mailhelp.helpdocs import DIRECTORY
    shutil.copytree(DIRECTORY / 'en', tmp_path / 'en')
    path=tmp_path/'en/manifest.json'
    manifest=json.loads(path.read_text('utf-8'));manifest['locale']='de'
    path.write_text(json.dumps(manifest),encoding='utf-8')
    with pytest.raises(HelpUnavailable): load(tmp_path,locale=Locale.EN)


def test_concurrent_language_contexts_and_errors_never_leak():
    from threading import Barrier
    barrier=Barrier(2)
    def render(locale):
        with pytest.raises(RuntimeError), use_locale(locale):
            barrier.wait(timeout=5)
            assert tr('Abbrechen') == ('Cancel' if locale == Locale.EN else 'Abbrechen')
            raise RuntimeError('reset')
        return current()
    with ThreadPoolExecutor(2) as pool:
        assert list(pool.map(render,Locale)) == [Locale.DE,Locale.DE]


def test_the_english_package_has_the_frozen_approved_results():
    manifest=verify(packaged(Locale.EN))
    states=[json.loads(p.read_text('utf-8')) for p in (packaged(Locale.EN)/'state').glob('mail-*.json')]
    assert manifest.locale == Locale.EN and len(states)==30
    relevant=[s for s in states if s['relevance']['decision']=='relevant']
    irrelevant=[s for s in states if s['relevance']['decision']=='irrelevant']
    assert (len(relevant),len(irrelevant))==(10,20)
    proposals=[p for s in states for p in s['proposals']]
    assert sum(p['kind']=='event' for p in proposals)==6
    assert sum(p['kind']=='task' for p in proposals)==5
    assert all(p['status']=='pending_confirmation' and not p['open_questions'] for p in proposals)
    cake=next(p for p in proposals if 'cake' in p['title'].lower())
    assert cake['due']=='2026-12-05T13:30:00+01:00'
    assert all(p['title'].isascii() for p in proposals)


def test_cards_keep_english_description_without_the_owned_provenance_block():
    from mailhelp.domain.proposal import Proposal
    from mailhelp.review.cards import full_description
    root=packaged(Locale.EN)/'state'
    for path in root.glob('proposal-*.json'):
        proposal=Proposal.model_validate_json(path.read_bytes())
        description=full_description(proposal)
        assert description is None or 'Absender:' not in description
        assert description is None or 'Original-E-Mail' not in description
        assert proposal.description.endswith(proposal.mail_link) or proposal.description.endswith(proposal.mail_link+')')
