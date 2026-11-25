import json, hashlib, copy
import pytest
from fastapi.testclient import TestClient
from webapp import core as C
from pilot import gemini_screen
from pilot.youtube import YouTubeClient
from test_pipeline import fake_api, GOOD, video_item
import httpx

@pytest.fixture
def data(tmp_path):
    c=C.connect(tmp_path/'test.db');cfg=C.config(c)
    cfg['seeds']={'videos':[],'handles':[],'channel_ids':['UC_one']};cfg['search']['queries']=['জনমত'];cfg['search']['orders']=['relevance'];cfg['thresholds'].update(videos=1,channels=1,reliability_n=1)
    client=YouTubeClient('test-key',transport=httpx.MockTransport(fake_api([])),sleep=lambda _:None)
    yield c,cfg,client
    c.close();client.close()

def test_resumable_search_and_multiple_provenance(data):
    c,cfg,client=data
    for _ in range(2):C.search(c,cfg,client,2,lambda:None,lambda _:None)
    assert c.execute('SELECT COUNT(*) FROM checkpoints WHERE done=1').fetchone()[0]==4
    assert c.execute('SELECT COUNT(*) FROM discovery').fetchone()[0]==4
    assert client.search_calls==4

def test_expand_missing_record_long_video_and_resume(data):
    c,cfg,client=data;C.expand(c,cfg,client,lambda:None,lambda _:None)
    lib={x['video_id']:x for x in C.library(c,cfg)}
    assert lib['GONEGONEGO6']['retrieval']=='unavailable'
    assert lib['AAAAAAAAAA3']['active'] and lib['AAAAAAAAAA3']['duration_seconds']==480
    assert lib['AAAAAAAAAA2']['active']
    assert c.execute('SELECT pages FROM checkpoints').fetchone()[0]==2
    C.expand(c,cfg,client,lambda:None,lambda _:None)
    assert c.execute('SELECT pages FROM checkpoints').fetchone()[0]==2

def test_purge_excludes_stale(data):
    c,cfg,client=data;C.expand(c,cfg,client,lambda:None,lambda _:None)
    c.execute("UPDATE videos SET fetched_at='2020-01-01T00:00:00+00:00'");c.commit()
    assert not any(x['active'] for x in C.library(c,cfg));assert C.purge(c,cfg)==4
    assert c.execute('SELECT COUNT(*) FROM videos').fetchone()[0]==0
    assert len(C.library(c,cfg))==5

def test_failed_hydration_preserves_discovery(data):
    c,cfg,_=data
    class Client:
        def search(self,*args):return {'items':[{'id':{'videoId':'AAAAAAAAAA1'}}]}
        def videos(self,*args):raise RuntimeError('network')
    with pytest.raises(RuntimeError):C.search(c,cfg,Client(),1,lambda:None,lambda _:None)
    assert c.execute('SELECT retrieval FROM inventory').fetchone()[0]=='pending'
    assert c.execute('SELECT done FROM checkpoints').fetchone()[0]==1

def test_model_invalid_categories_timestamps_duplicate():
    for change in ('enum','time','repeat'):
        g=copy.deepcopy(GOOD)
        if change=='enum':g['format']='nonsense'
        if change=='time':g['personas'][0]['start_time']='99:99'
        if change=='repeat':g['personas'].append(copy.deepcopy(g['personas'][0]))
        with pytest.raises(Exception):gemini_screen.parse_output(json.dumps(g),12)
    with pytest.raises(Exception):gemini_screen.parse_output(json.dumps(GOOD),4)

def test_missing_null_false_synthetic(data):
    c,cfg,_=data
    for i,status in enumerate([{}, {'containsSyntheticMedia':None},{'containsSyntheticMedia':False},{'containsSyntheticMedia':True}]):
        vid='AAAAAAAAAA'+str(i);item=video_item(vid);item['status'].update(status);C.register(c,vid,'manual','');C.db.upsert_video(c,item,12)
    assert [x['flag'] for x in C.library(c,cfg)]==['absent','null','false','true']

def test_alpha_known_values():
    assert C.alpha_nominal([['a','a'],['b','b']])==1
    assert C.alpha_nominal([['a','a'],['a','a']]) is None
    assert C.alpha_nominal([['a','b'],['a','b']])==pytest.approx(-.5)

def test_feasibility_needs_final_evidence_viewing(data):
    c,cfg,client=data;C.expand(c,cfg,client,lambda:None,lambda _:None)
    assert C.report(c,cfg)['eligible_unique']==0
    v='AAAAAAAAAA1';a={'eligibility':'eligible','video':{},'personas':[{'id':'1','codes':{'age':'elderly'}}]}
    c.execute('INSERT INTO finals(video_id,version,payload,created) VALUES(?,?,?,?)',(v,cfg['version'],C.dumps(a),C.now()))
    c.execute("UPDATE inventory SET playback='viewable',playback_at=? WHERE video_id=?",(C.now(),v));c.commit();assert C.report(c,cfg)['eligible_unique']==0
    c.execute('INSERT INTO evidence(video_id,kind,source,observed,persona,note) VALUES(?,?,?,?,?,?)',(v,'fact_check','https://example.org','2026-01-01','all','Test fixture evidence'))
    c.commit();r=C.report(c,cfg);assert r['eligible_unique']==1 and r['verified']==1 and r['decision']=='NOT ESTABLISHED'

def test_annotation_rejects_missing_persona_and_out_of_range():
    with pytest.raises(ValueError):C.validate_annotation({'eligibility':'eligible','personas':[]})
    with pytest.raises(ValueError):C.validate_annotation({'eligibility':'eligible','personas':[{'id':'1','end':20}]},10)

def test_retry_attempts_count():
    calls=[]
    def fake(req):
        calls.append(1);return httpx.Response(503 if len(calls)==1 else 200,json={'items':[]})
    cl=YouTubeClient('test',transport=httpx.MockTransport(fake),sleep=lambda _:None);cl.videos(['AAAAAAAAAA1']);assert cl.general_calls==2

@pytest.fixture
def api(tmp_path,monkeypatch):
    # Test storage must be isolated from the distributed application.
    monkeypatch.setenv('RESEARCH_DATA',str(tmp_path/'appdata'))
    from webapp import server
    monkeypatch.setattr(server,'DB',tmp_path/'http.db')
    with TestClient(server.app) as cl:yield cl,server,{'Authorization':'Bearer '+server.TOKEN}

def test_api_ui_and_isolation(api):
    cl,s,h=api
    assert cl.get('/').status_code==200
    assert cl.get('/api/config').status_code==401
    assert cl.get('/api/config',headers={**h,'Origin':'https://example.org'}).status_code==403
    cfg=cl.get('/api/config',headers=h).json();cfg['permissions']['analysis']=True
    assert cl.post('/api/config',headers=h,json=cfg).status_code==200
    assert cl.post('/api/import',headers=h,json={'text':'AAAAAAAAAA1\ninvalid link'}).json()['accepted']==1
    cr=cl.post('/api/coders',headers=h,json={'name':'coderA'}).json();ch={'Authorization':'Bearer '+cr['token']}
    assert cl.get('/api/library',headers=ch).status_code==403
    assert cl.get('/api/video/AAAAAAAAAA1',headers=ch).status_code==403
    with s.cx() as c:
        c.execute('INSERT INTO assignments VALUES(?,?,?)',('AAAAAAAAAA1','coderA',cfg['version']));c.commit()
    d=cl.get('/api/video/AAAAAAAAAA1',headers=ch).json();assert set(d)=={'video_id','own_annotation','version'}
    assert cl.post('/api/video/AAAAAAAAAA1/annotation',headers=ch,json={'version':cfg['version'],'final':True,'payload':{'eligibility':'uncertain','personas':[]}}).status_code==200
    assert cl.get('/api/video/AAAAAAAAAA1',headers=h).json()['final'] is None
    assert cl.get('/api/export/json',headers=h).status_code==403
    assert cl.get('/api/report',headers=h).json()['eligible_unique']==0

def test_job_permissions(api):
    cl,s,h=api
    assert cl.post('/api/jobs',headers=h,json={'kind':'search','limit':1}).status_code==200
    import time
    for _ in range(30):
        r=cl.get('/api/jobs',headers=h).json()[0]
        if r['state']=='failed':break
        time.sleep(.1)
    assert r['state']=='failed' and 'permission' in r['error']
