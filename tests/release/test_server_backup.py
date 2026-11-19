"""Offline backup tests with synthetic credentials and fake external services."""
import json
import runpy
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from devtools import server_backup as app

NOW = datetime(2026, 11, 19, 3, 30, tzinfo=UTC)


def test_server_documentation_is_a_required_backup_source():
    root = Path(__file__).resolve().parents[2]
    template = yaml.safe_load((root/'ops/server/backup-config.example.yaml').read_text('utf-8'))
    assert '/opt/mailhelp/server-docs' in template['required_paths']
    assert '/opt/mailhelp/server-docs' not in template['optional_paths']


@pytest.fixture
def config(tmp_path):
    source = tmp_path/'source'/'credentials.env'
    source.parent.mkdir()
    source.write_text('SYNTHETIC_TOKEN=not-a-real-token\n')
    return {'schema_version': 1, 'remote': 'mailhelp-dropbox:Backup/Mailhelpserver',
            'rclone_config': str(tmp_path/'private-rclone.conf'),
            'staging_directory': str(tmp_path/'stage'), 'retention_days': 14,
            'minimum_free_bytes': 0, 'containers': ['prod', 'demo', 'absent'],
            'services': ['web.service', 'inactive.service'],
            'required_paths': [str(source)], 'optional_paths': [str(tmp_path/'missing')]}


@pytest.fixture
def fake(monkeypatch):
    calls = []
    def execute(command):
        calls.append(command)
        if command[:3] == ['docker', 'ps', '--format']:
            return 'prod\ndemo\n'
        if command[:2] == ['systemctl', 'list-units']:
            return 'web.service loaded active running Web\n'
        if command[:3] == ['docker', 'ps', '-a']:
            return 'prod mailhelp:test\ndemo mailhelp:test\n'
        if command[0] == 'rclone' and 'lsjson' in command:
            return json.dumps([{'Name': n} for n in [
                'mailhelpserver-20261001T000000Z.tar.gz',
                'mailhelpserver-20261001T000000Z.sha256',
                'mailhelpserver-20261119T000000Z.tar.gz',
                'unrelated.tar.gz', '../other-file', 'mailhelpserver-20261301T000000Z.tar.gz']])
        return ''
    monkeypatch.setattr(app, 'execute', execute)
    return calls


def test_execute_never_leaks_command_output(monkeypatch):
    monkeypatch.setattr(app.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout='safe'))
    assert app.execute(['rclone', 'ls']) == 'safe'
    monkeypatch.setattr(app.subprocess, 'run', lambda *a, **k: SimpleNamespace(
        returncode=5, stdout='SECRET', stderr='PRIVATE'))
    with pytest.raises(app.BackupError, match='rclone failed') as error:
        app.execute(['rclone', 'secret-argument'])
    assert 'SECRET' not in str(error.value) and 'secret-argument' not in str(error.value)


def test_configuration_validation(tmp_path, config):
    path = tmp_path/'config.yaml'
    path.write_text(yaml.safe_dump(config))
    assert app.load_config(path) == config
    for raw in [[], {'schema_version': 9}]:
        path.write_text(yaml.safe_dump(raw))
        with pytest.raises(app.BackupError):
            app.load_config(path)
    for key, value in [('remote', 'other:somewhere'), ('retention_days', 0), ('retention_days', 15),
                       ('required_paths', ['relative']), ('required_paths', [str(tmp_path)])]:
        changed = {**config, key: value}
        path.write_text(yaml.safe_dump(changed))
        with pytest.raises(app.BackupError):
            app.load_config(path)


def test_required_and_optional_sources(config, tmp_path):
    optional = tmp_path/'additional.txt'
    optional.write_text('synthetic')
    config['optional_paths'].append(str(optional))
    assert app.archive_sources(config) == [Path(config['required_paths'][0]), optional]
    Path(config['required_paths'][0]).unlink()
    with pytest.raises(app.BackupError, match='required'):
        app.archive_sources(config)


def test_low_disk_space_prevents_service_stop(config, fake):
    stage = Path(config['staging_directory'])
    stage.mkdir()
    config['minimum_free_bytes'] = 10**30
    with pytest.raises(app.BackupError, match='staging'):
        app.create_archive(config, stage/'unused.tar.gz', NOW)
    assert not fake


def test_success_preserves_credentials_and_restarts_before_upload(config, fake):
    import tarfile
    stage = Path(config['staging_directory'])
    stage.mkdir()
    (stage/'mailhelpserver-20261001T000000Z.tar.gz').write_text('owned old archive')
    (stage/'do-not-delete.txt').write_text('unrelated')
    result = app.backup(config, NOW)
    assert result['status'] == 'success'
    archive = stage/result['archive']
    with tarfile.open(archive) as bundle:
        assert any(m.name.endswith('credentials.env') for m in bundle.getmembers())
        content = bundle.extractfile(next(m for m in bundle if m.name.endswith('credentials.env'))).read()
        assert b'SYNTHETIC_TOKEN=not-a-real-token' in content
        manifest = json.load(bundle.extractfile('MAILHELP-BACKUP-MANIFEST.json'))
        assert manifest['unencrypted'] is True
    commands = [c[0:2] for c in fake]
    start = commands.index(['docker', 'start'])
    upload = next(i for i,c in enumerate(fake) if 'copyto' in c)
    assert start < upload
    assert ['docker', 'start', 'absent'] not in fake
    assert ['systemctl', 'start', 'inactive.service'] not in fake
    assert ['systemctl', 'start', 'web.service'] in fake
    assert not (stage/'resume.json').exists()
    assert not (stage/'mailhelpserver-20261001T000000Z.tar.gz').exists()
    assert (stage/'do-not-delete.txt').exists()
    deletions = [c[-1] for c in fake if 'deletefile' in c]
    assert len(deletions) == 2 and all('/mailhelpserver-20261001' in p for p in deletions)
    assert any('check' in c and '--one-way' in c for c in fake)


def test_service_stop_failure_still_recovers(config, fake, monkeypatch):
    real = app.execute
    def fail_stop(command):
        if command[:2] == ['docker', 'stop']:
            raise app.BackupError('synthetic stop failure')
        return real(command)
    monkeypatch.setattr(app, 'execute', fail_stop)
    stage = Path(config['staging_directory'])
    stage.mkdir()
    with pytest.raises(app.BackupError, match='stop failure'):
        app.create_archive(config, stage/'failed.tar.gz', NOW)
    assert ['docker', 'start', 'prod'] in fake
    assert ['systemctl', 'start', 'web.service'] in fake


def test_upload_failure_occurs_after_service_recovery(config, fake, monkeypatch):
    real = app.execute
    def fail_upload(command):
        if 'copyto' in command:
            raise app.BackupError('upload failed')
        return real(command)
    monkeypatch.setattr(app, 'execute', fail_upload)
    with pytest.raises(app.BackupError, match='upload failed'):
        app.backup(config, NOW)
    assert ['docker', 'start', 'prod'] in fake
    assert not any('deletefile' in c for c in fake)


@pytest.mark.parametrize(('now', 'expired', 'kept'), [
    (datetime(2026, 12, 3, 2, 30, tzinfo=UTC), '20261119T131920Z', '20261119T230000Z'),
    (datetime(2026, 10, 31, 2, 30, tzinfo=UTC), '20261017T215959Z', '20261017T220000Z'),
    (datetime(2026, 3, 30, 1, 30, tzinfo=UTC), '20260316T225959Z', '20260316T230000Z'),
])
def test_day15_deletes_first_day_regardless_of_backup_time(config, fake, monkeypatch, now, expired, kept):
    original = app.execute
    old_archive = f'mailhelpserver-{expired}.tar.gz'
    old_checksum = f'mailhelpserver-{expired}.sha256'
    retained = f'mailhelpserver-{kept}.tar.gz'
    def remote_listing(command):
        result = original(command)
        if command[0] == 'rclone' and 'lsjson' in command:
            return json.dumps([{'Name': n} for n in (old_archive, old_checksum, retained)])
        return result
    monkeypatch.setattr(app, 'execute', remote_listing)
    app.backup(config, now)
    deleted = {c[-1].rsplit('/', 1)[-1] for c in fake if 'deletefile' in c}
    assert deleted == {old_archive, old_checksum}


def test_recovery_keeps_only_unrecovered_services(config, tmp_path, monkeypatch):
    stage = Path(config['staging_directory'])
    stage.mkdir()
    path = stage/'resume.json'
    app.write_json(path, {'containers': ['prod', 'demo'], 'services': ['web.service', 'other.service']})
    def execute(command):
        if command[-1] in {'prod', 'web.service'}:
            raise app.BackupError('temporarily unavailable')
        return ''
    monkeypatch.setattr(app, 'execute', execute)
    with pytest.raises(app.BackupError, match='recovery'):
        app.recover(config)
    assert json.loads(path.read_text()) == {'containers': ['prod'], 'services': ['web.service']}
    monkeypatch.setattr(app, 'execute', lambda command: '')
    app.recover(config)
    assert not path.exists()
    app.recover(config)


def test_main_success_failure_and_recovery(config, tmp_path, monkeypatch, capsys):
    masks = []
    monkeypatch.setattr(app.os, 'umask', lambda value: masks.append(value) or 0)
    path = tmp_path/'config.yaml'
    path.write_text(yaml.safe_dump(config))
    monkeypatch.setattr(sys, 'argv', ['backup', '--config', str(path)])
    monkeypatch.setattr(app, 'backup', lambda *args: {'status': 'success'})
    assert app.main() == 0
    def fail(*args):
        raise app.BackupError('SECRET_OUTPUT_MUST_NOT_ESCAPE')
    monkeypatch.setattr(app, 'backup', fail)
    assert app.main() == 1
    status = json.loads((Path(config['staging_directory'])/'status.json').read_text())
    assert status['status'] == 'failed'
    assert 'SECRET_OUTPUT' not in capsys.readouterr().out
    monkeypatch.setattr(sys, 'argv', ['backup', '--config', str(path), '--recover'])
    assert app.main() == 0
    with pytest.raises(SystemExit) as exit_code:
        runpy.run_path(str(Path(app.__file__)), run_name='__main__')
    assert exit_code.value.code == 0
    assert masks and all(value == 0o077 for value in masks)
