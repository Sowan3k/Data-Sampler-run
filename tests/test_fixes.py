"""Tests for the 0.3.0 fixes: corpus locking, availability as an outcome, sample pool,
alpha missing-data rules, categorical codebook, Gemini error detail, timestamps,
duration cap and evidence scope."""
import json, time

import httpx
import pytest
from fastapi.testclient import TestClient

from webapp import core as C
from pilot import gemini_screen
from pilot.youtube import YouTubeClient
from test_pipeline import fake_api, GOOD, VIDEOS


def fake_client():
    return YouTubeClient('test-key', transport=httpx.MockTransport(fake_api([])), sleep=lambda _: None)


@pytest.fixture
def corpus(tmp_path):
    c = C.connect(tmp_path / 'fix.db'); cfg = C.config(c)
    cfg['seeds'] = {'videos': [], 'handles': [], 'channel_ids': ['UC_one']}
    cfg['thresholds'].update(videos=1, channels=1, reliability_n=1)
    client = fake_client()
    C.expand(c, cfg, client, lambda: None, lambda _: None)
    yield c, cfg, client
    c.close(); client.close()


def code_eligible(c, cfg, vid, level_kind='fact_check'):
    a = {'eligibility': 'eligible', 'origin_judgment': 'suspected_synthetic', 'video': {'party_favoured': 'bnp'},
         'personas': [{'id': '1', 'codes': {'gender': 'male', 'endorses_party': 'bnp'}}]}
    c.execute('INSERT INTO finals(video_id,version,payload,created) VALUES(?,?,?,?)', (vid, cfg['version'], C.dumps(a), C.now()))
    c.execute('INSERT INTO evidence(video_id,kind,source,observed,persona,note) VALUES(?,?,?,?,?,?)',
              (vid, level_kind, 'https://example.org/check', '2026-01-20', 'all', 'fixture evidence'))
    c.commit()


# --- 1. corpus locking and availability --------------------------------------

def test_coded_video_stays_in_corpus_after_old_playback_and_removal(corpus):
    c, cfg, client = corpus
    vid = 'AAAAAAAAAA1'
    code_eligible(c, cfg, vid)
    c.execute("UPDATE inventory SET playback='viewable', playback_at='2020-01-01T00:00:00+00:00' WHERE video_id=?", (vid,)); c.commit()
    r = C.report(c, cfg)
    assert r['eligible_unique'] == 1 and r['eligible_available'] == 1      # an old playback check no longer drops it
    backup = VIDEOS.pop(vid)
    try:
        C.ingest(c, cfg, client, [vid])                                       # video no longer returned by the API
    finally:
        VIDEOS[vid] = backup
    r = C.report(c, cfg)
    assert r['eligible_unique'] == 1                                          # still in the coded corpus
    assert r['eligible_available'] == 0 and r['availability'] == {'unavailable': 1}
    assert r['conditions']['eligible_available'] is False                     # the pilot gate counts available videos


def test_channel_locator_survives_metadata_purge(corpus):
    c, cfg, _ = corpus
    code_eligible(c, cfg, 'AAAAAAAAAA1')
    c.execute("UPDATE videos SET fetched_at='2020-01-01T00:00:00+00:00'"); c.execute("UPDATE channels SET fetched_at='2020-01-01T00:00:00+00:00'"); c.commit()
    assert C.purge(c, cfg) == 4
    assert c.execute('SELECT COUNT(*) FROM videos').fetchone()[0] == 0
    row = next(x for x in C.library(c, cfg) if x['video_id'] == 'AAAAAAAAAA1')
    assert row['channel_id'] == 'UC_one' and row['title'] is None and row['availability'] == 'public'
    r = C.report(c, cfg)
    assert r['eligible_unique'] == 1 and r['channels'] == 1 and r['channels_available'] == 1


def test_known_out_of_period_upload_is_not_counted(corpus):
    c, cfg, client = corpus
    C.register(c, 'AAAAAAAAAA4', 'manual', ''); C.ingest(c, cfg, client, ['AAAAAAAAAA4'])
    code_eligible(c, cfg, 'AAAAAAAAAA4')
    assert C.report(c, cfg)['eligible_unique'] == 0


def test_repost_group_available_if_any_member_is(corpus):
    c, cfg, client = corpus
    code_eligible(c, cfg, 'AAAAAAAAAA1')
    c.execute("UPDATE inventory SET group_id='AAAAAAAAAA1' WHERE video_id='AAAAAAAAAA5'"); c.commit()
    backup = VIDEOS.pop('AAAAAAAAAA1')
    try:
        C.ingest(c, cfg, client, ['AAAAAAAAAA1'])
    finally:
        VIDEOS['AAAAAAAAAA1'] = backup
    r = C.report(c, cfg)
    assert r['eligible_unique'] == 1 and r['eligible_available'] == 1


def test_report_counts_party_and_label_prevalence_only_from_level_1_and_3(corpus):
    c, cfg, _ = corpus
    code_eligible(c, cfg, 'AAAAAAAAAA1', 'fact_check')
    code_eligible(c, cfg, 'AAAAAAAAAA5', 'platform_label')
    r = C.report(c, cfg)
    assert r['party_favoured'] == {'bnp': 2} and r['message_counts']['endorsement'] == 2
    assert r['label_observations_level_1_3'] == {'platform:unknown': 1, 'creator:unknown': 1}


# --- 2. reliability sample pool and alpha ------------------------------------

def test_sample_pool_only_screened_eligible_canonical_available(corpus):
    c, cfg, _ = corpus
    assert C.screened_eligible(c, cfg) == []
    c.execute("UPDATE inventory SET screening='eligible' WHERE video_id IN ('AAAAAAAAAA1','AAAAAAAAAA5','GONEGONEGO6')")
    c.execute("UPDATE inventory SET group_id='AAAAAAAAAA1' WHERE video_id='AAAAAAAAAA5'"); c.commit()
    pool = [r['video_id'] for r in C.screened_eligible(c, cfg)]
    assert pool == ['AAAAAAAAAA1']        # repost and unavailable lead excluded, unscreened uploads excluded


def test_alpha_strict_keeps_unknown_as_category():
    groups = [['a', 'a'], ['b', 'b'], ['a', 'unknown'], ['b', 'uncertain']]
    loose = C.alpha_nominal(groups, C.LOOSE_DROP); strict = C.alpha_nominal(groups)
    assert loose == 1 and strict < 1


def test_reliability_gate_uses_strict_alpha(corpus):
    c, cfg, _ = corpus
    for name in ('coderA', 'coderB'):
        c.execute('INSERT INTO assignments VALUES(?,?,?)', ('AAAAAAAAAA1', name, cfg['version']))
    payloads = {'coderA': {'gender': 'male', 'age': 'elderly', 'endorses_party': 'bnp'},
                'coderB': {'gender': 'male', 'age': 'unknown', 'endorses_party': 'bnp'}}
    for name, codes in payloads.items():
        a = {'eligibility': 'eligible', 'origin_judgment': 'uncertain', 'video': {}, 'personas': [{'id': '1', 'codes': codes}]}
        c.execute('INSERT INTO annotations(video_id,coder,version,payload,created) VALUES(?,?,?,?,?)', ('AAAAAAAAAA1', name, cfg['version'], C.dumps(a), C.now()))
    c.commit()
    rel = C.reliability(c, cfg)
    assert rel['variables']['age']['units'] == 1 and rel['variables']['age']['units_excluding_uncertain'] == 0
    assert 'endorses_party' in rel['variables'] and 'endorsement' not in rel['variables']


# --- 3. categorical codebook ---------------------------------------------------

def test_codebook_is_categorical_for_counted_variables():
    for k in ('endorses_party', 'attacks_party', 'visible_religion', 'stated_religion', 'visible_occupation', 'stated_occupation', 'factual_claim'):
        assert isinstance(C.PERSONA_FIELDS[k], list), k
    for k in ('party_favoured', 'uniforms', 'regional_dialect', 'production_artifacts'):
        assert isinstance(C.VIDEO_FIELDS[k], list), k
    ok = {'eligibility': 'eligible', 'video': {'party_favoured': 'jamaat'}, 'personas': [{'id': '1', 'codes': {'endorses_party': 'jamaat', 'visible_religion': 'hindu'}}]}
    C.validate_annotation(ok)
    with pytest.raises(ValueError):
        C.validate_annotation({'eligibility': 'eligible', 'personas': [{'id': '1', 'codes': {'endorses_party': 'BNP'}}]})
    with pytest.raises(ValueError):
        C.validate_annotation({'eligibility': 'eligible', 'personas': [{'id': '1', 'codes': {'endorsement': 'BNP'}}]})


# --- 4. Gemini timestamps -------------------------------------------------------

@pytest.mark.parametrize('stamp,ok', [('0:04', True), ('00:04', True), ('0:04.5', True), ('1:02:03', True), ('00:99', False), ('4s', False)])
def test_timestamp_formats(stamp, ok):
    g = json.loads(json.dumps(GOOD)); g['artifact_observations'][0]['time'] = stamp
    if ok:
        gemini_screen.parse_output(json.dumps(g))
    else:
        with pytest.raises(ValueError):
            gemini_screen.parse_output(json.dumps(g))


def test_redact_removes_key_like_strings():
    out = gemini_screen.redact('400 bad request key=AIzaSyFAKEFAKEFAKEFAKEFAKE1234 for models/x')
    assert 'AIza' not in out and 'models/x' in out


# --- HTTP: screening, evidence scope, sample errors, Gemini job ------------------

@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv('RESEARCH_DATA', str(tmp_path / 'appdata'))
    from webapp import server
    monkeypatch.setattr(server, 'DB', tmp_path / 'http.db')
    with TestClient(server.app) as cl:
        yield cl, server, {'Authorization': 'Bearer ' + server.TOKEN}


def seed_server(s, cfg_changes=None):
    with s.cx() as c:
        cfg = C.config(c); cfg['seeds'] = {'videos': [], 'handles': [], 'channel_ids': ['UC_one']}
        client = fake_client(); C.expand(c, cfg, client, lambda: None, lambda _: None); client.close()


def test_screening_decision_and_sample_pool(api):
    cl, s, h = api
    seed_server(s)
    for name in ('coderA', 'coderB'):
        cl.post('/api/coders', headers=h, json={'name': name})
    r = cl.post('/api/assign', headers=h, json={'coders': ['coderA', 'coderB'], 'n': 5, 'seed': 1})
    assert r.status_code == 400 and 'screened-eligible' in r.json()['detail']
    base = {'playback': 'viewable', 'creator_label': 'unknown', 'platform_label': 'unknown', 'group_id': 'AAAAAAAAAA1'}
    assert cl.post('/api/video/AAAAAAAAAA1/observe', headers=h, json={**base, 'screening': 'excluded'}).status_code == 400
    assert cl.post('/api/video/AAAAAAAAAA1/observe', headers=h, json={**base, 'screening': 'eligible'}).status_code == 200
    r = cl.post('/api/assign', headers=h, json={'coders': ['coderA', 'coderB'], 'n': 5, 'seed': 1}).json()
    assert r == {'assigned': 1, 'pool': 1}


def test_evidence_scope_must_be_a_listed_choice(api):
    cl, s, h = api
    seed_server(s)
    body = {'kind': 'fact_check', 'source': 'https://example.org', 'observed': '2026-01-01', 'note': 'rated AI'}
    assert cl.post('/api/video/AAAAAAAAAA1/evidence', headers=h, json={**body, 'persona': 'All'}).status_code == 400
    assert cl.post('/api/video/AAAAAAAAAA1/evidence', headers=h, json={**body, 'persona': 'all'}).status_code == 200


def test_gemini_job_skips_long_uploads_and_keeps_error_detail(api, monkeypatch):
    cl, s, h = api
    seed_server(s)
    cfg = cl.get('/api/config', headers=h).json()
    cfg['permissions']['gemini'] = True; cfg['gemini'].update(model='test-model', seconds_between_calls=0, max_duration_seconds=180)
    assert cl.post('/api/config', headers=h, json=cfg).status_code == 200
    monkeypatch.setitem(s.KEYS, 'gemini', 'AIzaSyFAKEFAKEFAKEFAKEFAKE1234')

    class Interactions:
        def create(self, **kw):
            raise RuntimeError('404 NOT_FOUND: models/test-model is not found. key=AIzaSyFAKEFAKEFAKEFAKEFAKE1234')

    class FakeClient:
        def __init__(self, api_key=None):
            self.interactions = Interactions()

    import google.genai
    monkeypatch.setattr(google.genai, 'Client', FakeClient)
    assert cl.post('/api/jobs', headers=h, json={'kind': 'gemini', 'limit': 10}).status_code == 200
    for _ in range(50):
        job = cl.get('/api/jobs', headers=h).json()[0]
        if job['state'] in ('completed', 'failed'):
            break
        time.sleep(.1)
    assert job['state'] == 'completed', job
    with s.cx() as c:
        runs = {r['video_id']: r['error'] for r in C.asrows(c, 'SELECT video_id,error FROM model_runs')}
    assert 'AAAAAAAAAA3' not in runs                      # 480-second upload skipped by the cap
    assert set(runs) == {'AAAAAAAAAA1', 'AAAAAAAAAA2', 'AAAAAAAAAA5'}
    assert all('NOT_FOUND' in e and 'AIza' not in e for e in runs.values())
    assert 'skipped' in job['progress']
