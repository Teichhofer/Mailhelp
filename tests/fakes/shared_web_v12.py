"""Shared synthetic fixtures and doubles; no test-module dependencies."""



import yaml
from shared_application import settings

from mailhelp.config import Topic
from mailhelp.configuration import ConfigurationService
from mailhelp.lifecycle import Lifecycle
from mailhelp.metrics import MetricsRecorder, MetricsSettings


def configure(web, tmp_path):
    cfg = settings(tmp_path)
    (tmp_path / 'config.yaml').write_text(yaml.safe_dump(cfg.model_dump(mode='json')), encoding='utf-8')
    for name, topics in [('topics.yaml', [Topic(id='school', name='Schule', description='Schule', enabled=True).model_dump()]),
                         ('irrelevant_topics.yaml', [])]:
        (tmp_path / name).write_text(yaml.safe_dump({'topics': topics}), encoding='utf-8')
    active = []
    service = ConfigurationService(tmp_path, web.store, cfg, web.dialog.review.web_authorizer, active.append)
    web.site.archive.configuration = service
    web.dialog.review.configuration = service
    metrics = MetricsRecorder(tmp_path / 'metrics.jsonl', MetricsSettings())
    web.site.archive.metrics = metrics
    calls = []
    lifecycle = Lifecycle(lambda: calls.append('stop'), web.dialog.review.web_authorizer)
    web.site.lifecycle = web.site.archive.lifecycle = lifecycle
    return service, metrics, lifecycle, active, calls
