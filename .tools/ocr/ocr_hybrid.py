"""One isolated DirectML worker alongside CPU OCR, with durable CPU retries."""
import contextlib
import json
import queue
import subprocess
import sys
import threading
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path


class GPU:
    def __init__(self, pipeline, execution):
        self.pipeline = pipeline
        self.execution = execution
        self.process = None
        self.log = None

    def read(self, process, responses):
        for line in process.stdout:
            responses.put(line)
        responses.put(None)

    def start(self):
        self.log = (self.pipeline.out/'gpu-stderr.log').open('a', encoding='utf-8')
        self.responses = queue.Queue()
        folder = Path(__file__).resolve().parent
        code = ("import sys;sys.path.append("+repr(str(folder/'venv/Lib/site-packages'))+
                ");sys.path.insert(0,"+repr(str(folder))+
                ");import ocr_hybrid;ocr_hybrid.worker("+repr(str(folder/'config.yaml'))+")")
        self.process = subprocess.Popen([self.execution['gpu_python'],'-X','utf8','-u','-c',code],
                                        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,
                                        text=True,encoding='utf-8',creationflags=0x08000000)
        threading.Thread(target=self.read,args=(self.process,self.responses),daemon=True).start()

    def recognize(self, job):
        from ocr_pipeline import digest
        if self.process is None:
            self.start()
        self.process.stdin.write(json.dumps(job,ensure_ascii=False)+'\n')
        self.process.stdin.flush()
        try:
            response = self.responses.get(timeout=self.execution['gpu_timeout_seconds'])
        except queue.Empty as exc:
            raise RuntimeError('GPU-Zeitlimit überschritten') from exc
        if response is None:
            raise RuntimeError('GPU-Prozess beendet, Exit-Code '+str(self.process.poll()))
        answer = json.loads(response)
        if answer.get('status') != 'ok' or answer.get('result_key') != job['result_key']:
            raise RuntimeError('GPU-Aufgabe fehlgeschlagen: '+str(answer))
        result = self.pipeline.cached(self.pipeline.out/'results'/job['result_key'],digest(job['file']))
        if result is None:
            raise RuntimeError('GPU-Ergebnis fehlt oder ist ungültig')
        return result

    def close(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            self.process.stdin.close()
            self.process.stdout.close()
            self.process = None
        if self.log is not None:
            self.log.close()
            self.log = None


def process(pipeline, jobs, execution):
    from ocr_pipeline import digest
    pending = deque()
    done = 0
    for job in jobs:
        if pipeline.cached(pipeline.out/'results'/job['result_key'],digest(job['file'])) is None:
            pending.append(job)
        else:
            done += 1
    cached = done
    retries = deque()
    errors = []
    counts = {'cpu_done':0,'gpu_done':0,'gpu_fallbacks':0}
    failures = 0
    gpu_enabled = execution['gpu_enabled']
    gpu = GPU(pipeline,execution)
    futures = {}

    def status(phase):
        pipeline.status(phase,tasks_total=len(jobs),tasks_done=done,cache_reused=cached,
                        errors=len(errors),gpu_enabled=gpu_enabled,**counts)

    status('ocr_hybrid')
    reported = done//100
    try:
        with ThreadPoolExecutor(pipeline.cfg['workers']+1) as pool:
            while pending or retries or futures:
                devices = [device for device,job in futures.values()]
                if gpu_enabled and 'gpu' not in devices and pending:
                    job = pending.popleft()
                    futures[pool.submit(gpu.recognize,job)] = ('gpu',job)
                for _ in range(pipeline.cfg['workers']-devices.count('cpu')):
                    if not (retries or pending):
                        break
                    job = (retries or pending).popleft()
                    futures[pool.submit(pipeline.recognize,job)] = ('cpu',job)
                completed,_ = wait(futures,return_when=FIRST_COMPLETED)
                for future in completed:
                    device,job = futures.pop(future)
                    try:
                        future.result()
                    except Exception as exc:
                        if device == 'gpu':
                            retries.append(job)
                            failures += 1
                            counts['gpu_fallbacks'] += 1
                            gpu.close()
                            gpu_enabled = failures < execution['gpu_max_consecutive_failures']
                            pipeline.event('gpu_cpu_fallback',file=job['file'],error=str(exc),
                                           consecutive_failures=failures,gpu_enabled=gpu_enabled)
                            status('ocr_hybrid')
                            continue
                        record = {'file':job['file'],'error':str(exc)}
                        errors.append(record)
                        pipeline.event('ocr_error',**record)
                    else:
                        counts[device+'_done'] += 1
                        if device == 'gpu':
                            failures = 0
                    done += 1
                    if done//100 > reported:
                        reported = done//100
                        status('ocr_hybrid')
    finally:
        gpu.close()
    status('ocr_done')
    from ocr_pipeline import save, now
    save(pipeline.out/'execution-summary.json',{'completed_at':now(),'execution':execution,
         'tasks_total':len(jobs),'tasks_done':done,'cache_reused':cached,'errors':errors,
         'gpu_enabled_at_end':gpu_enabled,**counts})
    return errors


def configure_directml(ort, session_class):
    original = session_class._init_sess_opts

    def options(config):
        value = original(config)
        value.enable_mem_pattern = False
        value.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        return value

    session_class._init_sess_opts = staticmethod(options)


def worker(config_path):
    import onnxruntime as ort
    import ocr_pipeline as base
    from rapidocr_onnxruntime.utils.infer_engine import OrtInferSession
    configure_directml(ort,OrtInferSession)
    pipeline = base.Pipeline(base.load(config_path))
    for line in sys.stdin:
        job = json.loads(line)
        try:
            with contextlib.redirect_stdout(sys.stderr):
                if not hasattr(pipeline.local,'engine'):
                    engine = base.RapidOCR(**pipeline.cfg['rapid_options'],
                                           det_use_dml=True,cls_use_dml=True,rec_use_dml=True)
                    providers = [session.get_providers()[0] for session in
                                 (engine.text_det.infer.session,engine.text_cls.infer.session,
                                  engine.text_rec.session.session)]
                    if providers != ['DmlExecutionProvider']*3:
                        raise RuntimeError('DirectML wurde nicht für alle Modelle aktiviert')
                    pipeline.local.engine = engine
                    pipeline.local.provider = 'DirectML'
                pipeline.recognize(job)
            answer = {'status':'ok','result_key':job['result_key']}
        except Exception as exc:
            answer = {'status':'error','result_key':job['result_key'],'error':str(exc)}
        print(json.dumps(answer,ensure_ascii=False),flush=True)


def main():
    import ocr_pipeline as base
    folder = Path(__file__).resolve().parent
    pipeline = base.Pipeline(base.load(folder/'config.yaml'))
    execution = base.load(folder/'execution.yaml')
    pipeline.process = lambda jobs: process(pipeline,jobs,execution)
    return pipeline.run()
