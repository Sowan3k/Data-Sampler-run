"""Local-only HTTP service. Start with run.py; no public deployment supported."""
import csv, io, json, os, secrets, threading, time, logging, random, hashlib, re
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from datetime import date
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from . import core as C
from pilot.youtube import extract_video_id, YouTubeClient
from pilot import gemini_screen
BASE=C.ROOT; DATA=Path(os.environ.get('RESEARCH_DATA',str(BASE/'data'))); DATA.mkdir(parents=True,exist_ok=True); DB=DATA/'research.db'; TOKENFILE=DATA/'admin.token'
if not TOKENFILE.exists():
    TOKENFILE.write_text(secrets.token_urlsafe(32));os.chmod(TOKENFILE,0o600)
TOKEN=TOKENFILE.read_text().strip(); KEYS={'youtube':os.getenv('YOUTUBE_API_KEY',''),'gemini':os.getenv('GEMINI_API_KEY','')}; STOP=threading.Event()
@contextmanager
def cx():
    c=C.connect(DB)
    try:yield c
    finally:c.close()
def fail(msg,status=400):raise HTTPException(status,msg)
def identity(req:Request):
    tok=req.headers.get('Authorization','').removeprefix('Bearer ')
    if secrets.compare_digest(tok,TOKEN):return 'admin'
    with cx() as c:
        r=c.execute('SELECT name FROM coders WHERE token_hash=?',(hashlib.sha256(tok.encode()).hexdigest(),)).fetchone()
    if not r:fail('Sign in using your local access token.',401)
    return r[0]
def admin(who=Depends(identity)):
    if who!='admin':fail('Administrator access required.',403)
    return who
SECRET_PATTERN=re.compile(r'AIza[0-9A-Za-z_-]{20,}|(?i:key=)[^&\s"\']+')
def errtext(e):
    # Keep the service's own message so live failures can be diagnosed; strip anything key-like.
    msg=str(e) if isinstance(e,(ValueError,YouTubeErrorType())) else f'{type(e).__name__}: {e}'
    for key in KEYS.values():
        if key:msg=msg.replace(key,'[redacted]')
    return SECRET_PATTERN.sub('[redacted]',msg)[:500]
def YouTubeErrorType():
    from pilot.youtube import YouTubeError
    return YouTubeError
class Paused(Exception):pass

def worker():
    while not STOP.is_set():
        try:
            with cx() as c:
                row=c.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY id LIMIT 1").fetchone()
                if not row:
                    # Periodic expiry even when the browser is closed.
                    if int(time.time()) % 60 == 0:C.purge(c,C.config(c))
                    STOP.wait(.5);continue
                j=dict(row);jid=j['id'];cfg=C.config(c);args=json.loads(j['args']);c.execute("UPDATE jobs SET state='running',updated=?,error='' WHERE id=?",(C.now(),jid));c.commit()
                def check():
                    if STOP.is_set() or c.execute('SELECT state FROM jobs WHERE id=?',(jid,)).fetchone()[0]!='running':raise Paused()
                def progress(msg):
                    c.execute('UPDATE jobs SET progress=?,updated=? WHERE id=?',(msg,C.now(),jid));c.commit()
                client=None
                try:
                    kind=j['kind'];check();C.purge(c,cfg)
                    if kind=='purge':progress('Expired metadata removed. Restricted locator records remain pending policy review.')
                    elif kind=='gemini':
                        if not cfg['permissions']['gemini']:raise ValueError('Confirm permission for third-party video processing first.')
                        if not KEYS['gemini'] or not cfg['gemini']['model']:raise ValueError('Connect Gemini and select a verified model first.')
                        from google import genai
                        g=genai.Client(api_key=KEYS['gemini']);prompt=gemini_screen.build_prompt(cfg);ph=C.hashval(prompt);ch=C.hashval(cfg);n=0;skipped=0
                        # Automatic batches skip long or unknown-length uploads to protect the daily video allowance.
                        # Explicitly listed IDs are always attempted.
                        cap=int(cfg['gemini'].get('max_duration_seconds',180));explicit=bool(args.get('ids'))
                        for v in C.library(c,cfg):
                            check();vid=v['video_id']
                            if not v['active'] or (explicit and vid not in args['ids']):continue
                            if not explicit and (v['duration_seconds'] is None or v['duration_seconds']>cap):skipped+=1;continue
                            if c.execute('SELECT 1 FROM model_runs WHERE video_id=? AND model=? AND config_hash=? AND prompt_hash=? AND ok=1',(vid,cfg['gemini']['model'],ch,ph)).fetchone():continue
                            if n>=args['limit']:break
                            try:
                                raw=gemini_screen.call_gemini(g,cfg['gemini']['model'],prompt,'https://www.youtube.com/watch?v='+vid);parsed=gemini_screen.parse_output(raw,v['duration_seconds']);ok=1;payload=parsed.model_dump_json();error=''
                            except Exception as e:ok=0;payload=None;error='Model request or validation failed: '+errtext(e)
                            c.execute('INSERT INTO model_runs(video_id,model,config_hash,prompt_hash,version,created,ok,payload,error) VALUES(?,?,?,?,?,?,?,?,?)',(vid,cfg['gemini']['model'],ch,ph,cfg['version'],C.now(),ok,payload,error));c.commit();n+=1;progress(f'{n} attempts; latest {vid}: '+('validated draft' if ok else 'failed; see the video page for the error'));STOP.wait(float(cfg['gemini']['seconds_between_calls']))
                        progress(f'{n} attempts. {skipped} uploads skipped as longer than {cap}s or of unknown length; list their IDs to screen them anyway.')
                    else:
                        if not cfg['permissions']['collection']:raise ValueError('Confirm collection permission in Research setup first.')
                        if not KEYS['youtube']:raise ValueError('Connect YouTube API first.')
                        client=C.client_for(c,cfg,KEYS['youtube'],check)
                        if kind=='search':C.search(c,cfg,client,args['limit'],check,progress)
                        elif kind=='expand':C.expand(c,cfg,client,check,progress)
                        elif kind in ('refresh','hydrate'):
                            ids=[r['video_id'] for r in C.library(c,cfg) if kind=='refresh' or r['retrieval'] in ('pending','stale','unavailable')]
                            for batch in C.chunks(ids,50):check();C.ingest(c,cfg,client,batch);progress('Retrieved metadata for batch ending '+batch[-1])
                        else:raise ValueError('Unknown job')
                    c.execute("UPDATE jobs SET state='completed',updated=? WHERE id=? AND state='running'",(C.now(),jid));c.commit()
                except Paused:
                    c.execute("UPDATE jobs SET state='paused',updated=? WHERE id=? AND state='running'",(C.now(),jid));c.commit()
                except Exception as e:
                    c.execute("UPDATE jobs SET state='failed',error=?,updated=? WHERE id=? AND state='running'",(errtext(e),C.now(),jid));c.commit()
                finally:
                    if client:client.close()
        except Exception:STOP.wait(1)
@asynccontextmanager
async def lifespan(app):
    with cx() as c:
        c.execute("UPDATE jobs SET state='paused' WHERE state='running'");c.commit();C.purge(c,C.config(c))
    STOP.clear();t=threading.Thread(target=worker,daemon=True);t.start();yield;STOP.set();t.join(timeout=3)
app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
@app.middleware('http')
async def local_guard(req,call_next):
    # Reject cross-origin requests and unexpected Host values (DNS rebinding defense).
    host=req.headers.get('host','').split(':')[0];origin=req.headers.get('origin')
    if host not in ('127.0.0.1','localhost','testserver') or (origin and origin not in ('http://'+req.headers.get('host',''),'https://'+req.headers.get('host',''))):return Response('Local access only',403)
    res=await call_next(req);res.headers['Cache-Control']='no-store';res.headers['X-Content-Type-Options']='nosniff';res.headers['Referrer-Policy']='no-referrer';return res
@app.exception_handler(ValueError)
async def value_error(req,e):
    from fastapi.responses import JSONResponse
    return JSONResponse({'detail':errtext(e)},400)
@app.get('/')
def home():return FileResponse(BASE/'webapp/static/index.html')
app.mount('/static',StaticFiles(directory=BASE/'webapp/static'),name='static')
@app.get('/api/session')
def session(who=Depends(identity)):return {'role':who}
@app.get('/api/config')
def configuration(_=Depends(admin)):
    with cx() as c:return C.config(c)
@app.post('/api/config')
def save_config(data:dict,_=Depends(admin)):
    with cx() as c:
        old=C.config(c); cfg=data
        for key in old:
            if key not in cfg:fail('Missing setting '+key)
        p=cfg['study_period'];a,b=date.fromisoformat(p['start']),date.fromisoformat(p['end'])
        if a>b or (b-a).days>1096:fail('Study period must be ordered and at most three years.')
        if not cfg['version'].strip():fail('Codebook version required')
        if not 0<=float(cfg['gemini']['seconds_between_calls'])<=120:fail('Model delay must be 0 to 120 seconds')
        cfg['gemini'].setdefault('max_duration_seconds',180)
        if not 10<=int(cfg['gemini']['max_duration_seconds'])<=3600:fail('Maximum screening length must be 10 to 3600 seconds')
        if not 1<=int(cfg['storage']['api_data_max_age_days'])<=30:fail('Metadata lifetime must be 1 to 30 days')
        if not 1<=int(cfg['search']['max_pages_per_query'])<=100:fail('Page cap must be 1 to 100')
        if not cfg['search']['queries'] or any(not str(q).strip() for q in cfg['search']['queries']):fail('At least one query is required')
        if not (1<=int(cfg['search_limit'])<=100000 and 1<=int(cfg['general_limit'])<=100000):fail('Invalid quota limits')
        t=cfg['thresholds']
        if min(t['videos'],t['channels'],t['reliability_n'])<1 or not 0<=t['verified']<=100 or not 0<=t['alpha']<=1:fail('Invalid feasibility thresholds')
        if c.execute("SELECT 1 FROM jobs WHERE state IN ('running','queued')").fetchone():fail('Pause or finish jobs before changing study settings')
        cfg['storage']['db_path']='data/research.db';C.put(c,'config',cfg);C.audit(c,'configuration',{'hash':C.hashval(cfg),'version':cfg['version']});C.purge(c,cfg)
        for v in c.execute('SELECT * FROM videos').fetchall():C.db.save_prescreen(c,v['video_id'],C.prescreen_video(dict(v),cfg))
        c.commit();return {'saved':True}
@app.get('/api/connections')
def connections(_=Depends(admin)):
    with cx() as c:return {'youtube':bool(KEYS['youtube']),'gemini':bool(KEYS['gemini']),'requests':C.asrows(c,'SELECT endpoint,COUNT(*) count FROM request_log GROUP BY endpoint')}
@app.post('/api/connections')
def set_keys(d:dict,_=Depends(admin)):
    for k in KEYS:
        if k in d:KEYS[k]=str(d[k]).strip()
    return {'saved':True,'note':'Keys are held in memory only until restart.'}
@app.post('/api/test-connection')
def test_connection(d:dict,_=Depends(admin)):
    k=d.get('service')
    if k not in KEYS or not KEYS[k]:fail('Set an API key first')
    try:
        if k=='youtube':
            with cx() as c:
                client=C.client_for(c,C.config(c),KEYS[k],lambda:None)
                try:r=client.videos(['dQw4w9WgXcQ'],parts='id')
                finally:client.close()
            return {'connected':True,'note':'API responded successfully; no research record stored.'}
        from google import genai
        g=genai.Client(api_key=KEYS[k]);return {'connected':True,'models':[m.name for m in g.models.list()]}
    except Exception as e:fail(errtext(e))
@app.get('/api/jobs')
def jobs(_=Depends(admin)):
    with cx() as c:return C.asrows(c,'SELECT * FROM jobs ORDER BY id DESC LIMIT 100')
@app.post('/api/jobs')
def enqueue(d:dict,_=Depends(admin)):
    kind=d.get('kind');limit=int(d.get('limit',10))
    if kind not in ('search','expand','hydrate','refresh','purge','gemini') or not 1<=limit<=1000:fail('Invalid operation or limit')
    with cx() as c:
        c.execute('INSERT INTO jobs(kind,args,state,created,updated) VALUES(?,?,?,?,?)',(kind,C.dumps({'limit':limit,'ids':d.get('ids',[])}),'queued',C.now(),C.now()));c.commit();return {'queued':True}
@app.post('/api/jobs/{jid}')
def control(jid:int,d:dict,_=Depends(admin)):
    state=d.get('state');allowed={'paused':['running','queued'],'cancelled':['running','queued','paused','failed'],'queued':['paused','failed']}
    if state not in allowed:fail('Invalid state')
    with cx() as c:
        r=c.execute('SELECT state FROM jobs WHERE id=?',(jid,)).fetchone()
        if not r or r[0] not in allowed[state]:fail('Invalid transition')
        c.execute('UPDATE jobs SET state=?,updated=? WHERE id=?',(state,C.now(),jid));c.commit();return {'saved':True}
@app.post('/api/import')
def import_ids(d:dict,_=Depends(admin)):
    # CSV with video_id/url, source_url, note, or line-separated links. Imported leads never auto-verify.
    text=d.get('text','');source=d.get('source','manual');valid=[];bad=[]
    if source not in ('manual','fact_check','dismislab'):fail('Invalid source')
    if len(text)>2000000:fail('Import too large')
    if d.get('format')=='csv': records=list(csv.DictReader(io.StringIO(text)))
    else:records=[{'url':v.strip(),'source_url':d.get('source_url','')} for v in text.splitlines() if v.strip()]
    with cx() as c:
        for r in records:
            raw=r.get('video_id') or r.get('url') or '';vid=extract_video_id(raw)
            if not vid:bad.append(raw[:100]);continue
            C.register(c,vid,source,r.get('source_url','')+' '+r.get('note',''));valid.append(vid)
        C.audit(c,'import',{'source':source,'accepted':len(valid),'invalid':len(bad)})
    return {'accepted':len(valid),'invalid':bad}
@app.get('/api/library')
def library(_=Depends(admin)):
    with cx() as c:
        cfg=C.config(c);C.purge(c,cfg);return C.library(c,cfg)
@app.get('/api/video/{vid}')
def video(vid:str,who=Depends(identity)):
    with cx() as c:
        cfg=C.config(c);C.purge(c,cfg)
        if who!='admin':
            if not c.execute('SELECT 1 FROM assignments WHERE video_id=? AND coder=? AND version=?',(vid,who,cfg['version'])).fetchone():fail('Not assigned',403)
            a=c.execute('SELECT payload FROM annotations WHERE video_id=? AND coder=? AND version=? ORDER BY id DESC LIMIT 1',(vid,who,cfg['version'])).fetchone()
            return {'video_id':vid,'own_annotation':json.loads(a[0]) if a else None,'version':cfg['version']}
        v=next((r for r in C.library(c,cfg) if r['video_id']==vid),None)
        if not v:fail('Video not found',404)
        return {**v,'version':cfg['version'],'evidence':C.asrows(c,'SELECT * FROM evidence WHERE video_id=?',(vid,)),'discoveries':C.asrows(c,'SELECT * FROM discovery WHERE video_id=?',(vid,)),'model':C.asrows(c,'SELECT * FROM model_runs WHERE video_id=? ORDER BY id DESC LIMIT 5',(vid,)),'annotations':[r for r in C.latest(c,'annotations',cfg['version']) if r['video_id']==vid],'final':next((json.loads(r['payload']) for r in C.latest(c,'finals',cfg['version']) if r['video_id']==vid),None)}
@app.post('/api/video/{vid}/observe')
def observe(vid:str,d:dict,_=Depends(admin)):
    with cx() as c:
        if not c.execute('SELECT 1 FROM inventory WHERE video_id=?',(vid,)).fetchone():fail('Video not found',404)
        play=d.get('playback');creator=d.get('creator_label');platform=d.get('platform_label');group=d.get('group_id') or vid
        if play not in ('viewable','unavailable','unknown') or creator not in ('yes','no','unknown') or platform not in ('yes','no','unknown'):fail('Invalid observation')
        if not c.execute('SELECT 1 FROM inventory WHERE video_id=?',(group,)).fetchone():fail('Group must be an existing video ID')
        if group!=vid and not d.get('group_note','').strip():fail('Explain duplicate grouping')
        target=c.execute('SELECT group_id FROM inventory WHERE video_id=?',(group,)).fetchone()[0]
        if group!=vid and target!=group:fail('Choose the canonical group video, not another repost.')
        if group!=vid and c.execute('SELECT 1 FROM inventory WHERE group_id=? AND video_id<>?',(vid,vid)).fetchone():fail('Reassign existing group members before moving the canonical video.')
        scr=d.get('screening');snote=str(d.get('screening_note','')).strip()
        if scr is not None and scr not in C.SCREENING:fail('Invalid screening decision')
        if scr=='excluded' and not snote:fail('Give a reason for excluding the video')
        c.execute('UPDATE inventory SET playback=?,playback_at=?,creator_label=?,platform_label=?,label_at=?,group_id=?,group_note=? WHERE video_id=?',(play,C.now(),creator,platform,C.now(),group,d.get('group_note',''),vid))
        if scr is not None:c.execute('UPDATE inventory SET screening=?,screening_note=?,screening_at=? WHERE video_id=?',(scr,snote,C.now(),vid))
        c.commit();C.audit(c,'observation',{'video_id':vid,'screening':scr});return {'saved':True}
@app.post('/api/video/{vid}/evidence')
def evidence(vid:str,d:dict,_=Depends(admin)):
    with cx() as c:
        if not c.execute('SELECT 1 FROM inventory WHERE video_id=?',(vid,)).fetchone():fail('Video not found',404)
        if d.get('kind') not in C.KINDS or not d.get('note','').strip():fail('Evidence type and rationale required')
        if d.get('kind') in ('fact_check','creator_disclosure','platform_label') and not re.match(r'^https?://',d.get('source','')):fail('Provide a source URL')
        if d.get('persona') not in C.EVIDENCE_SCOPES:fail('Choose a persona scope: all, some_personas or unclear')
        date.fromisoformat(d.get('observed','')[:10]);c.execute('INSERT INTO evidence(video_id,kind,source,observed,persona,note) VALUES(?,?,?,?,?,?)',(vid,d['kind'],d.get('source',''),d['observed'],d.get('persona',''),d['note']));c.commit();return {'saved':True}
@app.get('/api/codebook')
def codebook(who=Depends(identity)):
    with cx() as c:return {'video':C.VIDEO_FIELDS,'persona':C.PERSONA_FIELDS,'version':C.config(c)['version']}
@app.post('/api/video/{vid}/annotation')
def annotate(vid:str,d:dict,who=Depends(identity)):
    with cx() as c:
        cfg=C.config(c)
        if d.get('version')!=cfg['version']:fail('Codebook version changed; reload.')
        if not c.execute('SELECT 1 FROM inventory WHERE video_id=?',(vid,)).fetchone():fail('Video not found',404)
        if who!='admin' and not c.execute('SELECT 1 FROM assignments WHERE video_id=? AND coder=? AND version=?',(vid,who,cfg['version'])).fetchone():fail('Not assigned',403)
        row=c.execute('SELECT duration_seconds FROM videos WHERE video_id=?',(vid,)).fetchone();a=C.validate_annotation(d['payload'],row[0] if row else None)
        if who=='admin' and d.get('final'):
            c.execute('INSERT INTO finals(video_id,version,payload,created) VALUES(?,?,?,?)',(vid,cfg['version'],C.dumps(a),C.now()))
        else:c.execute('INSERT INTO annotations(video_id,coder,version,payload,created) VALUES(?,?,?,?,?)',(vid,who,cfg['version'],C.dumps(a),C.now()))
        c.commit();return {'saved':True}
@app.post('/api/coders')
def add_coder(d:dict,_=Depends(admin)):
    name=d.get('name','').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',name) or name=='admin':fail('Use a unique short name (letters, digits, hyphens).')
    token=secrets.token_urlsafe(32)
    with cx() as c:
        if c.execute('SELECT 1 FROM coders WHERE name=?',(name,)).fetchone():fail('Coder already exists')
        c.execute('INSERT INTO coders VALUES(?,?)',(name,hashlib.sha256(token.encode()).hexdigest()));c.commit();return {'name':name,'token':token}
@app.get('/api/coders')
def coders(_=Depends(admin)):
    with cx() as c:return C.asrows(c,'SELECT name FROM coders ORDER BY name')
@app.post('/api/assign')
def assign(d:dict,_=Depends(admin)):
    names=list(dict.fromkeys(d.get('coders',[])));n=int(d.get('n',50));seed=int(d.get('seed',42))
    if len(names)<2 or n<1 or n>10000:fail('Choose at least two independent coders and a positive sample size')
    with cx() as c:
        cfg=C.config(c);available={r[0] for r in c.execute('SELECT name FROM coders')}
        if not set(names)<=available:fail('Unknown coder')
        ids=sorted(r['video_id'] for r in C.screened_eligible(c,cfg))
        if not ids:fail('No screened-eligible videos yet. Mark videos as eligible in the screening field on each video page first.')
        sample=random.Random(seed).sample(ids,min(n,len(ids)))
        for v in sample:
            for name in names:c.execute('INSERT OR IGNORE INTO assignments VALUES(?,?,?)',(v,name,cfg['version']))
        c.commit();C.audit(c,'sample',{'seed':seed,'n':len(sample),'pool':len(ids),'coders':names,'ids':sample,'version':cfg['version']});return {'assigned':len(sample),'pool':len(ids)}
@app.get('/api/assignments')
def assignments(who=Depends(identity)):
    with cx() as c:
        cfg=C.config(c);q='SELECT a.video_id,a.coder,a.version,EXISTS(SELECT 1 FROM annotations x WHERE x.video_id=a.video_id AND x.coder=a.coder AND x.version=a.version) done FROM assignments a WHERE a.version=?';return C.asrows(c,q+('' if who=='admin' else ' AND coder=?'),(cfg['version'],) if who=='admin' else (cfg['version'],who))
@app.get('/api/report')
def report(_=Depends(admin)):
    with cx() as c:
        cfg=C.config(c);C.purge(c,cfg)
        if not cfg['permissions']['analysis']:return {'blocked':True,'note':'Confirm cross-channel analysis permission before computing research statistics.'}
        return C.report(c,cfg)
@app.get('/api/audit')
def audit(_=Depends(admin)):
    with cx() as c:return C.asrows(c,'SELECT * FROM audit ORDER BY id DESC LIMIT 200')
@app.get('/api/export/{fmt}')
def export(fmt:str,_=Depends(admin)):
    with cx() as c:
        cfg=C.config(c)
        if not cfg['permissions']['export'] or not cfg['permissions']['analysis']:fail('Export and analysis permissions must be recorded.',403)
        C.purge(c,cfg);r=C.report(c,cfg)
        # aggregate report only; no source IDs, API metadata or raw model output.
        if fmt=='json':body=json.dumps(r,ensure_ascii=False,indent=2);media='application/json'
        elif fmt=='md':body='# Feasibility report\n\n'+ '\n'.join(f'- {k}: {v}' for k,v in r.items());media='text/markdown'
        elif fmt=='csv':
            s=io.StringIO();w=csv.writer(s);w.writerow(['metric','value']);w.writerows((k,str(v)) for k,v in r.items() if not isinstance(v,dict));body=s.getvalue();media='text/csv'
        else:fail('Unknown format')
        return Response(body,media_type=media,headers={'Content-Disposition':f'attachment; filename="feasibility.{fmt}"'})
