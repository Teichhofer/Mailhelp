"""Race and lifecycle boundaries of the worker; barriers are deterministic."""
from contextlib import contextmanager

import pytest
import yaml

from mailhelp.runtime.learning_jobs import LearningConflict
from mailhelp.runtime.learning_worker import LearningPaused
from tests.fakes.learning_harness import learning


@pytest.mark.parametrize('phase',['discover','finish','result'])
def test_cancel_and_immediate_new_job_rejects_previous_generations_results(learning,phase):
    h=learning
    h.change('start',h.selection)
    def replace():
        h.change('cancel')
        h.change('start',h.selection|{'count':1})
    if phase=='discover':
        h.reader.before=replace
    else:
        h.worker.tick()
        if phase=='finish':
            state=h.jobs.state();state.cursor=len(state.candidates);h.jobs.save(state)
        @contextmanager
        def reader(*_):
            if phase=='finish':replace()
            yield h.reader
            if phase=='result':replace()
        h.worker.open_reader=reader
    h.worker.tick()
    current=h.jobs.state()
    assert current.status=='running' and current.cursor==0
    assert current.candidates is None and current.cards==[]


def test_prior_job_cannot_charge_or_pause_the_immediately_restarted_job(learning):
    h=learning
    h.change('start',h.selection);h.worker.tick()
    changed=[]
    def replace():
        if not changed:
            h.change('cancel');h.change('start',h.selection|{'count':1});changed.append(True)
    h.client.before=replace
    with pytest.raises(LearningPaused):h.worker.tick()
    current=h.jobs.state()
    assert current.reserved_tokens==0 and current.status=='running' and current.cursor==0


def test_old_background_failure_does_not_pause_a_new_generation(learning,monkeypatch):
    h=learning
    h.change('start',h.selection)
    def late_failure():
        h.change('cancel');h.change('start',h.selection|{'count':1})
        h.worker.stopped.set()
        raise ConnectionError('old generation')
    monkeypatch.setattr(h.worker,'tick',late_failure)
    h.worker.run()
    assert h.jobs.state().status=='running'


@pytest.mark.parametrize('phase',['discover','finish','result'])
@pytest.mark.parametrize('change',['cancel','config'])
def test_late_results_cannot_overwrite_cancel_or_config_change(learning,phase,change):
    h=learning
    h.change('start',h.selection)
    def mutate():
        if change=='cancel':
            h.change('cancel')
        else:
            path=h.directory/'topics.yaml'
            path.write_text(path.read_text(encoding='utf8')+'\n',encoding='utf8')
    if phase=='discover':
        h.reader.before=mutate
        assert not h.worker.tick()
    else:
        h.worker.tick()
        if phase=='finish':
            state=h.jobs.state(); state.cursor=len(state.candidates);h.jobs.save(state)
            @contextmanager
            def reader(*_):
                mutate()
                yield h.reader
            h.worker.open_reader=reader
            if change=='config':
                with pytest.raises(LearningConflict):h.worker.tick()
                assert h.jobs.state().cards==[]
                assert h.jobs.state().status=='running'
            else:
                h.worker.tick()
        else:
            h.client.before=lambda:None
            @contextmanager
            def reader(*_):
                yield h.reader
                mutate()
            h.worker.open_reader=reader
            h.worker.tick()
            assert h.jobs.state().cards==[]


@pytest.mark.parametrize('paused',[False,True])
def test_background_loop_contains_errors_and_stops(learning,paused,monkeypatch):
    h=learning
    h.worker.stop() # no thread to join yet
    h.worker.stopped.clear()
    h.change('start',h.selection)
    def tick():
        if paused:h.change('pause')
        h.worker.stopped.set()
        raise ConnectionError('secret-provider-detail')
    monkeypatch.setattr(h.worker,'tick',tick)
    h.worker.run()
    assert h.jobs.state().status=='paused'
    assert 'secret-provider' not in h.jobs.state().model_dump_json()


def test_background_loop_continues_after_successful_unit(learning,monkeypatch):
    h=learning
    def tick():h.worker.stopped.set();return True
    monkeypatch.setattr(h.worker,'tick',tick)
    h.worker.run()


def test_changed_configuration_and_failed_mail_are_isolated(learning):
    h=learning
    h.change('start',h.selection)
    h.worker.tick()
    h.client.fail=True
    h.worker.tick()
    assert h.jobs.state().cursor==1 and h.jobs.state().failures==1
    path=h.directory/'topics.yaml'
    path.write_text(path.read_text(encoding='utf8')+'\n',encoding='utf8')
    with pytest.raises(LearningConflict):h.worker.tick()


def test_multiple_mailbox_format_is_updated_without_changing_other_mailboxes(learning):
    h=learning
    path=h.directory/'config.yaml'
    raw=yaml.safe_load(path.read_text(encoding='utf8'))
    box=h.app.settings.imap.enabled_mailboxes()[0].model_dump(mode='json')
    raw['imap']={'mailboxes':[box,box|{'id':2,'label':'Other'}]}
    path.write_text(yaml.safe_dump(raw),encoding='utf8')
    h.review(); h.change('apply')
    saved=yaml.safe_load(path.read_text(encoding='utf8'))
    assert 'Archive' in saved['imap']['mailboxes'][0]['folders']
    assert 'Archive' not in saved['imap']['mailboxes'][1]['folders']
