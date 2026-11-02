"""Local, resumable OCR of downloaded posts and every 2-fps video frame."""
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import cv2
import imageio_ffmpeg
import msvcrt
import numpy as np
from PIL import Image, ImageOps
from rapidocr_onnxruntime import RapidOCR


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


@contextmanager
def exclusive(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if path.stat().st_size == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError('Ein OCR-Lauf ist bereits aktiv.') from exc
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def normalize(text):
    return re.sub(r'\W+', ' ', text.casefold()).strip()


def media_order(path):
    return [int(p) if p.isdigit() else p for p in re.split(r'(\d+)',Path(path).name)]


def usable(text, score, minimum):
    return score >= minimum and len(re.sub(r'\W+', '', text)) >= 3


class Pipeline:
    def __init__(self, config):
        self.cfg = config
        if config['fps'] != 2:
            raise ValueError('Für diesen Auftrag sind genau zwei Frames pro Sekunde erforderlich.')
        self.root = Path(config['source']).resolve()
        self.out = Path(config['output']).resolve()
        self.out.mkdir(parents=True, exist_ok=True)
        self.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        self.local = threading.local()
        model_hashes = {p.name: digest(p) for p in sorted(Path(config['tessdata']).glob('*.traineddata'))}
        self.fingerprint = hashlib.sha256(json.dumps({'config':config, 'languages':model_hashes},sort_keys=True).encode()).hexdigest()
        self.started = now()
        cv2.setNumThreads(1)

    def event(self, kind, **details):
        with (self.out / 'events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'at':now(),'event':kind,**details},ensure_ascii=False)+'\n')

    def status(self, phase, **counts):
        save(self.out/'status.json', {'phase':phase,'pid':os.getpid(),'started_at':self.started,'updated_at':now(),
                                    'fps':2,'authentication':'none','local_only':True,**counts})
        print(json.dumps({'phase':phase,**counts},ensure_ascii=False),flush=True)

    def scan(self):
        posts = []
        media = []
        for path in sorted(self.root.glob('*.json')):
            node = load(path)['node']
            if not node.get('shortcode'):
                continue
            assets = sorted((p for p in self.root.glob(path.stem+'*') if p.suffix.lower() in ('.jpg','.jpeg','.png','.mp4') and '_profile_pic' not in p.name),key=media_order)
            caption = '\n'.join(e['node']['text'] for e in node.get('edge_media_to_caption',{}).get('edges',[]))
            german = len(re.findall(r'\b(?:ich|wir|nicht|und|für|euch|uns|gemeinsam|dein)\b',caption,re.I)) >= 3
            posts.append({'shortcode':node['shortcode'],'file':path.name,'metadata_sha256':digest(path),'caption':caption,
                          'published_timestamp':node['taken_at_timestamp'],'url':'https://www.instagram.com/p/'+node['shortcode']+'/',
                          'likes':(node.get('edge_media_preview_like') or {}).get('count'),
                          'comments':(node.get('edge_media_to_parent_comment') or {}).get('count'),
                          'media':[p.name for p in assets]})
            media.extend({'file':str(p),'name':p.name,'post':node['shortcode'],'german':german} for p in assets)
        return posts, media

    def extract(self, item):
        source = Path(item['file'])
        sha = digest(source)
        folder = self.out/'frames'/source.stem/sha[:12]
        marker = folder/'extraction.json'
        if marker.exists():
            previous = load(marker)
            if previous.get('sha256') == sha and previous.get('fps') == 2 and len(list(folder.glob('frame_*.jpg'))) == previous.get('frame_count'):
                return previous
        folder.mkdir(parents=True, exist_ok=True)
        command = [self.ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-y','-i',str(source),
                   '-vf','fps=fps=2:start_time=0','-q:v','2','-an','-threads','1',str(folder/'frame_%06d.jpg')]
        subprocess.run(command,check=True,capture_output=True,timeout=180,creationflags=0x08000000)
        frames = sorted(folder.glob('frame_*.jpg'))
        if not frames:
            raise RuntimeError('FFmpeg hat keine Frames erzeugt: '+source.name)
        result = {'file':source.name,'sha256':sha,'fps':2,'frame_count':len(frames),'folder':str(folder),'completed_at':now()}
        save(marker,result)
        return result

    def recognize(self, item):
        source = Path(item['file'])
        sha = digest(source)
        result_path = self.out/'results'/item['result_key']
        cached = self.cached(result_path,sha)
        if cached is not None:
            return cached
        if not hasattr(self.local,'engine'):
            self.local.engine = RapidOCR(**self.cfg['rapid_options'])
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert('RGB')
        raw, _ = self.local.engine(np.asarray(image)[:,:,::-1].copy())
        lines = []
        for box, text, score in raw or []:
            lines.append({'text':str(text),'confidence':float(score),'box':[[float(v) for v in point] for point in box],
                          'usable':usable(text,float(score),self.cfg['text_confidence'])})
        alternative = ''
        if lines and item['german']:
            alternative = self.german_alternative(image,lines)
        result = {'status':'ok','file':str(source),'sha256':sha,'fingerprint':self.fingerprint,'post':item['post'],
                  'source_media':item['source_media'],'timestamp_seconds':item['timestamp_seconds'],'lines':lines,
                  'text':'\n'.join(x['text'] for x in lines),'usable_text':'\n'.join(x['text'] for x in lines if x['usable']),
                  'german_alternative':alternative,'completed_at':now(),
                  'execution_provider':getattr(self.local,'provider','CPU')}
        save(result_path,result)
        return result

    def cached(self,path,sha):
        try:
            result=load(path)
        except (FileNotFoundError,json.JSONDecodeError):
            return None
        if not isinstance(result,dict):
            return None
        if result.get('status')=='ok' and result.get('sha256')==sha and result.get('fingerprint')==self.fingerprint:
            return result
        return None

    def german_alternative(self, image, lines):
        crops=[]
        for line in lines:
            xs,ys=zip(*line['box'])
            crop=image.crop((max(0,int(min(xs))-4),max(0,int(min(ys))-4),min(image.width,int(max(xs))+5),min(image.height,int(max(ys))+5)))
            crop=ImageOps.autocontrast(crop.convert('L'))
            scale=64/max(1,crop.height)
            crop=crop.resize((max(1,int(crop.width*scale)),64))
            if np.asarray(crop).mean()<140:
                crop=ImageOps.invert(crop)
            crops.append(crop)
        montage=Image.new('L',(max(c.width for c in crops)+40,len(crops)*90+20),255)
        for index,crop in enumerate(crops):
            montage.paste(crop,(20,20+index*90))
        buffer=io.BytesIO()
        montage.save(buffer,format='PNG')
        cmd=[self.cfg['tesseract'],'stdin','stdout','--tessdata-dir',self.cfg['tessdata'],'-l','deu+eng','--psm','6']
        result=subprocess.run(cmd,input=buffer.getvalue(),capture_output=True,check=True,timeout=60,
                              env={**os.environ,'OMP_THREAD_LIMIT':'1'},creationflags=0x08000000)
        return result.stdout.decode('utf-8',errors='replace').strip()

    def process(self, jobs):
        errors=[]
        done=0
        self.status('ocr',tasks_total=len(jobs),tasks_done=0,errors=0)
        with ThreadPoolExecutor(self.cfg['workers']) as pool:
            futures={pool.submit(self.recognize,job):job for job in jobs}
            for future in as_completed(futures):
                job=futures[future]
                try:
                    future.result()
                except Exception as exc:
                    record={'file':job['file'],'error':str(exc)}
                    errors.append(record)
                    self.event('ocr_error',**record)
                done+=1
                if done%100==0:
                    self.status('ocr',tasks_total=len(jobs),tasks_done=done,errors=len(errors))
        self.status('ocr_done',tasks_total=len(jobs),tasks_done=done,errors=len(errors))
        return errors

    def aggregate(self, posts, jobs, errors):
        bypost={p['shortcode']:[] for p in posts}
        for job in jobs:
            path=self.out/'results'/job['result_key']
            result=self.cached(path,digest(job['file']))
            if result is not None:
                bypost[job['post']].append(result)
        enriched=[]
        for post in posts:
            found={}
            references=sorted(bypost[post['shortcode']],key=lambda r:(media_order(r['source_media']),-1 if r['timestamp_seconds'] is None else r['timestamp_seconds']))
            for result in references:
                for line in result['lines']:
                    if line['usable']:
                        key=normalize(line['text'])
                        entry=found.setdefault(key,{'text':line['text'],'sources':[]})
                        entry['sources'].append({'media':result['source_media'],'timestamp_seconds':result['timestamp_seconds'],
                                                 'confidence':line['confidence']})
            caption_keys=normalize(post.get('caption',''))
            additional=[entry['text'] for key,entry in found.items() if key not in caption_keys]
            item={**post,'ocr_text':'\n'.join(x['text'] for x in found.values()),'ocr_lines':list(found.values()),
                  'ocr_items_expected':sum(j['post']==post['shortcode'] for j in jobs),'ocr_items_available':len(references),
                  'german_alternatives':list(dict.fromkeys(r['german_alternative'] for r in references if r['german_alternative'])),
                  'ocr_additional_to_caption':additional,'review_required':bool(additional)}
            save(self.out/'posts'/(post['shortcode']+'.json'),item)
            enriched.append(item)
        totals={'posts':len(posts),'posts_with_ocr_text':sum(bool(p['ocr_text']) for p in enriched),'ocr_tasks':len(jobs),
                'video_frames':sum(j['timestamp_seconds'] is not None for j in jobs),'still_images':sum(j['timestamp_seconds'] is None for j in jobs),
                'ocr_results_available':sum(p['ocr_items_available'] for p in enriched),
                'posts_requiring_content_review':sum(p['review_required'] for p in enriched),
                'errors':errors,'updated_at':now()}
        totals['complete']=not errors and totals['ocr_results_available']==len(jobs)
        save(self.out/'posts-with-ocr.json',{'summary':totals,'posts':enriched})
        save(self.out/'summary.json',totals)
        with (self.out/'posts-with-ocr.csv').open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.writer(stream,delimiter=';')
            writer.writerow(['Shortcode','Instagram_Link','Bildunterschrift','OCR_Text','Deutsche_Alternative','Neue_OCR_Zeilen','OCR_erwartet','OCR_vorhanden','Inhaltliche_Pruefung_noetig'])
            for item in enriched:
                cells=[item['shortcode'],item.get('url',''),item.get('caption',''),item['ocr_text'],'\n'.join(item['german_alternatives']),
                       '\n'.join(item['ocr_additional_to_caption']),item['ocr_items_expected'],item['ocr_items_available'],item['review_required']]
                writer.writerow(["'"+c if isinstance(c,str) and c.lstrip().startswith(('=','+','-','@')) else c for c in cells])
        return totals

    def run(self):
        with exclusive(self.out/'run.lock'):
            posts,media=self.scan()
            save(self.out/'input-manifest.json',{'captured_at':now(),'posts':posts,'media':media,'config':self.cfg,'fingerprint':self.fingerprint})
            videos=[m for m in media if Path(m['file']).suffix=='.mp4']
            images=[m for m in media if Path(m['file']).suffix!='.mp4']
            self.status('extracting_frames',posts=len(posts),videos_total=len(videos),videos_done=0)
            jobs=[{**m,'source_media':m['name'],'timestamp_seconds':None,'result_key':m['name']+'.json'} for m in images]
            errors=[]
            for index,video in enumerate(videos,1):
                try:
                    result=self.extract(video)
                    frames=sorted(Path(result['folder']).glob('frame_*.jpg'))
                    jobs.extend({**video,'file':str(frame),'source_media':video['name'],'timestamp_seconds':i/2,
                                 'result_key':video['name']+'/'+frame.stem+'.json'} for i,frame in enumerate(frames))
                except Exception as exc:
                    record={'file':video['file'],'error':str(exc)}
                    errors.append(record)
                    self.event('extraction_error',**record)
                if index%20==0:
                    self.status('extracting_frames',posts=len(posts),videos_total=len(videos),videos_done=index)
            save(self.out/'jobs.json',jobs)
            errors.extend(self.process(jobs))
            summary=self.aggregate(posts,jobs,errors)
            self.status('complete' if summary['complete'] else 'complete_with_errors',**summary)
            return summary


def main():
    config=load(Path(__file__).with_name('config.yaml'))
    return Pipeline(config).run()


def finish_pending():
    config=load(Path(__file__).with_name('config.yaml'))
    lock=Path(config['output']).resolve()/'run.lock'
    while True:
        try:
            with exclusive(lock):
                pass
            break
        except RuntimeError:
            time.sleep(15)
    return Pipeline(config).run()
