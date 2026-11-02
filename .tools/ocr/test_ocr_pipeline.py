import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from contextlib import contextmanager

import numpy as np
import pytest
from PIL import Image

import ocr_pipeline as o


@pytest.fixture
def pipeline(tmp_path,monkeypatch):
    model=tmp_path/'tessdata'
    model.mkdir()
    (model/'eng.traineddata').write_bytes(b'synthetic-model')
    root=tmp_path/'source'
    root.mkdir()
    monkeypatch.setattr(o.imageio_ffmpeg,'get_ffmpeg_exe',lambda:'synthetic-ffmpeg')
    cfg={'source':str(root),'output':str(tmp_path/'out'),'fps':2,'workers':2,'text_confidence':.85,
         'tessdata':str(model),'tesseract':'synthetic-tesseract','rapid_options':{},'pipeline_version':'test'}
    return o.Pipeline(cfg)


def asset(pipeline,name='post.jpg',german=False):
    path=pipeline.root/name
    if path.suffix=='.mp4':
        path.write_bytes(b'synthetic-video')
    else:
        Image.new('RGB',(120,80),'white').save(path)
    return {'file':str(path),'name':name,'post':'ABC','german':german,'source_media':name,
            'timestamp_seconds':None,'result_key':name+'.json'}


def lines(text='Take a slow morning',score=.98):
    return [[[[10,10],[110,10],[110,40],[10,40]],text,score]]


def test_config_rejects_wrong_fps(pipeline):
    with pytest.raises(ValueError,match='zwei Frames'):
        o.Pipeline({**pipeline.cfg,'fps':1})


def test_atomic_json_hash_and_text_helpers(tmp_path):
    path=tmp_path/'nested'/'result.json'
    o.save(path,{'text':'Grüße'})
    assert o.load(path)=={'text':'Grüße'}
    assert not path.with_suffix('.json.tmp').exists()
    assert len(o.digest(path))==64
    assert o.normalize(' Slow, MORNING! ')=='slow morning'
    assert o.usable('Slow morning',.95,.85)
    assert not o.usable('x',.99,.85)
    assert not o.usable('morning',.2,.85)
    assert '+00:00' in o.now()


def test_lock_prevents_parallel_and_releases_after_error(tmp_path):
    path=tmp_path/'locks'/'run.lock'
    with pytest.raises(ValueError,match='synthetic'):
        with o.exclusive(path):
            with pytest.raises(RuntimeError,match='bereits aktiv'):
                with o.exclusive(path):
                    pytest.fail('second instance entered')
            raise ValueError('synthetic')
    with o.exclusive(path):
        assert path.exists()


def write_post(root,stem='post',shortcode='ABC',caption='just relax'):
    o.save(root/(stem+'.json'),{'node':{'shortcode':shortcode,'taken_at_timestamp':123456,
           'edge_media_to_caption':{'edges':[{'node':{'text':caption}}]},
           'edge_media_preview_like':{'count':7},'edge_media_to_parent_comment':{'count':2}}})


def test_scan_maps_media_excludes_profile_and_tagged(pipeline):
    write_post(pipeline.root,caption='Wir sind für euch da und freuen uns.')
    o.save(pipeline.root/'profile.json',{'node':{'username':'raus.life'}})
    for name in ['post.jpg','post_1.mp4','post_2.png','post_profile_pic.jpg','other.jpg']:
        (pipeline.root/name).write_bytes(b'x')
    (pipeline.root/'tagged').mkdir()
    write_post(pipeline.root/'tagged',stem='tag',shortcode='TAGGED')
    posts,media=pipeline.scan()
    assert [p['shortcode'] for p in posts]==['ABC']
    assert {m['name'] for m in media}=={'post.jpg','post_1.mp4','post_2.png'}
    assert all(m['german'] for m in media)
    assert posts[0]['likes']==7 and posts[0]['comments']==2
    write_post(pipeline.root,caption='A slow morning in the woods')
    assert not pipeline.scan()[1][0]['german']


def fake_extract(command,**kwargs):
    template=Path(command[-1])
    for i in [1,2]:
        Image.new('RGB',(120,80),'white').save(template.parent/f'frame_{i:06d}.jpg')
    return SimpleNamespace(returncode=0)


def test_extract_two_fps_cache_resume_and_commands(pipeline,monkeypatch):
    item=asset(pipeline,'movie.mp4')
    run=Mock(side_effect=fake_extract)
    monkeypatch.setattr(o.subprocess,'run',run)
    result=pipeline.extract(item)
    assert result['frame_count']==2 and result['fps']==2
    args=run.call_args.args[0]
    assert args[args.index('-vf')+1]=='fps=fps=2:start_time=0'
    assert '-nostdin' in args and '-an' in args
    assert run.call_args.kwargs['creationflags']==0x08000000
    assert pipeline.extract(item)==result and run.call_count==1


@pytest.mark.parametrize('change',[{'sha256':'wrong'},{'fps':1},{'frame_count':4}])
def test_extract_repairs_invalid_markers(pipeline,monkeypatch,change):
    item=asset(pipeline,'movie.mp4')
    monkeypatch.setattr(o.subprocess,'run',fake_extract)
    result=pipeline.extract(item)
    marker=Path(result['folder'])/'extraction.json'
    o.save(marker,{**result,**change})
    assert pipeline.extract(item)['frame_count']==2


def test_extract_fails_without_frames_and_on_ffmpeg_error(pipeline,monkeypatch):
    item=asset(pipeline,'movie.mp4')
    monkeypatch.setattr(o.subprocess,'run',lambda *a,**kw:None)
    with pytest.raises(RuntimeError,match='keine Frames'):
        pipeline.extract(item)
    def broken(*a,**kw):raise subprocess.TimeoutExpired('ffmpeg',180)
    monkeypatch.setattr(o.subprocess,'run',broken)
    with pytest.raises(subprocess.TimeoutExpired):pipeline.extract(item)


def test_recognize_quality_empty_results_and_engine_reuse(pipeline,monkeypatch):
    item=asset(pipeline)
    engine=Mock(return_value=(lines()+lines('noise',.2),[]))
    constructor=Mock(return_value=engine)
    monkeypatch.setattr(o,'RapidOCR',constructor)
    result=pipeline.recognize(item)
    assert result['usable_text']=='Take a slow morning'
    assert 'noise' in result['text'] and result['lines'][1]['usable'] is False
    assert result['german_alternative']==''
    assert pipeline.recognize(item)==result and engine.call_count==1
    second=asset(pipeline,'other.jpg')
    engine.return_value=(None,None)
    assert pipeline.recognize(second)['text']==''
    assert constructor.call_count==1


@pytest.mark.parametrize('change',[{'status':'error'},{'sha256':'wrong'},{'fingerprint':'wrong'}])
def test_recognize_retries_invalid_cache(pipeline,monkeypatch,change):
    item=asset(pipeline)
    engine=Mock(return_value=(lines(),[]))
    monkeypatch.setattr(o,'RapidOCR',lambda **kw:engine)
    result=pipeline.recognize(item)
    o.save(pipeline.out/'results'/item['result_key'],{**result,**change})
    assert pipeline.recognize(item)['status']=='ok'
    assert engine.call_count==2


def test_german_alternative_uses_detected_regions_and_local_languages(pipeline,monkeypatch):
    item=asset(pipeline,german=True)
    monkeypatch.setattr(o,'RapidOCR',lambda **kw:lambda image:(lines(),[]))
    run=Mock(return_value=SimpleNamespace(stdout='Grüße aus der Natur'.encode()))
    monkeypatch.setattr(o.subprocess,'run',run)
    result=pipeline.recognize(item)
    assert result['german_alternative']=='Grüße aus der Natur'
    assert 'deu+eng' in run.call_args.args[0]
    assert run.call_args.kwargs['env']['OMP_THREAD_LIMIT']=='1'
    assert run.call_args.kwargs['input'].startswith(b'\x89PNG')
    black=Image.new('RGB',(120,80),'black')
    assert pipeline.german_alternative(black,[{'box':lines()[0][0]}])=='Grüße aus der Natur'
    assert np.asarray(black).mean()==0


def test_process_reports_success_failure_and_progress(pipeline,monkeypatch):
    jobs=[{'file':str(i)} for i in range(101)]
    def recognize(job):
        if job['file']=='50':raise RuntimeError('synthetic OCR error')
        return {'status':'ok'}
    monkeypatch.setattr(pipeline,'recognize',recognize)
    errors=pipeline.process(jobs)
    assert errors==[{'file':'50','error':'synthetic OCR error'}]
    status=o.load(pipeline.out/'status.json')
    assert status['tasks_done']==101 and status['errors']==1
    log=(pipeline.out/'events.jsonl').read_text()
    assert 'ocr_error' in log and 'synthetic OCR error' in log
    assert pipeline.process([])==[]


def test_aggregate_preserves_frame_sources_and_deduplicates(pipeline,monkeypatch):
    item=asset(pipeline)
    monkeypatch.setattr(o,'RapidOCR',lambda **kw:lambda image:(lines()+lines('x',.99),[]))
    pipeline.recognize(item)
    other={**item,'result_key':'second.json','timestamp_seconds':.5}
    result={**o.load(pipeline.out/'results'/item['result_key']),'timestamp_seconds':.5,'german_alternative':'Ruhiger Morgen'}
    o.save(pipeline.out/'results'/'second.json',result)
    missing={**item,'result_key':'missing.json'}
    posts=[{'shortcode':'ABC','caption':'=untrusted public text','media':[]},{'shortcode':'EMPTY','caption':'','media':[]}]
    summary=pipeline.aggregate(posts,[item,other,missing],[])
    assert summary['posts']==2 and summary['posts_with_ocr_text']==1
    assert summary['video_frames']==1 and summary['still_images']==2
    assert summary['complete'] is False and summary['ocr_results_available']==2
    enriched=o.load(pipeline.out/'posts'/'ABC.json')
    assert enriched['caption']=='=untrusted public text' and enriched['ocr_text']=='Take a slow morning'
    assert len(enriched['ocr_lines'][0]['sources'])==2
    assert enriched['german_alternatives']==['Ruhiger Morgen']
    assert enriched['ocr_items_expected']==3 and enriched['ocr_items_available']==2
    assert enriched['review_required'] is True
    assert "'=untrusted" in (pipeline.out/'posts-with-ocr.csv').read_text(encoding='utf-8-sig')
    posts[0]['caption']='Take a slow morning'
    pipeline.aggregate(posts,[item,other],[])
    assert o.load(pipeline.out/'posts'/'ABC.json')['review_required'] is False
    assert o.load(pipeline.out/'summary.json')['complete'] is True


def test_run_handles_video_failure_and_frame_timestamps(pipeline,monkeypatch):
    write_post(pipeline.root)
    asset(pipeline)
    for i in range(20):asset(pipeline,f'post_{i}.mp4')
    def extract(command,**kwargs):
        if command[command.index('-i')+1].endswith('post_5.mp4'):
            raise subprocess.CalledProcessError(1,command)
        return fake_extract(command,**kwargs)
    monkeypatch.setattr(o.subprocess,'run',extract)
    monkeypatch.setattr(o,'RapidOCR',lambda **kw:lambda image:(lines(),[]))
    summary=pipeline.run()
    assert len(summary['errors'])==1
    assert summary['video_frames']==38 and summary['still_images']==1
    jobs=o.load(pipeline.out/'jobs.json')
    assert {j['timestamp_seconds'] for j in jobs}=={None,0,.5}
    assert o.load(pipeline.out/'status.json')['phase']=='complete_with_errors'
    assert 'extraction_error' in (pipeline.out/'events.jsonl').read_text()


def test_run_empty_and_main(pipeline,monkeypatch,tmp_path):
    assert pipeline.run()['posts']==0
    assert o.load(pipeline.out/'status.json')['phase']=='complete'
    o.save(tmp_path/'config.yaml',pipeline.cfg)
    monkeypatch.setattr(o,'__file__',str(tmp_path/'ocr_pipeline.py'))
    constructor=Mock(return_value=SimpleNamespace(run=lambda:'finished'))
    monkeypatch.setattr(o,'Pipeline',constructor)
    assert o.main()=='finished'
    constructor.assert_called_once_with(pipeline.cfg)


def test_corrupt_result_is_reprocessed(pipeline,monkeypatch):
    item=asset(pipeline)
    path=pipeline.out/'results'/item['result_key']
    path.parent.mkdir(parents=True)
    path.write_text('{unfinished',encoding='utf-8')
    monkeypatch.setattr(o,'RapidOCR',lambda **kw:lambda image:(lines(),[]))
    assert pipeline.recognize(item)['usable_text']=='Take a slow morning'
    o.save(path,[])
    assert pipeline.recognize(item)['usable_text']=='Take a slow morning'


def test_aggregate_rejects_stale_results_after_failed_retry(pipeline,monkeypatch):
    item=asset(pipeline)
    monkeypatch.setattr(o,'RapidOCR',lambda **kw:lambda image:(lines(),[]))
    result=pipeline.recognize(item)
    o.save(pipeline.out/'results'/item['result_key'],{**result,'fingerprint':'stale'})
    pipeline.aggregate([{'shortcode':'ABC'}],[item],[{'file':item['file'],'error':'retry failed'}])
    enriched=o.load(pipeline.out/'posts'/'ABC.json')
    assert enriched['ocr_items_available']==0 and enriched['ocr_text']==''


def test_carousel_order_is_numeric(pipeline):
    write_post(pipeline.root)
    for name in ['post_10.jpg','post_2.jpg','post_1.jpg']:
        (pipeline.root/name).write_bytes(b'synthetic')
    posts,media=pipeline.scan()
    assert posts[0]['media']==['post_1.jpg','post_2.jpg','post_10.jpg']


def test_finisher_waits_for_active_run_and_resumes_once(pipeline,monkeypatch,tmp_path):
    o.save(tmp_path/'config.yaml',pipeline.cfg)
    monkeypatch.setattr(o,'__file__',str(tmp_path/'ocr_pipeline.py'))
    attempts=[]
    @contextmanager
    def lock(path):
        attempts.append(path)
        if len(attempts)==1:raise RuntimeError('active')
        yield
    monkeypatch.setattr(o,'exclusive',lock)
    sleep=Mock()
    monkeypatch.setattr(o.time,'sleep',sleep)
    run=Mock(return_value='finished')
    monkeypatch.setattr(o,'Pipeline',lambda cfg:SimpleNamespace(run=run))
    assert o.finish_pending()=='finished'
    assert len(attempts)==2
    sleep.assert_called_once_with(15)
    run.assert_called_once_with()


def test_run_reports_missing_result_as_incomplete(pipeline,monkeypatch):
    write_post(pipeline.root)
    asset(pipeline)
    monkeypatch.setattr(pipeline,'process',lambda jobs:[])
    summary=pipeline.run()
    assert summary['complete'] is False
    assert o.load(pipeline.out/'status.json')['phase']=='complete_with_errors'
