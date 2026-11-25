"""Regression and acceptance tests for 0.3.1."""
import csv, io, json, subprocess, sys, zipfile, zoneinfo

import httpx
import pytest
from fastapi.testclient import TestClient

from webapp import core as C, research as R, exports as X
from pilot.youtube import YouTubeClient
from test_pipeline import fake_api, VIDEOS

RULES = {'alpha': .67, 'min_pairs': 40, 'min_completeness': .8, 'reliability_n': 1, 'critical': C.CRITICAL_PERSONA}


def fake_client():
    return YouTubeClient('test-key', transport=httpx.MockTransport(fake_api([])), sleep=lambda _: None)


@pytest.fixture
def corpus(tmp_path):
    c = C.connect(tmp_path / 'v031.db'); cfg = C.config(c)
    cfg['seeds'] = {'videos': [], 'handles': [], 'channel_ids': ['UC_one']}
    cfg['thresholds'].update(videos=1, channels=1, reliability_n=1, min_pairs=1)
    cfg['permissions'].update(ethics=True, collection=True, analysis=True, export=True)
    client = fake_client(); C.expand(c, cfg, client, lambda: None, lambda _: None)
    yield c, cfg, client, tmp_path
    c.close(); client.close()


def adjudicate(c, cfg, vid, eligibility='eligible', evidence='fact_check', reason=None, codes=None, video=None):
    a = {'eligibility': eligibility, 'origin_judgment': 'suspected_synthetic', 'video': video or {'party_favoured': 'bnp', 'format': 'street_interview', 'news_brand': 'yes'},
         'personas': [{'id': '1', 'codes': codes or {'gender': 'male', 'age': 'elderly', 'endorses_party': 'bnp'}}]}
    if reason: a['exclusion_reason'] = reason
    c.execute('INSERT INTO finals(video_id,version,payload,created) VALUES(?,?,?,?)', (vid, cfg['version'], C.dumps(C.validate_annotation(a)), C.now()))
    if evidence: c.execute('INSERT INTO evidence(video_id,kind,source,observed,persona,note) VALUES(?,?,?,?,?,?)', (vid, evidence, 'https://example.org/fc', '2026-01-20', 'all', 'fixture'))
    c.commit()


def submit(c, rid, vid, coder, personas, version='1.1', eligibility='eligible'):
    a = {'eligibility': eligibility, 'origin_judgment': 'uncertain', 'video': {'format': 'street_interview'}, 'personas': personas}
    c.execute('INSERT INTO annotations(video_id,coder,version,payload,created,round_id) VALUES(?,?,?,?,?,?)', (vid, coder, version, C.dumps(C.validate_annotation(a)), C.now(), rid)); c.commit()


def persona(pid, gender='male', age='elderly', party='bnp'):
    return {'id': str(pid), 'codes': {'gender': gender, 'age': age, 'endorses_party': party}}


def add_coders(c, *names):
    for n in names: c.execute('INSERT INTO coders VALUES(?,?)', (n, 'hash-' + n))
    c.commit()


# --- 1. out-of-period uploads after metadata expiry ------------------------------------

def test_out_of_period_upload_stays_excluded_after_metadata_expiry(corpus):
    c, cfg, client, _ = corpus
    C.register(c, 'AAAAAAAAAA4', 'manual', ''); C.ingest(c, cfg, client, ['AAAAAAAAAA4'])
    adjudicate(c, cfg, 'AAAAAAAAAA4')
    assert R.report(c, cfg)['eligible_unique'] == 0
    c.execute("UPDATE videos SET fetched_at='2020-01-01T00:00:00+00:00'"); c.commit(); C.purge(c, cfg)
    r = R.report(c, cfg)
    assert r['eligible_unique'] == 0 and r['flow']['excluded_outside_period'] == 1


def test_upload_with_unknown_period_is_excluded_and_counted(corpus):
    c, cfg, _, _ = corpus
    C.register(c, 'ZZZZZZZZZZ1', 'fact_check', 'never retrieved')
    adjudicate(c, cfg, 'ZZZZZZZZZZ1')
    r = R.report(c, cfg)
    assert r['eligible_unique'] == 0 and r['flow']['excluded_period_unknown'] == 1


# --- 2. separate dated observations -----------------------------------------------------

def test_api_and_playback_are_separate_and_latest_date_wins(corpus):
    c, cfg, _, _ = corpus
    vid = 'AAAAAAAAAA1'
    c.execute("INSERT INTO playback_checks(video_id,observed_at,status,reason) VALUES(?,?,?,?)", (vid, '2026-01-05T00:00:00+00:00', 'unavailable', 'Video unavailable'))
    c.execute("INSERT INTO playback_checks(video_id,observed_at,status,reason) VALUES(?,?,?,?)", (vid, '2026-01-01T00:00:00+00:00', 'viewable', ''))  # older, inserted later
    c.commit()
    row = next(r for r in C.library(c, cfg) if r['video_id'] == vid)
    assert row['api_status'] == 'public' and row['playback_status'] == 'unavailable' and row['playback_reason'] == 'Video unavailable'
    assert not row['available_for_gate'] and not row['viewable_now']
    C.record_playback(c, vid, 'viewable'); c.commit()
    row = next(r for r in C.library(c, cfg) if r['video_id'] == vid)
    assert row['playback_status'] == 'viewable' and row['available_for_gate']


def test_api_check_does_not_overwrite_playback(corpus):
    c, cfg, client, _ = corpus
    vid = 'AAAAAAAAAA1'; C.record_playback(c, vid, 'viewable'); c.commit()
    backup = VIDEOS.pop(vid)
    try: C.ingest(c, cfg, client, [vid])
    finally: VIDEOS[vid] = backup
    row = next(r for r in C.library(c, cfg) if r['video_id'] == vid)
    assert row['api_status'] == 'not_returned' and row['playback_status'] == 'viewable'


def test_repeated_identical_playback_is_not_duplicated(corpus):
    c, cfg, _, _ = corpus
    assert C.record_playback(c, 'AAAAAAAAAA1', 'viewable') is True
    assert C.record_playback(c, 'AAAAAAAAAA1', 'viewable') is False
    assert C.record_playback(c, 'AAAAAAAAAA1', 'unavailable', 'Private video') is True


# --- 3. freshness window ---------------------------------------------------------------

def test_availability_requires_recent_api_check(corpus):
    c, cfg, _, _ = corpus
    adjudicate(c, cfg, 'AAAAAAAAAA1')
    assert R.report(c, cfg)['eligible_available'] == 1
    c.execute("UPDATE availability_checks SET checked_at='2020-01-01T00:00:00+00:00'"); c.commit()
    r = R.report(c, cfg)
    assert r['eligible_unique'] == 1 and r['eligible_available'] == 0 and r['stale_availability'] == 1
    item = next(i for i in r['checklist'] if i['id'] == 'eligible_available')
    assert item['status'] == 'not_met' and 'Refresh metadata' in item['action']
    cfg['thresholds']['availability_max_age_days'] = 365 * 20
    assert R.report(c, cfg)['eligible_available'] == 1


# --- 4 and 5. usable pairs, completeness, unmatched personas -----------------------------

def test_gate_needs_enough_usable_pairs_even_with_perfect_alpha():
    subs = {f'V{i:010d}': {'A': {'eligibility': 'eligible', 'personas': [persona(1, age=a)]}, 'B': {'eligibility': 'eligible', 'personas': [persona(1, age=a)]}}
            for i, a in enumerate(['elderly', 'child', 'young_adult'])}
    res = R.compute_reliability(subs, C.codebook_snapshot('1.1'), RULES)
    assert res['variables']['age']['alpha'] == 1 and res['critical']['age']['status'] == 'insufficient_pairs' and not res['gate_met']
    res = R.compute_reliability(subs, C.codebook_snapshot('1.1'), {**RULES, 'min_pairs': 3})
    assert res['critical']['age']['status'] == 'met'


def test_missing_codes_make_a_variable_incomplete():
    subs = {f'V{i:010d}': {'A': {'personas': [persona(1, age='elderly' if i % 2 else 'child')]}, 'B': {'personas': [{'id': '1', 'codes': {'gender': 'male', 'endorses_party': 'bnp', 'age': 'missing' if i < 3 else ('elderly' if i % 2 else 'child')}}]}}
            for i in range(10)}
    res = R.compute_reliability(subs, C.codebook_snapshot('1.1'), {**RULES, 'min_pairs': 5})
    assert res['variables']['age']['completeness'] == 0.7 and res['critical']['age']['status'] == 'incomplete'


def test_unmatched_personas_are_reported_and_reduce_completeness():
    subs = {'VVVVVVVVVV1': {'A': {'personas': [persona(1), persona(2, gender='female')]}, 'B': {'personas': [persona(1)]}}}
    res = R.compute_reliability(subs, C.codebook_snapshot('1.1'), {**RULES, 'min_pairs': 1})
    assert res['unmatched_personas'] == [{'video_id': 'VVVVVVVVVV1', 'persona_id': '2', 'coded_by': ['A'], 'missing_for': ['B']}]
    assert res['persona_slots'] == 2 and res['matched_personas'] == 1 and res['persona_count_agreement'] == 0
    assert res['variables']['gender']['completeness'] == 0.5 and res['critical']['gender']['status'] == 'incomplete'


# --- 6. rounds: frozen rules, closed rounds immutable, adjudication order ----------------

def test_round_freezes_rules_and_closed_result_does_not_change(corpus):
    c, cfg, _, _ = corpus
    add_coders(c, 'coderA', 'coderB')
    c.execute("UPDATE inventory SET screening='eligible' WHERE video_id='AAAAAAAAAA1'"); c.commit()
    rid = R.create_round(c, cfg, 'Round 1', ['coderA', 'coderB'], 5, 7)['round_id']
    cfg['thresholds']['min_pairs'] = 99      # changing settings later does not change the round's rules
    submit(c, rid, 'AAAAAAAAAA1', 'coderA', [persona(1)]); submit(c, rid, 'AAAAAAAAAA1', 'coderB', [persona(1)])
    closed = R.close_round(c, rid)
    assert closed['rules']['min_pairs'] == 1 and closed['double_coded'] == 1
    submit(c, rid, 'AAAAAAAAAA1', 'coderB', [persona(1, gender='female')])   # a late revision slipped into the table
    again = R.reliability(c, rid)
    assert again == json.loads(json.dumps(closed)) and again['variables']['gender'] == closed['variables']['gender']
    with pytest.raises(ValueError): R.close_round(c, rid)


def test_two_rounds_keep_their_own_codebook_versions(corpus):
    c, cfg, _, _ = corpus
    add_coders(c, 'coderA', 'coderB')
    c.execute("UPDATE inventory SET screening='eligible' WHERE video_id IN ('AAAAAAAAAA1','AAAAAAAAAA5')"); c.commit()
    r1 = R.create_round(c, cfg, 'Round 1', ['coderA', 'coderB'], 1, 1)['round_id']
    with pytest.raises(ValueError): R.create_round(c, cfg, 'Too early', ['coderA', 'coderB'], 1, 1)
    R.close_round(c, r1)
    cfg['version'] = '1.2'
    r2 = R.create_round(c, cfg, 'Round 2', ['coderA', 'coderB'], 1, 2)['round_id']
    summ = {s['id']: s for s in R.rounds_summary(c)}
    assert summ[r1]['codebook_version'] == '1.1' and summ[r2]['codebook_version'] == '1.2'
    assert R.reliability(c, r1)['codebook_version'] == '1.1' and R.reliability(c, r2)['provisional'] is True


# --- 7 and 8. RQ3 cues, upload versus content level, exclusion reasons -------------------

def test_report_rq3_upload_content_and_exclusion_reasons(corpus):
    c, cfg, _, _ = corpus
    adjudicate(c, cfg, 'AAAAAAAAAA1')
    c.execute("UPDATE inventory SET group_id='AAAAAAAAAA1', creator_label='yes' WHERE video_id='AAAAAAAAAA5'")
    c.execute("UPDATE inventory SET screening='excluded', screening_reason='not_election_related' WHERE video_id='AAAAAAAAAA2'"); c.commit()
    adjudicate(c, cfg, 'AAAAAAAAAA3', eligibility='excluded', evidence=None, reason='genuine_footage')
    r = R.report(c, cfg)
    assert r['rq3']['cues']['news_brand'] == {'yes': 1} and r['rq3']['by_party']['format'] == {'bnp': {'street_interview': 1}}
    assert r['content_level']['groups'] == 1 and r['upload_level']['uploads'] == 2
    assert r['upload_level']['creator_label'] == {'unknown': 1, 'yes': 1}
    assert r['content_level']['labels_level_1_3'] == {'creator:yes': 1, 'platform:no_or_unknown': 1}
    assert r['flow']['screening_excluded_by_reason'] == {'not_election_related': 1}
    assert r['flow']['adjudication_excluded_by_reason'] == {'genuine_footage': 1}
    assert r['flow']['grouped_as_reposts'] == 1


def test_exclusion_requires_a_listed_reason():
    with pytest.raises(ValueError): C.validate_annotation({'eligibility': 'excluded', 'personas': []})
    C.validate_annotation({'eligibility': 'excluded', 'exclusion_reason': 'cartoon_or_animation', 'personas': []})


# --- exports --------------------------------------------------------------------------

def build_study(c, cfg):
    add_coders(c, 'coderA', 'coderB')
    for vid in ('AAAAAAAAAA1', 'AAAAAAAAAA5'):
        c.execute("UPDATE inventory SET screening='eligible' WHERE video_id=?", (vid,))
    c.commit()
    rid = R.create_round(c, cfg, 'Round 1', ['coderA', 'coderB'], 2, 3)['round_id']
    submit(c, rid, 'AAAAAAAAAA1', 'coderA', [persona(1), persona(2, gender='female', age='young_adult', party='jamaat')])
    submit(c, rid, 'AAAAAAAAAA1', 'coderB', [persona(1), persona(2, gender='female', age='middle_aged', party='jamaat')])
    submit(c, rid, 'AAAAAAAAAA5', 'coderA', [persona(1, age='child')])
    submit(c, rid, 'AAAAAAAAAA5', 'coderB', [persona(1, age='child'), persona(2)])
    R.close_round(c, rid)
    adjudicate(c, cfg, 'AAAAAAAAAA1'); adjudicate(c, cfg, 'AAAAAAAAAA5', evidence='platform_label', codes={'gender': 'female', 'age': 'child', 'endorses_party': 'none', 'factual_claim': 'yes'})
    adjudicate(c, cfg, 'AAAAAAAAAA3', eligibility='excluded', evidence=None, reason='genuine_footage')
    C.db.add_discovery(c, 'AAAAAAAAAA1', 'search', 'q'); c.execute("INSERT INTO search_log(query,order_by,published_after,published_before,page,result_count,total_results,run_at) VALUES('জনমত','date','a','b',1,3,3,'2026-11-25')"); c.commit()


def test_dataset_export_pseudonymises_ids_without_permission(corpus):
    c, cfg, _, tmp = corpus
    build_study(c, cfg)
    z = zipfile.ZipFile(io.BytesIO(X.dataset_zip(c, cfg, tmp)))
    body = ''.join(z.read(n).decode('utf-8') for n in z.namelist())
    assert {'coded_videos.csv', 'coded_personas.csv', 'uploads.csv', 'independent_annotations.csv', 'README.txt'} <= set(z.namelist())
    assert 'AAAAAAAAAA1' not in body and 'UC_one' not in body and 'নির্বাচন' not in body   # no IDs, no API titles
    cfg['permissions']['id_export'] = True
    z = zipfile.ZipFile(io.BytesIO(X.dataset_zip(c, cfg, tmp)))
    assert 'AAAAAAAAAA1' in z.read('coded_videos.csv').decode('utf-8')


def test_search_log_export(corpus):
    c, cfg, _, _ = corpus
    build_study(c, cfg)
    rows = list(csv.DictReader(io.StringIO(X.search_log_csv(c))))
    assert rows == [{'query': 'জনমত', 'order_by': 'date', 'published_after': 'a', 'published_before': 'b', 'page': '1', 'result_count': '3', 'total_results': '3', 'run_at': '2026-11-25'}]


def test_reproducibility_package_runs_and_matches_stored_results(corpus):
    c, cfg, _, tmp = corpus
    build_study(c, cfg)
    pkg = tmp / 'pkg'; zipfile.ZipFile(io.BytesIO(X.package_zip(c, cfg, tmp))).extractall(pkg)
    root = pkg / 'reproducibility_package'
    for name in ('data/coded_videos.csv', 'data/independent_annotations.csv', 'data/search_log.csv', 'data/flow.json', 'reliability/rounds.json',
                 'results/feasibility_report.json', 'codebook/codebook.json', 'config/study_config.json', 'analysis/analysis.py', 'README.md', 'MANIFEST.json'):
        assert (root / name).exists(), name
    everything = ''.join(p.read_text(encoding='utf-8') for p in root.rglob('*') if p.is_file())
    assert 'AAAAAAAAAA1' not in everything and 'UC_one' not in everything and 'test-key' not in everything
    run = subprocess.run([sys.executable, 'analysis/analysis.py'], cwd=root, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert 'all recomputed values match' in run.stdout
    results = json.loads((root / 'results/analysis_results.json').read_text(encoding='utf-8'))
    rounds = json.loads((root / 'reliability/rounds.json').read_text(encoding='utf-8'))
    assert results['included'] == 2 and len(rounds[0]['result']['unmatched_personas']) == 1


def test_analysis_script_detects_tampering(corpus):
    c, cfg, _, tmp = corpus
    build_study(c, cfg)
    pkg = tmp / 'pkg2'; zipfile.ZipFile(io.BytesIO(X.package_zip(c, cfg, tmp))).extractall(pkg)
    root = pkg / 'reproducibility_package'; f = root / 'data/independent_annotations.csv'
    f.write_text(f.read_text(encoding='utf-8').replace(',young_adult,', ',middle_aged,'), encoding='utf-8')
    run = subprocess.run([sys.executable, 'analysis/analysis.py'], cwd=root, capture_output=True, text=True)
    assert run.returncode == 1 and 'DIFFERENCES FOUND' in run.stdout


# --- technical -------------------------------------------------------------------------

def test_quota_day_works_without_a_timezone_database(monkeypatch):
    def broken(name): raise zoneinfo.ZoneInfoNotFoundError(name)
    monkeypatch.setattr(zoneinfo, 'ZoneInfo', broken)
    start = C.pacific_day_start()
    assert start.endswith('+00:00') and ('T08:00:00' in start or 'T07:00:00' in start)


def test_tzdata_is_a_declared_requirement():
    assert 'tzdata' in (C.ROOT / 'requirements.txt').read_text()


def test_old_saved_config_gains_new_settings(corpus):
    c, cfg, _, _ = corpus
    old = json.loads(C.dumps(cfg)); del old['thresholds']['min_pairs']; del old['permissions']['id_export']
    C.put(c, 'config', old)
    new = C.config(c)
    assert new['thresholds']['min_pairs'] == 40 and new['permissions']['id_export'] is False


def test_legacy_assignments_become_a_round(tmp_path):
    import sqlite3
    path = tmp_path / 'legacy.db'; c = C.connect(path)
    c.execute("INSERT INTO assignments VALUES('AAAAAAAAAA1','coderA','1.1')"); c.execute("DELETE FROM rounds"); c.commit(); c.close()
    c = C.connect(path)
    assert c.execute('SELECT COUNT(*) FROM round_assignments').fetchone()[0] == 1
    assert c.execute('SELECT name FROM rounds').fetchone()[0].startswith('Legacy round')


# --- HTTP ------------------------------------------------------------------------------

@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv('RESEARCH_DATA', str(tmp_path / 'appdata'))
    from webapp import server
    monkeypatch.setattr(server, 'DB', tmp_path / 'http.db'); monkeypatch.setattr(server, 'DATA', tmp_path)
    with TestClient(server.app) as cl:
        with server.cx() as c:
            cfg = C.config(c); cfg['seeds'] = {'videos': [], 'handles': [], 'channel_ids': ['UC_one']}
            client = fake_client(); C.expand(c, cfg, client, lambda: None, lambda _: None)
            C.register(c, 'AAAAAAAAAA4', 'manual', ''); C.ingest(c, cfg, client, ['AAAAAAAAAA4']); client.close()
            C.register(c, 'ZZZZZZZZZZ1', 'fact_check', '')
        yield cl, server, {'Authorization': 'Bearer ' + server.TOKEN}


OBS = {'playback': 'viewable', 'creator_label': 'unknown', 'platform_label': 'unknown'}


def test_http_screening_rules(api):
    cl, s, h = api
    r = cl.post('/api/video/ZZZZZZZZZZ1/observe', headers=h, json={**OBS, 'group_id': 'ZZZZZZZZZZ1', 'screening': 'eligible'})
    assert r.status_code == 400 and 'not known' in r.json()['detail']
    r = cl.post('/api/video/AAAAAAAAAA4/observe', headers=h, json={**OBS, 'group_id': 'AAAAAAAAAA4', 'screening': 'eligible'})
    assert r.status_code == 400 and 'outside the study period' in r.json()['detail']
    r = cl.post('/api/video/AAAAAAAAAA2/observe', headers=h, json={**OBS, 'group_id': 'AAAAAAAAAA2', 'screening': 'excluded'})
    assert r.status_code == 400
    assert cl.post('/api/video/AAAAAAAAAA2/observe', headers=h, json={**OBS, 'group_id': 'AAAAAAAAAA2', 'screening': 'excluded', 'screening_reason': 'not_election_related'}).status_code == 200
    r = cl.post('/api/video/AAAAAAAAAA1/observe', headers=h, json={**OBS, 'playback': 'unavailable', 'group_id': 'AAAAAAAAAA1'})
    assert r.status_code == 400 and 'message YouTube shows' in r.json()['detail']


def test_http_round_lifecycle_and_adjudication_order(api):
    cl, s, h = api
    tokens = {n: cl.post('/api/coders', headers=h, json={'name': n}).json()['token'] for n in ('coderA', 'coderB')}
    assert cl.post('/api/video/AAAAAAAAAA1/observe', headers=h, json={**OBS, 'group_id': 'AAAAAAAAAA1', 'screening': 'eligible'}).status_code == 200
    rnd = cl.post('/api/rounds', headers=h, json={'name': 'Round 1', 'coders': ['coderA', 'coderB'], 'n': 5, 'seed': 1}).json()
    payload = {'eligibility': 'eligible', 'origin_judgment': 'uncertain', 'video': {}, 'personas': [persona(1)]}
    for n, t in tokens.items():
        assert cl.post('/api/video/AAAAAAAAAA1/annotation', headers={'Authorization': 'Bearer ' + t}, json={'version': '1.1', 'payload': payload}).status_code == 200
    r = cl.post('/api/video/AAAAAAAAAA1/annotation', headers=h, json={'version': '1.1', 'final': True, 'payload': payload})
    assert r.status_code == 400 and 'open coding round' in r.json()['detail']
    closed = cl.post(f"/api/rounds/{rnd['round_id']}/close", headers=h).json()
    assert closed['double_coded'] == 1 and closed['provisional'] is False
    r = cl.post('/api/video/AAAAAAAAAA1/annotation', headers={'Authorization': 'Bearer ' + tokens['coderA']}, json={'version': '1.1', 'payload': payload})
    assert r.status_code == 403
    assert cl.post('/api/video/AAAAAAAAAA1/annotation', headers=h, json={'version': '1.1', 'final': True, 'payload': payload}).status_code == 200
    assert cl.get(f"/api/rounds/{rnd['round_id']}/reliability", headers=h).json() == closed
    a = cl.get('/api/assignments', headers={'Authorization': 'Bearer ' + tokens['coderB']}).json()
    assert len(a) == 1 and a[0]['done'] == 1 and a[0]['closed']


def test_http_exports_require_permissions(api):
    cl, s, h = api
    assert cl.get('/api/export/searchlog', headers=h).status_code == 403
    assert cl.get('/api/export/package', headers=h).status_code == 403
    cfg = cl.get('/api/config', headers=h).json(); cfg['permissions'].update(export=True, analysis=True)
    assert cl.post('/api/config', headers=h, json=cfg).status_code == 200
    assert cl.get('/api/export/searchlog', headers=h).status_code == 200
    r = cl.get('/api/export/package', headers=h)
    assert r.status_code == 200 and r.headers['content-type'] == 'application/zip'
    assert 'reproducibility_package/analysis/analysis.py' in zipfile.ZipFile(io.BytesIO(r.content)).namelist()
