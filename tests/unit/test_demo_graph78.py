"""7.8: even a rehashed corpus cannot carry foreign or inconsistent application state."""
import hashlib
import json
import shutil

import pytest

from mailhelp.i18n import Locale
from mailhelp.runtime.demo_dataset import DemoDatasetError, packaged, verify


@pytest.fixture
def corpus(tmp_path):
    target=tmp_path/'corpus'
    shutil.copytree(packaged(Locale.EN),target)
    return target


def change(corpus,name,edit):
    path=corpus/'state'/name
    raw=json.loads(path.read_text('utf-8'))
    edit(raw)
    path.write_text(json.dumps(raw),encoding='utf-8')
    manifest=json.loads((corpus/'manifest.json').read_text('utf-8'))
    manifest['files'][name]=hashlib.sha256(path.read_bytes()).hexdigest()
    (corpus/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')


@pytest.mark.parametrize('damage',['runtime','missing_mail','no_content','foreign_message','wrong_identity',
                                    'foreign_proposal','snapshot','orphan','invalid_state'])
def test_rehashed_but_inconsistent_graphs_are_rejected(corpus,damage):
    manifest=json.loads((corpus/'manifest.json').read_text('utf-8'))
    if damage in {'runtime','orphan'}:
        name='sessions.json' if damage=='runtime' else 'proposal-'+ 'a'*24+'-p_'+ 'b'*24+'.json'
        (corpus/'state'/name).write_text('{}',encoding='utf-8')
        manifest['files'][name]=hashlib.sha256(b'{}').hexdigest()
        (corpus/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    elif damage=='missing_mail':
        name=next(n for n in manifest['files'] if n.startswith('mail-'))
        del manifest['files'][name];(corpus/'state'/name).unlink()
        (corpus/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    elif damage=='snapshot':
        name=next(n for n in manifest['files'] if n.startswith('proposal-'))
        change(corpus,name,lambda raw:raw.update(title='Foreign title'))
    else:
        name=next(n for n in manifest['files'] if n.startswith('mail-') and
                  json.loads((corpus/'state'/n).read_text('utf-8'))['proposals'])
        def edit(raw):
            if damage=='no_content':raw['mail']=None
            elif damage=='foreign_message':raw['mail']['headers']['message_id']='<foreign@example.test>'
            elif damage=='wrong_identity':raw['id']='f'*24
            elif damage=='foreign_proposal':raw['proposals'][0]['source_mail_id']='f'*24
            else:raw.clear()
        change(corpus,name,edit)
    with pytest.raises(DemoDatasetError,match='Referenzen'):
        verify(corpus)


def test_both_verified_corpora_are_available_without_the_checkout():
    for locale in Locale:
        result=verify(packaged(locale))
        assert result.locale==locale and len(result.mails)==30


@pytest.mark.parametrize("field,value", [("source_commit", "unknown"), ("analysis_fingerprint", ""), ("model", " ")])
def test_english_manifest_requires_generation_provenance(corpus, field, value):
    path=corpus/'manifest.json'
    raw=json.loads(path.read_text('utf-8'));raw[field]=value
    path.write_text(json.dumps(raw),encoding='utf-8')
    with pytest.raises(DemoDatasetError,match='nicht lesbar'):
        verify(corpus)
