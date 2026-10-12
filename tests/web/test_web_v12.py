"""Synthetic archive, edit, settings, lifecycle and cost acceptance tests."""
import json
from decimal import Decimal

import pytest
import yaml
from shared_application import settings
from shared_review import command
from shared_web_v12 import configure as configure
from web_scenario import mail_id, proposal

from mailhelp.config import RetentionSettings, Topic
from mailhelp.configuration import AdminCommand, AdminKind, file_hash
from mailhelp.lifecycle import Lifecycle
from mailhelp.metrics import MetricsRecorder, MetricsSettings, electricity, sibling
from mailhelp.models import MailState, Relevance, Summary
from mailhelp.retention import RetentionService
from mailhelp.review.archive import record_analysis, record_event
from mailhelp.review.commands import CommandKind
from mailhelp.review.editing import ProposalEditPatch, edit_proposal, local_time
from mailhelp.review.queries import ArchiveQueries, ArchiveQuery
from mailhelp.review.results import ResultStatus
from mailhelp.storage import JsonStore


def test_mail_archive_filters_and_analysis(web):
    state = web.store.load_model(f'mail-{mail_id(1)}', MailState)
    state.relevance = Relevance(decision='relevant', topic_ids=['school'], reason='<script>reason</script>')
    state.summary = Summary(sentences=['Zusammenfassung <b>Schule</b>'], deadlines=['morgen'])
    web.store.save(f'mail-{state.id}', state.model_dump(mode='json'))
    record_analysis(web.store, state, {'school': 'Schule'}, 'JEV')
    assert web.browser.request('GET', '/mails').status == 200
    page = web.browser.request('GET', '/mails?q=Schule&relevance=relevant&topic=school').body.decode()
    assert '1 gespeicherte Mails' in page and '&lt;b&gt;' in page
    page = web.browser.request('GET', f'/mail/{state.id}').body.decode()
    assert 'Zusammenfassung' in page and 'Schule' in page and 'JEV' in page and '&lt;script&gt;reason' in page
    queries = ArchiveQueries(web.store)
    assert queries.search(ArchiveQuery(q='zzzz'))[1] == 0
    assert queries.search(ArchiveQuery(relevance='irrelevant'))[1] == 0
    assert queries.search(ArchiveQuery(topic='unknown'))[1] == 0
    assert queries.search(ArchiveQuery(state='waiting'))[1] == 1
    assert queries.search(ArchiveQuery(state='no_action'))[1] == 1
    assert queries.search(ArchiveQuery(state='failed'))[1] == 0
    assert queries.search(ArchiveQuery(status='created'))[1] == 1
    assert queries.search(ArchiveQuery(since='2099-01-01'))[1] == 0
    assert queries.search(ArchiveQuery(until='2000-01-01'))[1] == 0
    assert queries.search(ArchiveQuery(size=1, page=2))[0]
    assert 'Nächste Seite' in web.browser.request('GET', '/mails?size=1').body.decode()
    for query in ('q=x&q=y', 'relevance=bogus', 'page=0', 'size=101', 'since=2026-02-02&until=2026-01-01', 'secret=x'):
        assert web.browser.request('GET', '/mails?' + query).status == 422


def test_archive_cache_retention_and_bad_files(web, tmp_path, monkeypatch):
    queries = ArchiveQueries(web.store)
    first = queries.items()
    assert queries.items() == first
    web.store.save('mail-' + 'b'*24, {'broken': True})
    assert len(queries.items()) == len(first) and queries.damaged == 1
    state = web.store.load_model(f'mail-{mail_id(1)}', MailState)
    state.relevance = Relevance(decision='irrelevant', topic_ids=[], reason='Werbung')
    state.steps.completion = 'completed'
    state.proposals = []
    web.store.save(f'mail-{state.id}', state.model_dump(mode='json'))
    record_analysis(web.store, state, {}, 'JEV')
    assert 'Nicht erforderlich' in web.site.archive.analysis(state.id)
    record_analysis(web.store, state, {}, 'JEV')
    record_event(web.store, proposal(1, 'old'), 'state')
    record_event(web.store, proposal(1, 'old'), 'state')
    assert len(web.store.load('history-' + state.id)['events']) == 1
    # Run only valid records; corrupt files are deliberately reported in the GUI.
    (web.store.directory / ('mail-' + 'b'*24 + '.json')).unlink()
    RetentionService(web.store, RetentionSettings(analysis_days='disabled', history_days='disabled'),
                     web.logger).run()
    assert 'Nicht vorhanden' in web.site.archive.analysis(state.id)
    assert queries.search(ArchiveQuery(q='Werbung'))[1] == 0
    assert web.site.archive.analysis('e'*24) == ''
    (web.store.directory / ('analysis-' + state.id + '.json')).write_text('broken')
    assert 'beschädigt' in web.site.archive.analysis(state.id)
    assert queries.items()  # cache remains independent of a direct external file edit
    other = web.store.load_model(f'mail-{mail_id(2)}', MailState)
    other.mail = {'date_header_parsed': 'invalid'}
    other.display_headers = None
    web.store.save(f'mail-{other.id}', other.model_dump(mode='json'))
    assert queries.items()
    other.mail = {'date_header_parsed': '2026-01-01T10:00:00'}
    web.store.save(f'mail-{other.id}', other.model_dump(mode='json'))
    assert next(i for i in queries.items() if i['id'] == other.id)['received'] is None


def test_history_versions_are_read_only(web):
    item = proposal(1, 'formular')
    for version in range(1, 4):
        item = item.model_copy(update={'version': version})
        web.store.save(f'proposal-{item.source_mail_id}-{item.id}-v{version}', item.model_dump(mode='json'))
        record_event(web.store, item, 'edit', 'web', str(version))
    assert 'Version 3' in web.browser.request('GET', '/verlauf').body.decode()
    assert 'Weitere Ereignisse' in web.browser.request('GET', '/verlauf?size=1').body.decode()
    assert web.browser.request('GET', '/verlauf?page=0').status == 422
    assert web.browser.request('GET', '/verlauf?q=missing').status == 200
    assert web.browser.request('GET', '/verlauf?status=created&since=2099-01-01').status == 200
    page = web.browser.request('GET', f'/vorschlag/{item.source_mail_id}/{item.id}/version/2').body.decode()
    assert 'Historische Version' in page and 'action="/aktion"' not in page
    assert web.browser.request('GET', f'/vorschlag/{item.source_mail_id}/{item.id}/version/99').status == 404


@pytest.mark.parametrize('value', ['2026-03-29T02:30', '2026-10-25T02:30'])
def test_edit_time_gap_and_fold_are_rejected(value):
    with pytest.raises(ValueError):
        local_time(value, 'Europe/Berlin')


def test_edit_time_and_business_validation():
    assert local_time('', 'UTC') is None
    assert local_time('2026-01-01', 'UTC').isoformat() == '2026-01-01'
    assert local_time('2026-01-01T10:00', 'Europe/Berlin').utcoffset().total_seconds() == 3600
    assert local_time('2026-10-25T02:30+01:00', 'Europe/Berlin').utcoffset().total_seconds() == 3600
    with pytest.raises(ValueError): local_time('2026-01-01T10:00', 'UTC', True)
    item = proposal(1, 'p')
    assert edit_proposal(item, ProposalEditPatch(title=item.title), 'UTC', {'Inbox'}) == item
    revised = edit_proposal(item, ProposalEditPatch(title='Changed', due='2026-10-12'), 'UTC', {'Inbox'})
    assert revised.version == 2 and revised.title == 'Changed' and revised.explicit_duplicate_create_confirmed_version is None
    for patch in ({'target': 'other'}, {'start': '2026-01-01'}, {'all_day': True}):
        with pytest.raises(ValueError): edit_proposal(item, ProposalEditPatch(**patch), 'UTC', {'Inbox'})
    with pytest.raises(ValueError): edit_proposal(item.model_copy(update={'status': 'created'}), ProposalEditPatch(title='x'), 'UTC', {'Inbox'})
    event = proposal(2, 'e', kind='event', target='Calendar', open_questions=['Wann beginnt der Termin?', 'Wann endet der Termin?'])
    for patch in ({'due': '2026-01-01'}, {'video_link': 'http://bad.test'}):
        with pytest.raises(ValueError): edit_proposal(event, ProposalEditPatch(**patch), 'UTC', {'Calendar'})
    revised = edit_proposal(event, ProposalEditPatch(start='2026-10-12T10:00+02:00', end='2026-10-12T11:00+02:00'), 'Europe/Berlin', {'Calendar'})
    assert not revised.open_questions and revised.version == 2


def test_web_edit_saves_new_version_without_external_write(web):
    path = f'/vorschlag/{mail_id(1)}/formular/bearbeiten'
    fields = web.form(path, action=path)
    response = web.browser.request('POST', path, {**fields, 'title': 'Neuer Titel'})
    assert response.status == 303
    web.run()
    assert web.writer.created == 0
    current = web.store.load(f'proposal-{mail_id(1)}-formular')
    assert current['version'] == 2 and current['title'] == 'Neuer Titel'
    web.run()
    assert web.writer.created == 0
    assert web.browser.request('POST', path, {**fields, 'title': '', 'unknown': 'bad'}).status == 422
    assert web.browser.request('GET', f'/vorschlag/{mail_id(5)}/turnen/bearbeiten').status == 409
    assert web.browser.request('GET', f'/vorschlag/{"e"*24}/missing/bearbeiten').status == 404
    event_path = f'/vorschlag/{mail_id(1)}/elternabend/bearbeiten'
    form = web.form(event_path, action=event_path)
    assert web.browser.request('POST', event_path, {**form, 'all_day': 'invalid'}).status == 422


def test_settings_confirm_queue_restart_and_conflict(web, tmp_path):
    service, metrics, lifecycle, active, calls = configure(web, tmp_path)
    page = web.browser.request('GET', '/einstellungen').body.decode()
    assert 'poll_interval_seconds' in page and 'include_requests' in page
    form = web.form('/einstellungen', action='/einstellungen/speichern', name='poll_interval_seconds')
    form['value'] = '10'
    preview = web.browser.request('POST', '/einstellungen/speichern', form)
    assert preview.status == 200 and 'ausdrücklich' in preview.body.decode()
    assert yaml.safe_load((tmp_path / 'config.yaml').read_text())['poll_interval_seconds'] == 5
    accepted = web.browser.request('POST', '/einstellungen/speichern', {**form, 'confirm': 'yes'})
    assert accepted.status == 303
    assert 'Wird verarbeitet' in web.browser.request('GET', accepted.headers['Location']).body.decode()
    web.run()
    assert active[-1].poll_interval_seconds == 10
    assert 'Gespeichert' in web.browser.request('GET', accepted.headers['Location']).body.decode()
    assert web.browser.request('POST', '/einstellungen/speichern', {**form, 'confirm': 'yes'}).status == 409
    form = web.form('/einstellungen', action='/einstellungen/speichern', name='timezone')
    assert web.browser.request('POST', '/einstellungen/speichern', {**form, 'value': 'Bad/Zone', 'confirm': 'yes'}).status == 422
    form['value'] = 'Europe/Berlin'
    result = web.browser.request('POST', '/einstellungen/speichern', {**form, 'confirm': 'yes'})
    web.run()
    assert service.active.timezone == 'UTC'
    assert yaml.safe_load((tmp_path / 'config.yaml').read_text())['timezone'] == 'Europe/Berlin'
    assert 'nächsten Start' in web.browser.request('GET', result.headers['Location']).body.decode()
    assert calls == []


def test_themes_create_disable_conflict_and_authorization(web, tmp_path):
    service, *_ = configure(web, tmp_path)
    form = web.form('/themen', action='/themen/speichern', original_id='')
    data = {**form, 'id': 'sport', 'name': 'Sport', 'description': 'Sport', 'enabled': 'true',
            'examples': 'Training; Verein', 'exclusions': '', 'confirm': 'yes'}
    response = web.browser.request('POST', '/themen/speichern', data)
    assert response.status == 303
    web.run()
    topics = yaml.safe_load((tmp_path / 'topics.yaml').read_text())['topics']
    assert len(topics) == 2 and topics[-1]['examples'] == ['Training', 'Verein']
    assert web.browser.request('POST', '/themen/speichern', data).status == 409
    form = web.form('/themen', action='/themen/speichern', original_id='sport')
    data.update(form)
    data['enabled'] = 'false'
    assert web.browser.request('POST', '/themen/speichern', data).status == 303
    web.run()
    assert yaml.safe_load((tmp_path / 'topics.yaml').read_text())['topics'][-1]['enabled'] is False
    assert web.browser.request('POST', '/themen/speichern', {**data, 'id': 'changed'}).status == 422


def test_stop_requires_post_confirm_live_session_and_current_process(web, tmp_path):
    service, metrics, lifecycle, active, calls = configure(web, tmp_path)
    form = web.form('/einstellungen/beenden', action='/einstellungen/beenden')
    assert calls == []
    assert web.browser.request('POST', '/einstellungen/beenden', {**form, 'process': 'old'}).status == 409
    response = web.browser.request('POST', '/einstellungen/beenden', form)
    assert response.status == 202 and calls == []
    assert web.browser.request('POST', '/aktion', web.form('/', kind='reject', proposal_id='formular')).status == 503
    response.after_send()
    response.after_send()
    assert calls == ['stop']
    restarted = Lifecycle(lambda: calls.append('new'), lambda actor: True)
    assert restarted.state == 'running' and restarted.process != lifecycle.process


def test_lifecycle_invalid_key_revocation_and_second_request():
    allowed = [True]
    calls = []
    life = Lifecycle(lambda: calls.append(1), lambda actor: allowed[0])
    for key in ('short', 'z'*32):
        with pytest.raises(ValueError): life.request(life.process, key, 'actor')
    callback = life.request(life.process, 'a'*32, 'actor')
    with pytest.raises(ValueError): life.request(life.process, 'b'*32, 'actor')
    allowed[0] = False
    callback()
    assert life.state == 'running' and not calls
    with pytest.raises(ValueError): life.request(life.process, 'a'*32, 'actor')


def test_metrics_costs_retry_unknown_and_concurrency(tmp_path):
    assert electricity([(0, 20), (10, 30)], 300, .3) == Decimal('0.00075')
    metrics = MetricsRecorder(tmp_path / 'llm.jsonl', MetricsSettings())
    assert metrics.report()['count'] == 0
    metrics.observe('request_started', {'call_id': 'one', 'model': 'deepseek', 'stage': 'summary'})
    metrics.observe('request_started', {'call_id': 'one', 'model': 'deepseek', 'stage': 'summary', 'attempt': 2})
    metrics.observe('response_received', {'call_id': 'one', 'provider': 'cloud', 'reported_cost': .005})
    report = metrics.report()
    assert report['count'] == 2 and report['failed'] == 1 and report['unknown_cost'] == 1
    assert Decimal(report['usd']) == Decimal('.005')
    assert report['mean'] is not None and report['p95'] >= report['median']
    assert metrics.report(model='missing')['count'] == 0
    assert metrics.report(stage='other')['count'] == 0
    assert metrics.report(mode='local')['count'] == 0
    assert metrics.report(provider='other')['count'] == 0
    assert metrics.report(since='2099-01-01')['count'] == 0
    assert metrics.report(until='2000-01-01')['count'] == 0
    for parameters in ({'days': 0}, {'days': 3651}, {'since': 'bad'}, {'since': '2026-02-02', 'until': '2026-01-01'}):
        with pytest.raises(ValueError): metrics.report(**parameters)
    local = MetricsRecorder(tmp_path / 'llm.jsonl', MetricsSettings(), 'local')
    local.observe('request_started', {'call_id': 'gemma', 'model': 'gemma'})
    local.observe('request_failed', {'call_id': 'gemma'})
    assert Decimal(local.report()['electricity_eur']) >= 0
    local.observe('response_received', {'call_id': 'absent'})
    local.observe('ignored', {'call_id': 'gemma'})
    local.observe('ignored', {})
    local.settings.enabled = False
    local.observe('request_started', {'call_id': 'disabled'})
    local.settings.enabled = True
    with local.path.open('a') as stream: stream.write('bad\n{}\n')
    local._cache = None
    assert local.records()[1] == 2
    assert '"request"' not in local.path.read_text() and '"prompt"' not in local.path.read_text()


def test_metrics_and_status_pages(web, tmp_path):
    configure(web, tmp_path)
    assert web.browser.request('GET', '/auswertung').status == 200
    assert web.browser.request('GET', '/auswertung?days=bad').status == 422
    assert 'Aktuelle Verarbeitung' in web.browser.request('GET', '/status').body.decode()
    metrics = web.site.archive.metrics
    for event in ('processing_started', 'processing_completed', 'processing_failed', 'llm_rate_limited'):
        metrics.observe(event, {'mail_id': mail_id(1)})
    metrics.observe('request_started', {'call_id': 'c', 'stage': 'relevance'})
    metrics.observe('response_received', {'call_id': 'c'})
    assert 'relevance' in web.browser.request('GET', '/auswertung').body.decode()
    web.site.archive.metrics = None
    assert 'Noch keine' in web.browser.request('GET', '/auswertung').body.decode()
    web.site.archive.configuration = None
    assert web.browser.request('GET', '/einstellungen').status == 200
    assert web.browser.request('POST', '/einstellungen/speichern', {'csrf': web.auth.csrf_token(web.auth.sessions()[0].id)}).status == 503
    assert web.browser.request('GET', '/themen').status == 503
    web.site.archive.lifecycle = None
    assert web.browser.request('GET', '/einstellungen/beenden').status == 503


def test_configuration_reconcile_failure_and_closed_patch(web, tmp_path, monkeypatch):
    service, *_ = configure(web, tmp_path)
    actor = 'web:' + web.auth.sessions()[0].id
    def cmd(**changes):
        values = dict(kind=AdminKind.SETTINGS, actor=actor, expected_hash=file_hash(tmp_path/'config.yaml'),
                      idempotency_key='c'*32, acknowledged=True, patch={'poll_interval_seconds': 10})
        values.update(changes)
        return AdminCommand(**values)
    assert service.execute(cmd(actor='web:'+'0'*16)).status == ResultStatus.UNAUTHORIZED
    assert service.execute(cmd(acknowledged=False)).status == ResultStatus.INVALID
    assert service.execute(cmd(patch={'secrets': 'bad'})).status == ResultStatus.INVALID
    original = cmd()
    assert service.reconcile(original).status == ResultStatus.FAILED
    assert service.execute(original).status == ResultStatus.DONE
    assert service.reconcile(original).status == ResultStatus.DONE
    fresh = cmd()
    monkeypatch.setattr('mailhelp.configuration.atomic_replace', lambda *args: (_ for _ in ()).throw(OSError('readonly')))
    assert service.execute(fresh).status == ResultStatus.INVALID
    web.dialog.review.configuration = None
    assert web.dialog.review.execute(fresh).status == ResultStatus.INVALID
    assert web.dialog.review.reconcile(fresh).status == ResultStatus.FAILED


def test_topics_snapshot_survives_reconfiguration_and_restart(tmp_path):
    from mailhelp.orchestrator import Orchestrator
    old = [Topic(id='school', name='School', enabled=True, description='school')]
    new = [Topic(id='sport', name='Sport', enabled=True, description='sport')]
    with JsonStore(tmp_path) as store:
        engine = Orchestrator(None, store, None, 1, old, 1000, config_fingerprint='f'*64)
        assert not engine.accepts_configuration('a'*64)
        engine.topic_policy = 'policy'
        assert not engine.accepts_configuration('a'*64)
        engine.change_topics(new)
        assert engine.accepts_configuration('f'*64)
        assert engine.topics_for('f'*64) == old
        assert engine.topics_for(engine.config_fingerprint) == new
        restarted = Orchestrator(None, store, None, 1, new, 1000, config_fingerprint='b'*64)
        restarted.topic_policy = 'policy'
        assert restarted.accepts_configuration(engine.config_fingerprint)
        assert restarted.topics_for(engine.config_fingerprint) == new


def test_metrics_compaction_recovery_validation_and_logging(tmp_path, monkeypatch):
    from mailhelp.logging import JsonlLogger
    metrics = MetricsRecorder(tmp_path/'metrics'/'llm.jsonl', MetricsSettings())
    logger = JsonlLogger(tmp_path/'logs', file_enabled=False, llm_enabled=False)
    logger.metrics = metrics
    logger.event('INFO', 'orchestrator', 'processing_started', mail_id=mail_id(1))
    logger.llm_event('request_started', call_id='c', model='model', stage='relevance')
    logger.llm_event('token_usage_recorded', call_id='c', token_usage={'prompt_tokens': 2, 'cost': .001})
    logger.llm_event('response_received', call_id='c', response={'provider': 'cloud', 'usage': {'cost': .001}})
    assert metrics.report()['count'] == 1 and metrics.report()['usd'] == '0.001'
    rows, _ = metrics.records()
    row = rows[0]
    row['started_at'] = '2020-01-01T10:00:00+00:00'
    metrics.path.write_text(json.dumps(row)+'\n'+json.dumps(row)+'\n')
    metrics._cache = None
    assert metrics.records()[0] == []
    metrics.maintain()
    daily = json.loads(sibling(metrics.path, 'daily').read_text())
    assert list(daily.values())[0]['count'] == 1
    assert metrics.path.read_text() == ''
    metrics.maintain()
    assert json.loads(sibling(metrics.path, 'daily').read_text()) == daily
    # Recover a compaction interrupted after the journal was persisted.
    pending = sibling(metrics.path, 'compaction')
    pending.write_text(json.dumps({'daily': daily, 'retained': ''}))
    metrics.maintain()
    assert not pending.exists()
    logger.llm_event('request_started', call_id='zero', model='m')
    logger.llm_event('response_received', call_id='zero', reported_cost=0)
    for cost in ('NaN', '-1'):
        logger.llm_event('request_started', call_id=cost, model='m')
        logger.llm_event('response_received', call_id=cost, reported_cost=cost)
    assert metrics.report()['unknown_cost'] == 2
    # Metrics IO failure cannot turn a completed LLM call into a failed analysis.
    monkeypatch.setattr(metrics, 'observe', lambda *args: (_ for _ in ()).throw(OSError('full')))
    logger.event('INFO', 'orchestrator', 'processing_completed')
    logger.llm_event('response_received', call_id='io')
    assert metrics.failures == 2


def test_queued_admin_recovery_and_irrelevant_topics(web, tmp_path):
    service, *_ = configure(web, tmp_path)
    form = web.form('/themen', action='/themen/speichern', category='irrelevant')
    data = {**form, 'id': 'ads', 'name': 'Werbung', 'description': 'Werbung', 'enabled': 'true',
            'examples': '', 'exclusions': '', 'confirm': 'yes'}
    assert web.browser.request('POST', '/themen/speichern', data).status == 303
    web.run()
    assert yaml.safe_load((tmp_path/'irrelevant_topics.yaml').read_text())['topics'][0]['id'] == 'ads'
    entry = web.commands._entries()[-1]
    assert web.dialog.review.reconcile(entry.command).status == ResultStatus.DONE
    assert web.dialog.review.reconcile(entry.command.model_copy(update={'idempotency_key': 'z'*32})).status == ResultStatus.FAILED


def test_missing_data_versions_queries_and_queue_conflicts(web, monkeypatch):
    item = proposal(1, 'formular')
    record_event(web.store, item, 'state')
    assert web.browser.request('GET', '/verlauf?until=2000-01-01').status == 200
    web.store.save('history-' + mail_id(1), {'schema_version': 1, 'removed': True})
    assert web.browser.request('GET', f'/vorschlag/{mail_id(1)}/formular/version/1').status == 404
    (web.store.directory / ('history-' + mail_id(2) + '.json')).write_text('broken')
    assert web.browser.request('GET', '/verlauf').status == 200
    path = f'/vorschlag/{mail_id(1)}/formular/bearbeiten'
    form = web.form(path, action=path)
    assert web.browser.request('POST', path, {**form, 'title': 'One'}).status == 303
    assert web.browser.request('POST', path, {**form, 'title': 'Two'}).status == 409
    from mailhelp.review.inbox import CommandInboxFull
    monkeypatch.setattr(web.commands, 'submit', lambda *args: (_ for _ in ()).throw(CommandInboxFull()))
    assert web.browser.request('POST', path, {**form, 'title': 'Three'}).status == 409
    queries = ArchiveQueries(web.store)
    original = web.store.peek_model
    monkeypatch.setattr(web.store, 'peek_model', lambda name, model: None if name == 'mail-'+mail_id(1) else original(name, model))
    assert len(queries.items()) == 6


def test_structured_edits_keep_unset_fields_and_authorization(web):
    from types import SimpleNamespace

    from mailhelp.config import TargetSettings
    web.dialog.relevance.handler = SimpleNamespace(targets=TargetSettings(todoist_project='New inbox', google_calendar='Calendar'))
    cmd = command(CommandKind.EDIT, mail_id=mail_id(1), proposal_id='formular', actor='web:' + web.auth.sessions()[0].id,
                  patch=ProposalEditPatch(title='Task', target='New inbox'))
    result = web.dialog.review.execute(cmd)
    assert result.status == ResultStatus.DONE
    new = web.dialog.repository.load_current(mail_id(1), 'formular')
    assert new.version == 2 and new.target == 'New inbox'
    unchanged = cmd.model_copy(update={'version': 2, 'idempotency_key': 'unchanged-key', 'patch': ProposalEditPatch(title='Task')})
    assert web.dialog.review.execute(unchanged).status == ResultStatus.DONE
    event = command(CommandKind.EDIT, mail_id=mail_id(1), proposal_id='elternabend', actor=cmd.actor,
                    patch=ProposalEditPatch(title='Event', target='Calendar'))
    assert web.dialog.review.execute(event).status == ResultStatus.DONE
    with pytest.raises(ValueError):
        command(CommandKind.REJECT, patch=ProposalEditPatch(title='illegal'))
    missing = command(CommandKind.REJECT, proposal_id='missing', actor=cmd.actor)
    web.dialog.review._record(missing)
    assert web.writer.created == 0
    web.dialog.stop_requested = lambda: True
    web.dialog.poll_once()
    web.commands.submit(command(CommandKind.REJECT, proposal_id='formular', actor=cmd.actor))
    web.dialog._process_commands()
    assert web.commands.queued()


def test_after_send_runs_only_after_actual_http_response(running):
    from threading import Event

    from shared_web_server import call

    from mailhelp.web import Response
    flag = Event()
    def handler(request):
        response = Response.text(202, 'accepted')
        response.after_send = flag.set
        return response
    server, logger = running(handler)
    assert call(server, 'GET', '/')[0] == 202
    assert flag.wait(1)


def test_activate_application_live_subset(tmp_path):
    from types import SimpleNamespace

    from mailhelp.application import Application
    cfg = settings(tmp_path)
    metrics = MetricsRecorder(tmp_path/'metrics.jsonl', cfg.metrics)
    app = SimpleNamespace(logger=SimpleNamespace(metrics=metrics), settings=cfg,
                          mailbox=SimpleNamespace(settings=cfg))
    changed = cfg.model_copy(update={'poll_interval_seconds': 10})
    Application.apply_settings(app, changed)
    assert app.settings.poll_interval_seconds == 10 and metrics.settings == changed.metrics


def test_remaining_retention_filters_and_config_validation(web, tmp_path):
    service, *_ = configure(web, tmp_path)
    actor = 'web:' + web.auth.sessions()[0].id
    cmd = AdminCommand(kind=AdminKind.SETTINGS, actor=actor, idempotency_key='nested-setting',
                       expected_hash=file_hash(tmp_path/'config.yaml'), acknowledged=True,
                       patch={'retention.analysis_days': 30})
    assert service.execute(cmd).status == ResultStatus.DONE
    assert service.active.retention.analysis_days == 30
    topic = AdminCommand(kind=AdminKind.TOPICS, actor=actor, idempotency_key='topic-unconfirmed',
                         expected_hash=file_hash(tmp_path/'topics.yaml'), patch={'id': 'school', 'name': 'School', 'enabled': True, 'description': 'School'})
    assert service.execute(topic).status == ResultStatus.INVALID
    item = proposal(1, 'formular')
    record_event(web.store, item, 'state')
    page = web.browser.request('GET', '/verlauf?status=created').body.decode()
    assert '0 Ereignisse' in page  # unknown legacy events do not falsely match a status
    life = web.site.lifecycle
    csrf = web.auth.csrf_token(web.auth.sessions()[0].id)
    assert web.browser.request('POST', '/einstellungen/beenden', {'csrf': csrf}).status == 409
    event = proposal(2, 'event', kind='event', start='2026-10-12T10:00+02:00', end='2026-10-12T11:00+02:00')
    changed = edit_proposal(event, ProposalEditPatch(location='', video_link=''), 'UTC', {'Inbox'})
    assert changed.location is None and changed.video_link is None


def test_finished_notification_is_not_sent_twice_during_resume(tmp_path):
    from shared_services import AnalyzerStub, Notify

    from mailhelp.imap import FetchedMail
    from mailhelp.orchestrator import Orchestrator, ProcessingOutcome
    topic = Topic(id='school', name='School', enabled=True, description='school')
    with JsonStore(tmp_path) as store:
        notifier = Notify()
        engine = Orchestrator(AnalyzerStub('relevant'), store, notifier, 1, [topic], 1000)
        mail = FetchedMail('INBOX', 1, 2, b'Subject: Synthetic\n\nBody')
        result = engine.process(mail)
        before = list(notifier.messages)
        state = store.load_model('mail-' + result['id'], MailState)
        state.steps.completion = 'pending'
        state.steps.proposal_notification = 'pending'
        store.save('mail-' + state.id, state.model_dump(mode='json'))
        assert engine.process(mail).outcome == ProcessingOutcome.COMPLETED
        assert notifier.messages == before


def test_pairing_activity_does_not_rebuild_mail_search_index(web, monkeypatch):
    """Regression: updating a session's last-use timestamp is not a mail change."""
    queries = web.site.archive.queries
    queries.items()
    rebuilds = []
    original = queries._rebuild
    def rebuild():
        rebuilds.append(1)
        original()
    monkeypatch.setattr(queries, '_rebuild', rebuild)
    web.browser.request('GET', '/mails')
    web.browser.request('GET', '/mails')
    assert rebuilds == []


def test_stale_structured_form_is_rejected_before_queueing(web):
    """Regression: a form bound to an old version gets HTTP 409 immediately."""
    path = f'/vorschlag/{mail_id(1)}/formular/bearbeiten'
    fields = web.form(path, action=path)
    assert web.browser.request('POST', path, {**fields, 'title': 'First'}).status == 303
    web.run()
    before = len(web.commands._entries())
    response = web.browser.request('POST', path, {**fields, 'key': 'd'*32, 'title': 'Stale'})
    assert response.status == 409
    assert len(web.commands._entries()) == before


def test_repository_rejects_misbound_proposal_identity(web):
    """Regression: a valid schema in the wrong identity file is not actionable."""
    item = proposal(2, 'formular')
    web.store.save(f'proposal-{mail_id(1)}-formular', item.model_dump(mode='json'))
    assert web.dialog.repository.load_current(mail_id(1), 'formular') is None
