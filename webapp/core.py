"""Local research data and jobs. No network calls on import."""
import hashlib, json, random, sqlite3, re, os, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import Counter, defaultdict
from pilot import db, collect, gemini_screen
from pilot.prescreen import prescreen_video, parse_iso_duration, in_period
from pilot.youtube import YouTubeClient, chunks, extract_video_id
from pilot.config import load_config
ROOT=Path(__file__).resolve().parents[1]
SCHEMA='''
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY,v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,args TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'queued',progress TEXT DEFAULT '',error TEXT DEFAULT '',created TEXT,updated TEXT);
CREATE TABLE IF NOT EXISTS checkpoints(job_key TEXT PRIMARY KEY,token TEXT,pages INTEGER DEFAULT 0,done INTEGER DEFAULT 0,updated TEXT);
CREATE TABLE IF NOT EXISTS request_log(id INTEGER PRIMARY KEY,endpoint TEXT,at TEXT);
CREATE TABLE IF NOT EXISTS inventory(video_id TEXT PRIMARY KEY, retrieval TEXT DEFAULT 'pending',checked TEXT,playback TEXT DEFAULT 'unknown',playback_at TEXT, group_id TEXT, group_note TEXT, manual_channel TEXT, creator_label TEXT DEFAULT 'unknown',platform_label TEXT DEFAULT 'unknown',label_at TEXT);
CREATE TABLE IF NOT EXISTS evidence(id INTEGER PRIMARY KEY,video_id TEXT NOT NULL,kind TEXT NOT NULL,source TEXT,observed TEXT,persona TEXT,note TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS coders(name TEXT PRIMARY KEY,token_hash TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS assignments(video_id TEXT,coder TEXT,version TEXT,PRIMARY KEY(video_id,coder,version));
CREATE TABLE IF NOT EXISTS annotations(id INTEGER PRIMARY KEY,video_id TEXT,coder TEXT,version TEXT,payload TEXT,created TEXT);
CREATE TABLE IF NOT EXISTS finals(id INTEGER PRIMARY KEY,video_id TEXT,version TEXT,payload TEXT,created TEXT);
CREATE TABLE IF NOT EXISTS model_runs(id INTEGER PRIMARY KEY,video_id TEXT,model TEXT,config_hash TEXT,prompt_hash TEXT,version TEXT,created TEXT,ok INTEGER,payload TEXT,error TEXT);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,action TEXT,detail TEXT,created TEXT);
'''
DEFAULT_EXTRA={'title':'Who Gets Synthesised?','version':'1.0','thresholds':{'videos':100,'channels':5,'verified':50,'alpha':0.67,'reliability_n':50},'permissions':{'ethics':False,'collection':False,'analysis':False,'gemini':False,'export':False},'literature':'pending','literature_note':'','search_limit':100,'general_limit':10000,'study_notes':'Ordinary speaking synthetic personas; exclude identifiable real-person deepfakes, cartoons and genuine footage. Reposts grouped.'}
VIDEO_FIELDS={'format':['street_interview','single_testimonial','montage','skit','news_style','other','unknown'],'genre':['persuasive','satirical','other','unknown'],'interviewer':['yes','no','unknown'],'news_brand':['yes','no','unknown'],'captions':['yes','no','unknown'],'authenticity':'text','frame':'text','notes':'text'}
PERSONA_FIELDS={'gender':['male','female','other','unknown'],'age':['child','young_adult','middle_aged','elderly','unknown'],'setting':['rural','urban','unknown'],'disability_marker':['yes','no','unknown'],'visible_markers':'text','occupation_markers':'text','stated_identity':'text','transcript_bn':'text','party_mention':'text','endorsement':'text','attack':'text','issues':'text','factual_claim':'text','emotion':['none','fear','anger','hope','pride','humour','grievance','other','unknown'],'voice':['personal','collective','none','unknown'],'dialect':'text','notes':'text'}
KINDS=['fact_check','creator_disclosure','platform_label','visual_judgment','provenance','watermark','other']
def now(): return db.utcnow()
def dumps(x): return json.dumps(x,ensure_ascii=False,sort_keys=True)
def hashval(x): return hashlib.sha256(dumps(x).encode()).hexdigest()
def connect(path):
    c=db.connect(path); c.execute('PRAGMA busy_timeout=10000'); c.execute('PRAGMA journal_mode=WAL'); c.executescript(SCHEMA); c.commit(); return c
def get(c,k,default=None):
    r=c.execute('SELECT v FROM settings WHERE k=?',(k,)).fetchone();return json.loads(r[0]) if r else default
def put(c,k,v): c.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v',(k,dumps(v)));c.commit()
def config(c):
    cfg=load_config(ROOT/'config.yaml');cfg['search']['video_duration']='any';cfg['gemini']['model']='';cfg.update(json.loads(dumps(DEFAULT_EXTRA)));return get(c,'config',cfg)
def audit(c,a,d):c.execute('INSERT INTO audit(action,detail,created) VALUES(?,?,?)',(a,dumps(d),now()));c.commit()
def asrows(c,q,p=()):return [dict(r) for r in c.execute(q,p)]
def register(c,vid,source,detail):
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}',vid): raise ValueError('Invalid video ID')
    c.execute('INSERT OR IGNORE INTO inventory(video_id,group_id) VALUES(?,?)',(vid,vid));db.add_discovery(c,vid,source,detail)
    c.commit()
def cutoff(cfg):return (datetime.now(timezone.utc)-timedelta(days=min(30,int(cfg['storage']['api_data_max_age_days'])))).isoformat()
def purge(c,cfg,vid=None):
    # Keep identity keys in inventory only as restricted locator records pending permission.
    q='video_id=?' if vid else '(fetched_at IS NULL OR fetched_at<?)';p=(vid or cutoff(cfg),)
    ids=[r[0] for r in c.execute('SELECT video_id FROM videos WHERE '+q,p)]
    for v in ids:
        c.execute('DELETE FROM videos WHERE video_id=?',(v,));c.execute('DELETE FROM prescreen WHERE video_id=?',(v,));c.execute("UPDATE inventory SET retrieval=CASE WHEN retrieval='unavailable' THEN retrieval ELSE 'stale' END WHERE video_id=?",(v,))
    c.execute('DELETE FROM channels WHERE fetched_at<?',(cutoff(cfg),));c.commit();return len(ids)
def ingest(c,cfg,client,ids):
    for batch in chunks(list(dict.fromkeys(ids)),50):
        items={i['id']:i for i in client.videos(batch)}
        for vid in batch:
            item=items.get(vid)
            if not item:
                purge(c,cfg,vid);c.execute("UPDATE inventory SET retrieval='unavailable',checked=? WHERE video_id=?",(now(),vid));db.record_availability(c,vid,'not_returned');continue
            db.upsert_video(c,item,parse_iso_duration(item.get('contentDetails',{}).get('duration')))
            v=dict(c.execute('SELECT * FROM videos WHERE video_id=?',(vid,)).fetchone());db.save_prescreen(c,vid,prescreen_video(v,cfg))
            c.execute('UPDATE inventory SET retrieval=?,checked=? WHERE video_id=?',(v['privacy_status'] or 'unknown',now(),vid));db.record_availability(c,vid,v['privacy_status'] or 'unknown')
        c.commit()
def client_for(c,cfg,key,check):
    client=YouTubeClient(key)
    def request(endpoint):
        check()
        # Pacific date rather than UTC for quota resets.
        from zoneinfo import ZoneInfo
        tz=ZoneInfo('America/Los_Angeles');start=datetime.now(tz).replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc).isoformat()
        search=endpoint=='search';n=c.execute('SELECT COUNT(*) FROM request_log WHERE at>=? AND '+('endpoint=\'search\'' if search else 'endpoint<>\'search\''),(start,)).fetchone()[0]
        if n>=cfg['search_limit' if search else 'general_limit']:raise ValueError('Local daily request budget reached. Resume after quota reset.')
        c.execute('INSERT INTO request_log(endpoint,at) VALUES(?,?)',(endpoint,now()));c.commit()
    client.on_request=request;return client

def search(c,cfg,client,max_calls,check,progress):
    s=cfg['search']; p=cfg['study_period']; calls=0
    for query in s['queries']:
      for order in s['orders']:
       for after,before in collect.month_windows(p['start'],p['end'],p['timezone_offset_hours']):
        spec=[query,order,after,before,s['region_code'],s['relevance_language'],s['video_duration'],s['max_pages_per_query']];key='search:'+hashval(spec)
        cp=c.execute('SELECT * FROM checkpoints WHERE job_key=?',(key,)).fetchone();token=cp['token'] if cp else None;pages=cp['pages'] if cp else 0
        if cp and cp['done']:continue
        while calls<max_calls and pages<int(s['max_pages_per_query']):
            check();data=client.search(query,after,before,order,s['region_code'],s['relevance_language'],s['video_duration'],token);calls+=1;pages+=1
            items=data.get('items',[]);ids=[]
            for item in items:
                vid=item.get('id',{}).get('videoId')
                if vid:register(c,vid,'search',dumps({'query':query,'order':order,'after':after,'before':before,'page':pages,'key':key}));ids.append(vid)
            token=data.get('nextPageToken');done=not token or pages>=int(s['max_pages_per_query']);c.execute('INSERT OR REPLACE INTO checkpoints VALUES(?,?,?,?,?)',(key,token,pages,int(done),now()));c.execute('INSERT INTO search_log(query,order_by,published_after,published_before,page,result_count,total_results,run_at) VALUES(?,?,?,?,?,?,?,?)',(query,order,after,before,pages,len(items),data.get('pageInfo',{}).get('totalResults'),now()));c.commit()
            progress(f'{calls} search pages; {query}; {after[:10]}; '+('page cap reached' if token and done else ''))
            if ids:ingest(c,cfg,client,ids)
            if done:break
        if calls>=max_calls:return
    progress('All configured search windows processed (subject to page caps and API coverage).')
def expand(c,cfg,client,check,progress):
    ids=list(cfg['seeds']['channel_ids']);vids=[]
    for value in cfg['seeds']['videos']:
        vid=extract_video_id(value)
        if vid:register(c,vid,'seed','configured video');vids.append(vid)
    if vids:
        ingest(c,cfg,client,vids);ids += [r[0] for r in c.execute('SELECT channel_id FROM videos WHERE video_id IN ('+','.join('?'*len(vids))+')',vids) if r[0]]
    for handle in cfg['seeds']['handles']:
        item=client.channel_by_handle(handle)
        if item:ids.append(item['id'])
        else:progress('Handle not returned: '+handle)
    for ch in client.channels_by_id(list(dict.fromkeys(ids))):
        db.upsert_channel(c,ch,True);c.commit();playlist=ch.get('contentDetails',{}).get('relatedPlaylists',{}).get('uploads')
        if not playlist:continue
        key='playlist:'+hashval([playlist,cfg['study_period']]);cp=c.execute('SELECT * FROM checkpoints WHERE job_key=?',(key,)).fetchone();token=cp['token'] if cp else None;pages=cp['pages'] if cp else 0
        if cp and cp['done']:continue
        while True:
            check();data=client.get('playlistItems',part='contentDetails',playlistId=playlist,maxResults=50,pageToken=token);pages+=1;vids=[]
            for item in data.get('items',[]):
                d=item.get('contentDetails',{});vid=d.get('videoId');published=d.get('videoPublishedAt')
                if vid and (not published or in_period(published,cfg['study_period'])):register(c,vid,'channel_expansion',ch['id']);vids.append(vid)
            next_token=data.get('nextPageToken');c.execute('INSERT OR REPLACE INTO checkpoints VALUES(?,?,?,?,?)',(key,next_token,pages,int(not next_token),now()));c.commit();progress(f'{ch["id"]}: {pages} playlist pages')
            if vids:ingest(c,cfg,client,vids)
            if not next_token:break
            if next_token==token:raise ValueError('Repeated playlist token; coverage incomplete')
            token=next_token

def library(c,cfg):
    q='''SELECT i.*,v.title,v.channel_id,v.channel_title,v.published_at,v.duration_seconds,v.fetched_at,v.synthetic_field_present,v.contains_synthetic_media,p.in_period,p.election_hits,p.ai_hits,p.is_short, (SELECT COUNT(*) FROM evidence e WHERE e.video_id=i.video_id) evidence_count FROM inventory i LEFT JOIN videos v USING(video_id) LEFT JOIN prescreen p USING(video_id) ORDER BY CASE WHEN p.election_hits!='[]' AND p.ai_hits!='[]' THEN 0 WHEN p.election_hits!='[]' OR p.ai_hits!='[]' THEN 1 ELSE 2 END,i.video_id'''
    out=asrows(c,q)
    for r in out:
        r['priority']='unknown' if r['in_period'] is None else ('high' if r['election_hits']!='[]' and r['ai_hits']!='[]' else 'medium' if r['election_hits']!='[]' or r['ai_hits']!='[]' else 'low');r['fresh']=bool(r['fetched_at'] and r['fetched_at']>=cutoff(cfg));r['active']=bool(r['fresh'] and r['retrieval']=='public' and r['in_period']);r['flag']='absent' if not r['synthetic_field_present'] else ('null' if r['contains_synthetic_media'] is None else str(bool(r['contains_synthetic_media'])).lower())
    return out

def validate_annotation(a,duration=None):
    if a.get('origin_judgment','uncertain') not in ['suspected_synthetic','suspected_genuine','uncertain']:raise ValueError('Invalid origin judgment')
    if a.get('eligibility') not in ['eligible','excluded','uncertain']:raise ValueError('Select eligibility')
    if a['eligibility']=='excluded' and not a.get('reason','').strip():raise ValueError('Exclusion reason required')
    def codes(data,fields):
        if not isinstance(data,dict):raise ValueError('Codes must be an object')
        for k,v in data.items():
            if k not in fields:raise ValueError('Unknown code '+k)
            if isinstance(fields[k],list) and v not in fields[k]+['missing','not_applicable','uncertain']:raise ValueError('Invalid code '+k)
            if fields[k]=='text' and not isinstance(v,str):raise ValueError('Text required for '+k)
    codes(a.get('video',{}),VIDEO_FIELDS);seen=set()
    for p in a.get('personas',[]):
        pid=str(p.get('id','')).strip()
        if not pid or pid in seen:raise ValueError('Unique persona ID required')
        seen.add(pid);codes(p.get('codes',{}),PERSONA_FIELDS)
        start,end=p.get('start'),p.get('end')
        for v in (start,end):
            if v is not None and (not isinstance(v,(int,float)) or isinstance(v,bool) or v<0 or (duration is not None and v>duration)):raise ValueError('Invalid persona timestamp')
        if start is not None and end is not None and start>end:raise ValueError('Reversed timestamp')
    if a['eligibility']=='eligible' and not seen:raise ValueError('Eligible video requires at least one speaking persona')
    return a

def latest(c,table,version):
    return asrows(c,f'SELECT a.* FROM {table} a JOIN (SELECT video_id,'+('coder,' if table=='annotations' else '')+f'MAX(id) id FROM {table} WHERE version=? GROUP BY video_id'+(',coder' if table=='annotations' else '')+') b ON a.id=b.id',(version,))
def level(c,vid):
    # Only explicitly persona-linked or all-speaking-personas evidence with rationale qualifies.
    ev=asrows(c,'SELECT * FROM evidence WHERE video_id=?',(vid,)); good=[e for e in ev if e['note'].strip() and e['persona']=='all' and e['source'].strip()]
    if any(e['kind']=='fact_check' for e in good):return 1
    if any(e['kind'] in ('creator_disclosure','platform_label') for e in good):return 2
    if any(e['kind']=='visual_judgment' for e in ev):
        version=config(c)['version']; a=[json.loads(r['payload']) for r in latest(c,'annotations',version) if r['video_id']==vid and r['coder']!='admin']
        if len([x for x in a if x.get('origin_judgment')=='suspected_synthetic'])>=2:return 3
    return 0

def alpha_nominal(groups):
    # Krippendorff nominal coincidence matrix, variable number of coders, missing dropped.
    counts=Counter(); total=0.; disagree=0.
    for vals in groups:
        vals=[v for v in vals if v not in (None,'','missing','not_applicable','unknown','uncertain')];m=len(vals)
        if m<2:continue
        ct=Counter(vals);total+=m;counts.update(ct);disagree+=(m*m-sum(n*n for n in ct.values()))/(m-1)
    if total<2:return None
    expected=(total*total-sum(n*n for n in counts.values()))/(total-1)
    return None if expected==0 else 1-disagree/expected

def reliability(c,cfg):
    by=defaultdict(list)
    assigned={(r['video_id'],r['coder']) for r in c.execute('SELECT video_id,coder FROM assignments WHERE version=?',(cfg['version'],))}
    for r in latest(c,'annotations',cfg['version']):
        if (r['video_id'],r['coder']) in assigned:by[r['video_id']].append(json.loads(r['payload']))
    pairs={k:v for k,v in by.items() if len(v)>=2};out={}
    for field in ['eligibility','origin_judgment']+[k for k,v in VIDEO_FIELDS.items() if isinstance(v,list)]:
        groups=[[a.get('eligibility') if field=='eligibility' else a.get('origin_judgment') if field=='origin_judgment' else a.get('video',{}).get(field) for a in vals] for vals in pairs.values()];out[field]={'alpha':alpha_nominal(groups),'units':sum(sum(v not in (None,'','missing','not_applicable','unknown','uncertain') for v in g)>=2 for g in groups)}
    # Matching requires independent coders to use shared persona IDs, reviewed by admin.
    for field in ['gender','age','endorsement']:
        groups=[]
        for vals in pairs.values():
            ids=set.intersection(*(set(str(p['id']) for p in a.get('personas',[])) for a in vals))
            for pid in ids:groups.append([next(p for p in a['personas'] if str(p['id'])==pid).get('codes',{}).get(field) for a in vals])
        out[field]={'alpha':alpha_nominal(groups),'units':sum(sum(v not in (None,'','missing','not_applicable','unknown','uncertain') for v in g)>=2 for g in groups)}
    return {'double_coded':len(pairs),'variables':out,'warning':'Persona matching uses shared IDs; verify correspondence before interpreting alpha. Constant variables yield undefined alpha.'}
def report(c,cfg):
    lib=library(c,cfg);lookup={r['video_id']:r for r in lib};finals=latest(c,'finals',cfg['version']);groups={};channels=set();dist=Counter();labels=Counter();excluded=0;by_channel=Counter();by_level=defaultdict(Counter);messages=Counter();formats=Counter()
    for f in finals:
        a=json.loads(f['payload']);r=lookup.get(f['video_id'],{});v=f['video_id'];
        if a['eligibility']=='excluded':excluded+=1
        if a['eligibility']!='eligible' or not r.get('active') or r.get('playback')!='viewable' or not r.get('playback_at') or r['playback_at']<cutoff(cfg):continue
        lev=level(c,v)
        if not lev:continue
        g=r['group_id'] or v
        # representative: prefer stronger evidence; deterministic ID tie break
        if g not in groups or (lev,v)<(groups[g][0],groups[g][1]):groups[g]=(lev,v,a)
        if r.get('channel_id'):channels.add(r['channel_id'])
    for lev,v,a in groups.values():
        by_channel[lookup[v].get('channel_id') or 'unknown']+=1
        formats[a.get('video',{}).get('format','missing')]+=1
        for p in a.get('personas',[]):
            codes=p.get('codes',{});dist['age:'+codes.get('age','missing')]+=1;dist['gender:'+codes.get('gender','missing')]+=1;dist['setting:'+codes.get('setting','missing')]+=1
            by_level[str(lev)]['age:'+codes.get('age','missing')]+=1
            for k in ('endorsement','attack','factual_claim','issues'):
                if codes.get(k,'').strip():messages[k]+=1
        if lev in (1,3):labels[lookup[v].get('platform_label','unknown')]+=1
    n=len(groups);verified=sum(x[0] in (1,2) for x in groups.values());rel=reliability(c,cfg);t=cfg['thresholds'];critical=[rel['variables'][k]['alpha'] for k in ['gender','age','endorsement']]
    cond={'eligible_unique': n>=t['videos'],'channels':len(channels)>=t['channels'],'verified_share':None if not n else verified/n*100>=t['verified'],'reliability':None if rel['double_coded']<t['reliability_n'] or any(x is None for x in critical) else all(x>=t['alpha'] for x in critical),'literature':True if cfg['literature']=='clear' and cfg['literature_note'].strip() else False if cfg['literature']=='overlap' else None,'permissions':all(cfg['permissions'][k] for k in ['ethics','collection','analysis'])}
    return {'discovered':len(lib),'active':sum(r['active'] for r in lib),'unavailable':sum(r['retrieval']=='unavailable' for r in lib),'screened':c.execute('SELECT COUNT(DISTINCT video_id) FROM model_runs WHERE ok=1').fetchone()[0],'finalized':len(finals),'excluded':excluded,'eligible_unique':n,'channels':len(channels),'verified':verified,'verified_pct':round(verified/n*100,2) if n else None,'conditions':cond,'decision':'MET' if all(v is True for v in cond.values()) else 'NOT ESTABLISHED','reliability':rel,'distributions':dict(dist),'label_observations_level_1_3':dict(labels),'evidence_levels':dict(Counter(x[0] for x in groups.values())),'formats':dict(formats),'message_counts':dict(messages),'age_by_evidence_level':{k:dict(v) for k,v in by_level.items()},'channel_concentration':{'distinct_representative_channels':len(by_channel),'largest_channel_count':max(by_channel.values(),default=0),'leave_largest_channel_out_n':n-max(by_channel.values(),default=0)},'note':'Counts refer to discoverable current corpus, not platform census. Duplicate grouping and evidence assessments require human review.'}
