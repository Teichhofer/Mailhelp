"""Processing controls reuse the live session, CSRF and durable command inbox."""
import pytest

from mailhelp.domain.mail import MailState
from mailhelp.processing.retry import failed
from mailhelp.review.commands import CommandKind
from mailhelp.review.results import ResultStatus
from mailhelp.review.views import ReviewViews
from tests.fakes.processing_retry import errored
from tests.fakes.shared_web_actions import web as web


def put(web):
    state=errored()
    for _ in range(5):
        failed(state, state.config_fingerprint, state.created_at)
    web.store.save('mail-'+state.id, state.model_dump(mode='json'))
    return state.id


def load(web, ident):
    return web.store.load_model('mail-'+ident, MailState)


@pytest.mark.parametrize('kind',['retry_mail','file_mail'])
def test_processing_controls_are_versioned_durable_and_idempotent(web, kind):
    ident=put(web)
    page=web.browser.request('GET','/status').body.decode()
    assert 'aufgegeben' in page and '5 von 5' in page
    form=web.form('/mail/'+ident, kind=kind)
    assert web.submit(form).status==303
    assert web.submit(form).status==303
    web.run()
    state=load(web,ident)
    assert state.analysis_round==2
    assert state.processing_filed==(kind=='file_mail')
    assert state.processing_operation==form['key']
    assert web.writer.created==0 and web.writer.reconciled==0
    if kind=='retry_mail':
        assert state.processing_retry is None and state.deferred_until is None
    history=web.store.load('history-'+ident)['events']
    assert len(history)==1 and history[0]['actor'].startswith('web:')
    entry=web.commands._entries()[-1]
    assert web.dialog.review.reconcile(entry.command).status==ResultStatus.DONE
    assert len(web.store.load('history-'+ident)['events'])==1
    assert web.submit({**form,'key':'another-key'}).status==409
    if kind=='file_mail':
        assert ReviewViews(web.store,'UTC').system().mails_failed==0
        assert 'bewusst abgelegt' in web.browser.request('GET','/mail/'+ident).body.decode()


@pytest.mark.parametrize('reason',['csrf','revoked','expired','changed'])
def test_processing_control_authorization_is_checked_at_admission_and_execution(web,reason):
    ident=put(web); form=web.form('/mail/'+ident, kind='retry_mail')
    if reason=='csrf':
        assert web.submit({**form,'csrf':'invalid'}).status==403
        return
    if reason=='expired':
        web.auth.revoke_all()
        assert web.submit(form).status in (303,401,403)
    else:
        assert web.submit(form).status==303
        if reason=='revoked':
            web.auth.revoke_all()
        else:
            state=load(web,ident);state.analysis_round+=1
            web.store.save('mail-'+ident,state.model_dump(mode='json'))
        web.run()
        result=web.commands._entries()[-1].result
        assert result.status==(ResultStatus.UNAUTHORIZED if reason=='revoked' else ResultStatus.STALE)
    assert load(web,ident).processing_operation is None


def test_unavailable_retained_data_and_missing_mail_cannot_be_retried(web):
    ident=put(web); form=web.form('/mail/'+ident, kind='retry_mail')
    state=load(web,ident);state.summary=None
    web.store.save('mail-'+ident,state.model_dump(mode='json'))
    html=web.browser.request('GET','/mail/'+ident).body.decode()
    assert 'value="retry_mail"' not in html and 'value="file_mail"' in html
    web.submit(form);web.run()
    assert web.commands._entries()[-1].result.status==ResultStatus.STALE
    from mailhelp.review.errors import StaleCommand
    from mailhelp.review.processing_actions import apply
    command=web.commands._entries()[-1].command
    web.store.save('mail-'+ident,None)
    with pytest.raises(StaleCommand,match='nicht mehr vorhanden'):
        apply(web.store,command)
    assert not web.dialog.review._took_effect(command)
    assert web.site.archive.mail_archive.failure_card(ident,'Betreff','csrf')==''


def test_queued_control_resumes_after_restart_and_checks_authoritative_state(web):
    ident=put(web);form=web.form('/mail/'+ident,kind='retry_mail')
    web.submit(form)
    command=web.commands._entries()[-1].command
    assert not web.dialog.review._took_effect(command)
    assert web.dialog.review.resume_admitted(command).status==ResultStatus.DONE
    assert web.dialog.review._took_effect(command)
    assert web.dialog.review.resume_admitted(command).status==ResultStatus.DONE
    assert load(web,ident).analysis_round==2
    assert CommandKind.RETRY_MAIL==command.kind
