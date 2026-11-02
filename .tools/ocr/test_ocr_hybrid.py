import io
import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
import ocr_hybrid as h
import ocr_pipeline as o
from test_ocr_pipeline import pipeline, asset, lines


@pytest.fixture
def execution():
    return {'gpu_enabled':True,'gpu_python':'synthetic-gpu-python',
            'gpu_timeout_seconds':.01,'gpu_max_consecutive_failures':3}


def child(stdout='',alive=False):
    return NS(stdin=io.StringIO(),stdout=io.StringIO(stdout),poll=Mock(return_value=None if alive else 9),
              terminate=Mock(),wait=Mock(),kill=Mock())


def test_gpu_process_protocol_and_reuse(pipeline,execution,monkeypatch):
    job=asset(pipeline)
    monkeypatch.setattr(o,'RapidOCR',lambda **kw:lambda image:(lines(),[]))
    expected=pipeline.recognize(job)
    ack=json.dumps({'status':'ok','result_key':job['result_key']})+'\n'
    process=child(ack*2)
    constructor=Mock(return_value=process)
    monkeypatch.setattr(h.subprocess,'Popen',constructor)
    gpu=h.GPU(pipeline,execution)
    assert gpu.recognize(job)==expected
    assert gpu.recognize(job)==expected
    assert constructor.call_count==1
    assert constructor.call_args.kwargs['creationflags']==0x08000000
    assert 'gpu-python' in constructor.call_args.args[0][0]
    assert process.stdin.getvalue().count('\n')==2
    gpu.close()
    gpu.close()
    assert gpu.process is None and gpu.log is None


@pytest.mark.parametrize('response,match',[
    (None,'GPU-Prozess beendet'),
    ('invalid','Expecting value'),
    ('{"status":"error","result_key":"post.jpg.json"}','fehlgeschlagen'),
    ('{"status":"ok","result_key":"wrong"}','fehlgeschlagen'),
    ('{"status":"ok","result_key":"post.jpg.json"}','fehlt'),
    ('timeout','Zeitlimit')])
def test_gpu_protocol_failure_is_observable(pipeline,execution,monkeypatch,response,match):
    job=asset(pipeline)
    gpu=h.GPU(pipeline,execution)
    gpu.process=child()
    gpu.responses=queue.Queue()
    if response!='timeout':gpu.responses.put(response)
    with pytest.raises((RuntimeError,json.JSONDecodeError),match=match):gpu.recognize(job)
    gpu.close()


def test_gpu_kills_only_own_unresponsive_process(pipeline,execution):
    gpu=h.GPU(pipeline,execution)
    process=child(alive=True)
    process.wait.side_effect=[subprocess.TimeoutExpired('gpu',10),None]
    gpu.process=process
    gpu.close()
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert process.wait.call_count==2
    gpu.process=child(alive=True)
    process=gpu.process
    gpu.close()
    process.kill.assert_not_called()


def test_gpu_spawn_failure_closes_log(pipeline,execution,monkeypatch):
    monkeypatch.setattr(h.subprocess,'Popen',Mock(side_effect=OSError('spawn failed')))
    gpu=h.GPU(pipeline,execution)
    with pytest.raises(OSError):gpu.start()
    gpu.close()
    assert gpu.log is None


def fake_gpu(monkeypatch,action):
    instance=NS(recognize=Mock(side_effect=action),close=Mock())
    monkeypatch.setattr(h,'GPU',lambda *a:instance)
    return instance


def test_cpu_gpu_parallel_disjoint_and_resume(pipeline,execution,monkeypatch):
    jobs=[asset(pipeline,f'post_{i}.jpg') for i in range(104)]
    monkeypatch.setattr(o,'RapidOCR',lambda **kw:lambda image:(lines(),[]))
    pipeline.recognize(jobs[0])
    seen=[]
    cpu_active=threading.Event()
    def cpu(job):
        cpu_active.set()
        time.sleep(.001)
        seen.append(('cpu',job['result_key']))
    def gpu(job):
        assert cpu_active.wait(2)
        seen.append(('gpu',job['result_key']))
    monkeypatch.setattr(pipeline,'recognize',cpu)
    fake_gpu(monkeypatch,gpu)
    assert h.process(pipeline,jobs,execution)==[]
    assert {device for device,key in seen}=={'cpu','gpu'}
    assert len(seen)==103 and len({key for device,key in seen})==103
    status=o.load(pipeline.out/'status.json')
    assert status['tasks_done']==104 and status['cache_reused']==1
    assert status['gpu_done']>0 and status['cpu_done']>0
    assert o.load(pipeline.out/'execution-summary.json')['tasks_done']==104
    assert h.process(pipeline,[],execution)==[]


def test_native_gpu_crash_retries_cpu_and_disables_after_three(pipeline,execution,monkeypatch):
    pipeline.cfg['workers']=1
    jobs=[asset(pipeline,f'post_{i}.jpg') for i in range(20)]
    gpu_jobs=[]
    cpu_jobs=[]
    def gpu(job):
        gpu_jobs.append(job['result_key'])
        raise RuntimeError('native process exit 1')
    def cpu(job):
        time.sleep(.01)
        cpu_jobs.append(job['result_key'])
    instance=fake_gpu(monkeypatch,gpu)
    monkeypatch.setattr(pipeline,'recognize',cpu)
    assert h.process(pipeline,jobs,execution)==[]
    assert len(gpu_jobs)==3
    assert sorted(cpu_jobs)==sorted(j['result_key'] for j in jobs)
    assert instance.close.call_count==4
    status=o.load(pipeline.out/'status.json')
    assert status['gpu_enabled'] is False and status['gpu_fallbacks']==3
    assert status['tasks_done']==20


def test_gpu_success_resets_failures_and_cpu_retry_error_is_final(pipeline,execution,monkeypatch):
    jobs=[asset(pipeline,f'post_{i}.jpg') for i in range(12)]
    attempts=[]
    def gpu(job):
        attempts.append(job)
        if len(attempts) in [1,3]:raise RuntimeError('GPU fails')
    def cpu(job):
        time.sleep(.02)
        if job in attempts:raise RuntimeError('CPU also fails')
    fake_gpu(monkeypatch,gpu)
    monkeypatch.setattr(pipeline,'recognize',cpu)
    errors=h.process(pipeline,jobs,execution)
    assert len(errors)==2 and all(e['error']=='CPU also fails' for e in errors)
    events=[json.loads(line) for line in (pipeline.out/'events.jsonl').read_text().splitlines()]
    assert [e['consecutive_failures'] for e in events if e['event']=='gpu_cpu_fallback']==[1,1]
    assert o.load(pipeline.out/'status.json')['gpu_enabled'] is True


def test_cpu_only_and_commit_before_gpu_crash_reuses_cache(pipeline,execution,monkeypatch):
    jobs=[asset(pipeline)]
    engine=Mock(return_value=(lines(),[]))
    monkeypatch.setattr(o,'RapidOCR',lambda **kw:engine)
    def gpu(job):
        pipeline.recognize(job)
        raise RuntimeError('exit after atomic save before ack')
    fake_gpu(monkeypatch,gpu)
    assert h.process(pipeline,jobs,execution)==[]
    assert engine.call_count==1
    execution['gpu_enabled']=False
    assert h.process(pipeline,[asset(pipeline,'other.jpg')],execution)==[]
    assert engine.call_count==2


def test_directml_configuration_is_sequential_without_memory_patterns():
    session_class=type('Session',(),{'_init_sess_opts':staticmethod(lambda cfg:NS(value=cfg))})
    ort=NS(ExecutionMode=NS(ORT_SEQUENTIAL='sequential'))
    h.configure_directml(ort,session_class)
    options=session_class._init_sess_opts({'threads':1})
    assert options.enable_mem_pattern is False and options.execution_mode=='sequential'
    assert options.value=={'threads':1}


@pytest.mark.parametrize('provider',['DmlExecutionProvider','CPUExecutionProvider'])
def test_worker_provider_validation_protocol_errors_and_engine_reuse(pipeline,monkeypatch,tmp_path,capsys,provider):
    import rapidocr_onnxruntime.utils.infer_engine as infer
    monkeypatch.setattr(h,'configure_directml',Mock())
    session=NS(get_providers=lambda:[provider])
    engine=NS(text_det=NS(infer=NS(session=session)),text_cls=NS(infer=NS(session=session)),
              text_rec=NS(session=NS(session=session)))
    constructor=Mock(return_value=engine)
    monkeypatch.setattr(o,'RapidOCR',constructor)
    monkeypatch.setattr(o,'Pipeline',lambda cfg:pipeline)
    config=tmp_path/'config.yaml'
    o.save(config,pipeline.cfg)
    job=asset(pipeline)
    monkeypatch.setattr(sys,'stdin',io.StringIO((json.dumps(job)+'\n')*2))
    recognize=Mock(side_effect=[None,RuntimeError('OCR failure')])
    monkeypatch.setattr(pipeline,'recognize',recognize)
    h.worker(config)
    answers=[json.loads(line) for line in capsys.readouterr().out.splitlines()]
    if provider=='DmlExecutionProvider':
        assert [a['status'] for a in answers]==['ok','error']
        assert pipeline.local.provider=='DirectML'
    else:
        assert answers[0]['status']=='error' and 'DirectML' in answers[0]['error']
    assert constructor.call_count==(1 if provider=='DmlExecutionProvider' else 2)
    assert constructor.call_args.kwargs['det_use_dml'] is True


def test_hybrid_main_uses_separate_execution_config(pipeline,execution,monkeypatch,tmp_path):
    o.save(tmp_path/'config.yaml',pipeline.cfg)
    o.save(tmp_path/'execution.yaml',execution)
    monkeypatch.setattr(h,'__file__',str(tmp_path/'ocr_hybrid.py'))
    monkeypatch.setattr(o,'Pipeline',lambda cfg:pipeline)
    monkeypatch.setattr(pipeline,'run',lambda:pipeline.process(['job']))
    process=Mock(return_value='finished')
    monkeypatch.setattr(h,'process',process)
    assert h.main()=='finished'
    process.assert_called_once_with(pipeline,['job'],execution)
