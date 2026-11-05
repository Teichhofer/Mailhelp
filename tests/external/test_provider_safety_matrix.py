"""Shared authorization, replay, uncertain writes and channel races on all real adapters."""
import json

import pytest

from mailhelp.models import Proposal, ProposalStatus
from mailhelp.proposals.integrations import execute_confirmed
from tests.fakes.provider_matrix import PROVIDERS, ProviderMemory
from tests.fakes.shared_core import proposal
from tests.fakes.shared_telegram_dialog import callback
from tests.fakes.shared_write_improvements import event
from tests.scenarios.web_scenario import mail_id, save_mail


def item(memory,**patch):
    kind=event if memory.provider.endswith('calendar') else proposal
    writer=memory.writer()
    try:
        return kind(target=writer.target,status='confirmed',**patch)
    finally:writer.close()


@pytest.mark.parametrize('provider',PROVIDERS)
@pytest.mark.parametrize('uncertain',[False,True])
def test_actual_adapters_reconcile_persisted_result_before_any_retry(tmp_path,provider,uncertain):
    memory=ProviderMemory(tmp_path/'provider.json',provider,uncertain)
    record=item(memory)
    snapshots=[]
    writer=memory.writer()
    try:
        result,_=execute_confirmed(record,writer,snapshots.append,authorize=lambda:True)
        assert result.status==('uncertain' if uncertain else 'created')
    finally:writer.close()
    assert len(memory.writes())==1
    replay_record=result if uncertain else record
    for _ in range(2):
        # Brand new adapter: no cached result, ledger or HTTP client survives restart.
        writer=memory.writer()
        try:
            result,_=execute_confirmed(replay_record,writer,snapshots.append,authorize=lambda:False)
            assert result.status=='created' and result.external_id
        finally:writer.close()
    assert len(memory.writes())==1
    calls=memory.writes()
    if provider.startswith(('caldav','apple')):
        assert calls[0]['headers']['if-none-match']=='*'
    elif provider=='todoist':
        assert calls[0]['headers']['x-request-id']
    else:
        assert calls[0]['headers'].get('x-request-id') or calls[0]['headers'].get('authorization')


@pytest.mark.parametrize('provider',PROVIDERS)
@pytest.mark.parametrize('scenario',['revoked','target','dry','uncertain_missing'])
def test_actual_adapters_never_write_without_current_matching_authorization(tmp_path,provider,scenario):
    memory=ProviderMemory(tmp_path/'provider.json',provider)
    record=item(memory)
    if scenario=='target':record=record.model_copy(update={'target':'different-approved-target'})
    if scenario=='uncertain_missing':record=record.model_copy(update={'status':'uncertain'})
    writer=memory.writer()
    try:
        result,info=execute_confirmed(record,writer,lambda _:None,test_mode=scenario=='dry',authorize=lambda:False)
        assert memory.writes()==[]
        if scenario=='revoked':assert info=={'authorization_invalid':True}
        if scenario=='dry':assert result.status=='simulated' and memory.state()['calls']==[]
        if scenario=='target':assert info=={'target_mismatch':True} and memory.state()['calls']==[]
        if scenario=='uncertain_missing':assert result.status=='uncertain'
    finally:writer.close()


@pytest.mark.parametrize('provider',PROVIDERS)
@pytest.mark.parametrize('first',['web','telegram'])
def test_both_channels_confirm_same_version_with_real_provider_adapter(web,tmp_path,provider,first):
    memory=ProviderMemory(tmp_path/'external.json',provider)
    writer=memory.writer()
    record=item(memory).model_copy(update={
        'id':'matrix','source_mail_id':mail_id(80),'status':ProposalStatus.PENDING_CONFIRMATION})
    save_mail(web.store,80,'synthetic@example.test','Synthetic matrix',[record])
    slot='google_calendar' if writer.role=='calendar' else 'todoist'
    web.dialog.write_executor.writers[slot]=writer
    fields=web.form('/',kind='confirm',proposal_id='matrix')
    telegram=callback(91,f'proposal:{record.source_mail_id}:matrix:1:confirm')
    try:
        if first=='web':
            web.submit(fields);web.run();web.telegram.updates=[telegram];web.run()
        else:
            web.telegram.updates=[telegram];web.run();web.submit(fields);web.run()
        current=web.store.load_model(f'proposal-{record.source_mail_id}-matrix',Proposal)
        assert current.status=='created' and current.version==1
        assert len(memory.writes())==1
    finally:writer.close()


@pytest.mark.parametrize('provider',PROVIDERS)
@pytest.mark.parametrize('scenario',['P2','P3','P4','P5','P6','P7','CSRF'])
def test_parallel_safety_scenarios_with_actual_adapters(web,tmp_path,provider,scenario):
    from tests.fakes.safety_harness import Gate
    memory=ProviderMemory(tmp_path/'external.json',provider)
    writer=memory.writer()
    record=item(memory).model_copy(update={
        'id':'matrix','source_mail_id':mail_id(80),'status':ProposalStatus.PENDING_CONFIRMATION})
    save_mail(web.store,80,'synthetic@example.test','Synthetic matrix',[record])
    slot='google_calendar' if writer.role=='calendar' else 'todoist'
    web.dialog.write_executor.writers[slot]=writer
    confirm=web.form('/',kind='confirm',proposal_id='matrix')
    try:
        if scenario=='CSRF':
            assert web.submit(confirm|{'csrf':'invalid'}).status==403
        elif scenario in {'P2','P7'}:
            gate=Gate(); memory.after_write=gate.hold
            response=web.submit(confirm,accept='application/json')
            with gate.during(web.run):
                repeated=web.submit(confirm,accept='application/json')
                assert repeated.status==202 and json.loads(repeated.body)['id']==json.loads(response.body)['id']
            assert len(memory.writes())==1
        else:
            if scenario=='P3':
                path=f'/vorschlag/{record.source_mail_id}/matrix/bearbeiten'
                edit=web.form(path,action=path)|{'title':'Changed by person'}
                assert web.browser.request('POST',path,edit).status==303
            elif scenario=='P4':
                assert web.submit(web.form('/',kind='reject',proposal_id='matrix')).status==303
            elif scenario=='P5':
                source=record.model_copy(update={'id':'source','source_mail_id':mail_id(81)})
                save_mail(web.store,81,'source@example.test','Synthetic source',[source])
                merge={'csrf':web.browser.csrf('/'),'key':'matrix-merge','kind':'merge_proposals',
                    'mail_id':source.source_mail_id,'proposal_id':'source','version':1,
                    'target_mail_id':record.source_mail_id,'target_proposal_id':'matrix','target_version':1}
                assert web.browser.request('POST','/abgleich',merge).status==303
            web.submit(confirm)
            if scenario=='P6':web.auth.revoke_all()
            web.run()
            assert memory.writes()==[]
        current=web.store.load_model(f'proposal-{record.source_mail_id}-matrix',Proposal)
        if scenario in {'P2','P7'}:assert current.status=='created'
        if scenario in {'P3','P5'}:assert current.version==2 and current.status=='pending_confirmation'
        if scenario=='P4':assert current.status=='rejected'
        if scenario in {'P6','CSRF'}:assert current.status=='pending_confirmation'
    finally:writer.close()


@pytest.mark.process
@pytest.mark.parametrize('provider',PROVIDERS)
@pytest.mark.parametrize('point',['A1','A2','A3','A4'])
def test_hard_kill_matrix_reconciles_real_adapter_after_two_restarts(tmp_path,provider,point):
    from mailhelp.storage import JsonStore
    from tests.fakes.safety_harness import ProcessHarness, seed
    directory=tmp_path/'app'
    memory=ProviderMemory(tmp_path/'external.json',provider)
    seed(directory)
    record=item(memory).model_copy(update={
        'id':'action','source_mail_id':mail_id(1),'status':ProposalStatus.PENDING_CONFIRMATION})
    with JsonStore(directory) as store:save_mail(store,1,'synthetic@example.test','Synthetic matrix',[record])
    harness=ProcessHarness(directory,memory.path)
    harness.run(point,mode='provider:'+provider)
    assert len(memory.writes())==(0 if point=='A1' else 1)
    for _ in range(2):
        assert harness.run(mode='provider:'+provider)[0]=='done'
        with JsonStore(directory) as store:
            current=store.load_model(f'proposal-{record.source_mail_id}-action',Proposal)
            assert current.status=='created' and current.external_id
            assert len(store.load('action-ledger')['entries'])==1
    assert len(memory.writes())==1


@pytest.mark.parametrize('provider',['google_calendar','outlook_calendar','caldav_calendar'])
@pytest.mark.parametrize('cancel',[False,True])
def test_supported_calendar_change_and_cancellation_use_existing_resource(tmp_path,provider,cancel):
    from mailhelp.models import ProposalClassification
    memory=ProviderMemory(tmp_path/'external.json',provider)
    record=item(memory)
    writer=memory.writer()
    try:
        created,_=execute_confirmed(record,writer,lambda _:None,authorize=lambda:True)
        changed=record.model_copy(update={'version':2,'target_event_id':created.external_id,
            'is_cancellation':cancel,'classification':ProposalClassification.CANCELLATION if cancel
            else ProposalClassification.CHANGE})
        result,_=execute_confirmed(changed,writer,lambda _:None,authorize=lambda:True)
        assert result.status=='created'
        assert len(memory.writes())==2
        assert memory.writes()[-1]['method']==('DELETE' if provider=='outlook_calendar' and cancel else
                                             'PUT' if provider=='caldav_calendar' else 'PATCH')
    finally:writer.close()
