"""Consistent server archives to a configured rclone remote; never prints credentials."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

OWN_FILE = re.compile(r"mailhelpserver-(\d{8}T\d{6}Z)\.(?:tar\.gz|sha256)$")


class BackupError(RuntimeError):
    """A safe error without command output or secret values."""


def execute(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise BackupError(f"{Path(command[0]).name} failed (exit {result.returncode})")
    return result.stdout


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
    temporary.chmod(0o600)
    os.replace(temporary, path)


def load_config(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or value.get('schema_version') != 1:
        raise BackupError('Unsupported backup configuration')
    if not re.fullmatch(r'[a-zA-Z0-9_-]+:Backup/Mailhelpserver', value['remote']):
        raise BackupError('Unexpected remote destination')
    if not 1 <= value['retention_days'] <= 14:
        raise BackupError('Retention must be between 1 and 14 days')
    stage = Path(value['staging_directory']).resolve()
    for raw in [*value['required_paths'], *value['optional_paths']]:
        source = Path(raw)
        if not source.is_absolute() or stage.is_relative_to(source.resolve()):
            raise BackupError('Unsafe archive source')
    return value


def recover(config: dict) -> None:
    path = Path(config['staging_directory'])/'resume.json'
    if not path.exists():
        return
    pending = json.loads(path.read_text(encoding='utf-8'))
    failed = {'containers': [], 'services': []}
    for name in pending['containers']:
        try:
            execute(['docker', 'start', name])
        except BackupError:
            failed['containers'].append(name)
    for name in pending['services']:
        try:
            execute(['systemctl', 'start', name])
        except BackupError:
            failed['services'].append(name)
    if failed['containers'] or failed['services']:
        write_json(path, failed)
        raise BackupError('Some originally running services require recovery')
    path.unlink()


def archive_sources(config: dict) -> list[Path]:
    required = [Path(p) for p in config['required_paths']]
    if not all(p.exists() for p in required):
        raise BackupError('A required backup source is missing')
    return required + [Path(p) for p in config['optional_paths'] if Path(p).exists()]


def create_archive(config: dict, archive: Path, now: datetime) -> None:
    sources = archive_sources(config)
    if shutil.disk_usage(archive.parent).free < config['minimum_free_bytes']:
        raise BackupError('Insufficient staging space')
    running = set(execute(['docker', 'ps', '--format', '{{.Names}}']).splitlines())
    services = set(execute(['systemctl', 'list-units', '--type=service', '--state=running',
                            '--plain', '--no-legend']).splitlines())
    plan = {'containers': [n for n in config['containers'] if n in running],
            'services': [n for n in config['services'] if any(s.split()[0] == n for s in services)]}
    resume = archive.parent/'resume.json'
    write_json(resume, plan)
    try:
        for name in plan['containers']:
            execute(['docker', 'stop', '--time', '45', name])
        for name in plan['services']:
            execute(['systemctl', 'stop', name])
        inventory = {'created_utc': now.isoformat(), 'archive_schema': 1,
                     'unencrypted': True, 'source_paths': [str(p) for p in sources],
                     'resume_plan': plan,
                     'running_images': execute(['docker', 'ps', '-a', '--format', '{{.Names}} {{.Image}}'])}
        with tarfile.open(archive, 'x:gz', compresslevel=3, dereference=False) as bundle:
            for source in sources:
                bundle.add(source, arcname=source.as_posix().lstrip('/'))
            raw = json.dumps(inventory, indent=2).encode()
            entry = tarfile.TarInfo('MAILHELP-BACKUP-MANIFEST.json')
            entry.size, entry.mode = len(raw), 0o600
            bundle.addfile(entry, io.BytesIO(raw))
        archive.chmod(0o600)
        with tarfile.open(archive, 'r:gz') as bundle:
            bundle.getmember('MAILHELP-BACKUP-MANIFEST.json')
    finally:
        recover(config)


def rclone(config: dict, *arguments: str) -> str:
    return execute(['rclone', '--config', config['rclone_config'], '--retries', '3',
                    '--low-level-retries', '3', '--log-level', 'ERROR', *arguments])


def expired_name(name: str, cutoff: datetime) -> bool:
    match = OWN_FILE.fullmatch(name)
    if match is None:
        return False
    try:
        return datetime.strptime(match[1], '%Y%m%dT%H%M%SZ').replace(tzinfo=UTC) < cutoff
    except ValueError:
        return False


def retention_cutoff(now: datetime, days: int) -> datetime:
    zone = ZoneInfo('Europe/Berlin')
    first_kept_day = now.astimezone(zone).date()-timedelta(days=days-1)
    return datetime.combine(first_kept_day, datetime.min.time(), tzinfo=zone)


def backup(config: dict, now: datetime) -> dict:
    stage = Path(config['staging_directory'])
    stage.mkdir(mode=0o700, parents=True, exist_ok=True)
    recover(config)
    # Fail before stopping applications if Dropbox access is unavailable.
    rclone(config, 'mkdir', config['remote'])
    rclone(config, 'lsjson', config['remote'], '--files-only', '--max-depth', '1')
    stem = 'mailhelpserver-'+now.strftime('%Y%m%dT%H%M%SZ')
    archive, checksum = stage/(stem+'.tar.gz'), stage/(stem+'.sha256')
    create_archive(config, archive, now)
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    checksum.write_text(digest+'  '+archive.name+'\n', encoding='ascii')
    checksum.chmod(0o600)
    for item in (archive, checksum):
        rclone(config, 'copyto', str(item), config['remote']+'/'+item.name, '--immutable')
    # Dropbox's content hash is compared by rclone, not merely the file size.
    rclone(config, 'check', str(stage), config['remote'], '--one-way',
           '--include', archive.name, '--include', checksum.name)
    cutoff = retention_cutoff(now, config['retention_days'])
    remote_files = json.loads(rclone(config, 'lsjson', config['remote'], '--files-only', '--max-depth', '1'))
    for item in remote_files:
        if expired_name(item['Name'], cutoff):
            rclone(config, 'deletefile', config['remote']+'/'+item['Name'])
    for item in stage.iterdir():
        if expired_name(item.name, now-timedelta(days=2)):
            item.unlink()
    return {'status': 'success', 'completed_utc': now.isoformat(), 'archive': archive.name,
            'bytes': archive.stat().st_size, 'sha256': digest, 'remote': config['remote']}


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--recover', action='store_true')
    args = parser.parse_args()
    config = load_config(args.config)
    if args.recover:
        recover(config)
        return 0
    stage = Path(config['staging_directory'])
    stage.mkdir(mode=0o700, parents=True, exist_ok=True)
    now = datetime.now(UTC)
    try:
        status = backup(config, now)
    except (BackupError, OSError, ValueError, tarfile.TarError):
        status = {'status': 'failed', 'checked_utc': now.isoformat()}
    write_json(stage/'status.json', status)
    with (stage/'events.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(status)+'\n')
    print('MAILHELP_BACKUP_'+status['status'].upper(), flush=True)
    return 0 if status['status'] == 'success' else 1


if __name__ == '__main__':
    raise SystemExit(main())
