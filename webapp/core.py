"""Local research data, collection jobs and inventory. No network calls on import.

Research analytics (coding rounds, reliability, reports) live in research.py and
exports live in exports.py.
"""
import hashlib, json, random, sqlite3, re, os, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import Counter, defaultdict
from pilot import db, collect, gemini_screen
from pilot.prescreen import prescreen_video, parse_iso_duration, in_period
from pilot.youtube import YouTubeClient, chunks, extract_video_id
from pilot.config import load_config

ROOT = Path(__file__).resolve().parents[1]
APP_VERSION = '0.3.1'

SCHEMA = '''
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
CREATE TABLE IF NOT EXISTS playback_checks(id INTEGER PRIMARY KEY,video_id TEXT NOT NULL,observed_at TEXT NOT NULL,status TEXT NOT NULL,reason TEXT DEFAULT '',observer TEXT DEFAULT 'admin');
CREATE TABLE IF NOT EXISTS rounds(id INTEGER PRIMARY KEY,name TEXT NOT NULL,codebook_version TEXT NOT NULL,codebook TEXT NOT NULL,rules TEXT NOT NULL,seed INTEGER,pool_size INTEGER,created TEXT,closed TEXT,result TEXT);
CREATE TABLE IF NOT EXISTS round_assignments(round_id INTEGER NOT NULL,video_id TEXT NOT NULL,coder TEXT NOT NULL,PRIMARY KEY(round_id,video_id,coder));
'''

DEFAULT_EXTRA = {
    'title': 'Who Gets Synthesised?', 'version': '1.1',
    'thresholds': {'videos': 100, 'channels': 5, 'verified': 50, 'alpha': 0.67, 'reliability_n': 50,
                   'min_pairs': 40, 'min_completeness': 0.8, 'availability_max_age_days': 30},
    'permissions': {'ethics': False, 'collection': False, 'analysis': False, 'gemini': False, 'export': False, 'id_export': False},
    'literature': 'pending', 'literature_note': '', 'search_limit': 100, 'general_limit': 10000,
    'study_notes': 'Ordinary speaking synthetic personas; exclude identifiable real-person deepfakes, cartoons and genuine footage. Reposts grouped.'}

# --- Codebook 1.1 ---------------------------------------------------------------
# Variables that are counted or tested for reliability are categorical, so "BNP", "bnp"
# and a Bangla spelling cannot register as disagreement. Free text is kept for notes.
YNU = ['yes', 'no', 'unknown']
PARTIES = ['bnp', 'jamaat', 'ncp', 'awami_league', 'jatiya_party', 'other_party', 'multiple', 'none']
OCCUPATIONS = ['farmer', 'rickshaw_or_transport', 'shopkeeper_or_vendor', 'labourer', 'student', 'teacher', 'professional', 'police_or_security', 'religious_cleric', 'homemaker', 'journalist', 'other']
RELIGIONS = ['muslim', 'hindu', 'christian', 'buddhist', 'other']
VIDEO_FIELDS = {'format': ['street_interview', 'single_testimonial', 'montage', 'skit', 'news_style', 'other', 'unknown'], 'genre': ['persuasive', 'satirical', 'other', 'unknown'], 'party_favoured': PARTIES + ['unknown'], 'interviewer': YNU, 'news_brand': YNU, 'captions': YNU, 'uniforms': YNU, 'regional_dialect': YNU, 'production_artifacts': YNU, 'authenticity': 'text', 'frame': 'text', 'notes': 'text'}
PERSONA_FIELDS = {'gender': ['male', 'female', 'other', 'unknown'], 'age': ['child', 'young_adult', 'middle_aged', 'elderly', 'unknown'], 'setting': ['rural', 'urban', 'unknown'], 'disability_marker': YNU, 'visible_religion': RELIGIONS + ['no_visible_marker', 'unknown'], 'stated_religion': RELIGIONS + ['not_stated'], 'visible_occupation': OCCUPATIONS + ['no_visible_marker', 'unknown'], 'stated_occupation': OCCUPATIONS + ['not_stated'], 'visible_markers': 'text', 'stated_identity': 'text', 'transcript_bn': 'text', 'endorses_party': PARTIES + ['unknown'], 'attacks_party': PARTIES + ['unknown'], 'issues': 'text', 'factual_claim': YNU, 'factual_claim_text': 'text', 'emotion': ['none', 'fear', 'anger', 'hope', 'pride', 'humour', 'grievance', 'other', 'unknown'], 'voice': ['personal', 'collective', 'none', 'unknown'], 'dialect': 'text', 'notes': 'text'}
CRITICAL_PERSONA = ['gender', 'age', 'endorses_party']
RQ3_CUES = ['format', 'interviewer', 'news_brand', 'captions', 'uniforms', 'regional_dialect', 'production_artifacts']
# Proposal section 7.2 exclusion criteria, used at screening and adjudication so the
# flow diagram can report exclusions with reasons.
EXCLUSION_REASONS = ['outside_study_period', 'not_election_related', 'no_speaking_persona', 'real_person_deepfake', 'cartoon_or_animation', 'genuine_footage', 'repost_of_included_video', 'not_bangladesh_context', 'cannot_be_viewed', 'other']
MISSING_VALUES = {
    'missing': 'Not coded yet. Counts as incomplete. Replace it before submitting.',
    'unknown': 'You checked, and the video does not show or say this. This is a real answer.',
    'uncertain': 'You can see something, but you cannot choose between the categories.',
    'not_applicable': 'The question does not apply to this video or person.'}
FIELD_HELP = {
    'format': 'How the video is built. A street interview has an interviewer and passers-by; a montage joins several short clips.',
    'genre': 'Persuasive means it asks viewers to support or reject a party. Satirical means it is played for laughs.',
    'party_favoured': 'The party the video as a whole supports. Use none if no party is supported; multiple if more than one.',
    'interviewer': 'Is an interviewer or reporter visible or heard?',
    'news_brand': 'Is there a microphone, logo or banner styled like a news channel?',
    'captions': 'Are there on-screen captions or subtitles?',
    'uniforms': 'Does any person wear a uniform (police, army, school, professional)?',
    'regional_dialect': 'Does any speaker use a clearly regional Bangla dialect rather than standard Bangla?',
    'production_artifacts': 'Visible or audible generation artifacts: merged fingers, warped text, lip-sync drift, flicker.',
    'authenticity': 'Free text. Other cues that make the people look real or authoritative.',
    'frame': 'Free text. The problem defined, who is blamed, and the remedy proposed.',
    'notes': 'Free text. Anything else the adjudicator should know.',
    'gender': 'Apparent gender as presented. Code what a viewer would perceive.',
    'age': 'Apparent age group as presented.',
    'setting': 'Where the person is shown: village or field (rural) versus city street, shop or office (urban).',
    'disability_marker': 'A visible disability marker such as a wheelchair, crutch or white cane.',
    'visible_religion': 'Religion suggested by visible markers only: cap, beard, hijab, sindoor, tilak, cross. Never infer from a name.',
    'stated_religion': 'Religion the person says in speech. Use not_stated if they do not say it.',
    'visible_occupation': 'Occupation suggested by clothing, tools or setting, such as a rickshaw, plough or police uniform.',
    'stated_occupation': 'Occupation the person says in speech. Use not_stated if they do not say it.',
    'visible_markers': 'Free text. List the visible markers you relied on.',
    'stated_identity': 'Free text. Identity the person states: occupation, region, community.',
    'transcript_bn': 'Free text. What the person says, in Bangla script, as spoken.',
    'endorses_party': 'Party this person explicitly supports. A name or symbol shown without support is none.',
    'attacks_party': 'Party this person explicitly criticises. Use none if no party is criticised.',
    'issues': 'Free text. Policy issues raised, separated by semicolons.',
    'factual_claim': 'Does the person make a checkable factual claim (a number, event or record)?',
    'factual_claim_text': 'Free text. The claim, in their words.',
    'emotion': 'The main emotional appeal in what the person says.',
    'voice': 'Personal: "I will vote". Collective: "people like us support". None: no endorsement.',
    'dialect': 'Free text. Name the dialect if one is clear.'}

KINDS = ['fact_check', 'creator_disclosure', 'platform_label', 'visual_judgment', 'provenance', 'watermark', 'other']
SCREENING = ['unscreened', 'eligible', 'excluded', 'uncertain']
EVIDENCE_SCOPES = ['unclear', 'all', 'some_personas']
PLAYBACK = ['unknown', 'viewable', 'unavailable']

# Research columns. channel_id is a locator (like video_id) so channel counts survive the
# 30-day metadata purge. in_period is the study-period classification made when metadata was
# retrieved; it is a research record, kept after the raw publication date is purged.
INVENTORY_COLUMNS = {'channel_id': 'TEXT', 'screening': "TEXT DEFAULT 'unscreened'", 'screening_note': "TEXT DEFAULT ''", 'screening_at': 'TEXT', 'in_period': 'INTEGER', 'screening_reason': "TEXT DEFAULT ''"}


def now(): return db.utcnow()
def dumps(x): return json.dumps(x, ensure_ascii=False, sort_keys=True)
def hashval(x): return hashlib.sha256(dumps(x).encode()).hexdigest()
def codebook_snapshot(version):
    return {'version': version, 'video': VIDEO_FIELDS, 'persona': PERSONA_FIELDS, 'critical': CRITICAL_PERSONA,
            'exclusion_reasons': EXCLUSION_REASONS, 'missing_values': MISSING_VALUES, 'help': FIELD_HELP}


def connect(path):
    c = db.connect(path); c.execute('PRAGMA busy_timeout=10000'); c.execute('PRAGMA journal_mode=WAL'); c.executescript(SCHEMA)
    have = {r[1] for r in c.execute('PRAGMA table_info(inventory)')}
    for col, decl in INVENTORY_COLUMNS.items():
        if col not in have: c.execute(f'ALTER TABLE inventory ADD COLUMN {col} {decl}')
    if 'round_id' not in {r[1] for r in c.execute('PRAGMA table_info(annotations)')}:
        c.execute('ALTER TABLE annotations ADD COLUMN round_id INTEGER')
    _migrate_legacy(c)
    c.commit(); return c


def _migrate_legacy(c):
    """Move 0.2/0.3.0 data into the 0.3.1 structures (no-op on fresh databases)."""
    # Playback stored only as the latest inventory value becomes a dated observation.
    c.execute("""INSERT INTO playback_checks(video_id,observed_at,status,reason,observer)
                 SELECT video_id,COALESCE(playback_at,checked,'1970-01-01T00:00:00+00:00'),playback,'migrated from 0.3.0','admin' FROM inventory
                 WHERE playback IN ('viewable','unavailable') AND video_id NOT IN (SELECT video_id FROM playback_checks)""")
    # Old version-keyed assignments become one legacy round per codebook version.
    if c.execute('SELECT COUNT(*) FROM round_assignments').fetchone()[0] == 0:
        for (version,) in c.execute('SELECT DISTINCT version FROM assignments').fetchall():
            rules = {'alpha': 0.67, 'min_pairs': 40, 'min_completeness': 0.8, 'reliability_n': 50, 'critical': CRITICAL_PERSONA, 'missing_rule': 'strict'}
            cur = c.execute('INSERT INTO rounds(name,codebook_version,codebook,rules,seed,pool_size,created) VALUES(?,?,?,?,?,?,?)',
                            (f'Legacy round (codebook {version})', version, dumps(codebook_snapshot(version)), dumps(rules), None, None, now()))
            rid = cur.lastrowid
            c.execute('INSERT INTO round_assignments SELECT ?,video_id,coder FROM assignments WHERE version=?', (rid, version))
            c.execute("UPDATE annotations SET round_id=? WHERE version=? AND round_id IS NULL AND coder<>'admin'", (rid, version))


def get(c, k, default=None):
    r = c.execute('SELECT v FROM settings WHERE k=?', (k,)).fetchone(); return json.loads(r[0]) if r else default
def put(c, k, v): c.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v', (k, dumps(v))); c.commit()


def _fill(target, defaults):
    for k, v in defaults.items():
        if k not in target: target[k] = json.loads(dumps(v))
        elif isinstance(v, dict) and isinstance(target[k], dict): _fill(target[k], v)
    return target


def default_config():
    cfg = load_config(ROOT / 'config.yaml'); cfg['search']['video_duration'] = 'any'; cfg['gemini']['model'] = ''
    cfg.update(json.loads(dumps(DEFAULT_EXTRA))); return cfg


def config(c):
    """Saved configuration, with any setting added in a later release filled from the defaults."""
    base = default_config(); saved = get(c, 'config')
    return _fill(saved, base) if saved else base


def audit(c, a, d): c.execute('INSERT INTO audit(action,detail,created) VALUES(?,?,?)', (a, dumps(d), now())); c.commit()
def asrows(c, q, p=()): return [dict(r) for r in c.execute(q, p)]


def register(c, vid, source, detail, channel_id=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', vid): raise ValueError('Invalid video ID')
    c.execute('INSERT OR IGNORE INTO inventory(video_id,group_id) VALUES(?,?)', (vid, vid)); db.add_discovery(c, vid, source, detail)
    if channel_id: c.execute('UPDATE inventory SET channel_id=COALESCE(channel_id,?) WHERE video_id=?', (channel_id, vid))
    c.commit()


def cutoff(cfg): return (datetime.now(timezone.utc) - timedelta(days=min(30, int(cfg['storage']['api_data_max_age_days'])))).isoformat()
def days_ago(days): return (datetime.now(timezone.utc) - timedelta(days=float(days))).isoformat()


def purge(c, cfg, vid=None):
    # API metadata only. Locator IDs, the in-period classification and all research
    # observations stay in the inventory and observation tables.
    q = 'video_id=?' if vid else '(fetched_at IS NULL OR fetched_at<?)'; p = (vid or cutoff(cfg),)
    ids = [r[0] for r in c.execute('SELECT video_id FROM videos WHERE ' + q, p)]
    for v in ids:
        c.execute('DELETE FROM videos WHERE video_id=?', (v,)); c.execute('DELETE FROM prescreen WHERE video_id=?', (v,))
        c.execute("UPDATE inventory SET retrieval=CASE WHEN retrieval='unavailable' THEN retrieval ELSE 'stale' END WHERE video_id=?", (v,))
    c.execute('DELETE FROM channels WHERE fetched_at<?', (cutoff(cfg),)); c.commit(); return len(ids)


def ingest(c, cfg, client, ids):
    for batch in chunks(list(dict.fromkeys(ids)), 50):
        items = {i['id']: i for i in client.videos(batch)}
        for vid in batch:
            item = items.get(vid)
            if not item:
                purge(c, cfg, vid); c.execute("UPDATE inventory SET retrieval='unavailable',checked=? WHERE video_id=?", (now(), vid)); db.record_availability(c, vid, 'not_returned'); continue
            db.upsert_video(c, item, parse_iso_duration(item.get('contentDetails', {}).get('duration')))
            if item.get('snippet', {}).get('channelId'): c.execute('UPDATE inventory SET channel_id=? WHERE video_id=?', (item['snippet']['channelId'], vid))
            v = dict(c.execute('SELECT * FROM videos WHERE video_id=?', (vid,)).fetchone()); pre = prescreen_video(v, cfg); db.save_prescreen(c, vid, pre)
            c.execute('UPDATE inventory SET retrieval=?,checked=?,in_period=? WHERE video_id=?', (v['privacy_status'] or 'unknown', now(), int(pre['in_period']), vid))
            db.record_availability(c, vid, v['privacy_status'] or 'unknown')
        c.commit()


def pacific_day_start():
    """Start of the current YouTube quota day (midnight US Pacific) in UTC.

    Windows has no system timezone database; requirements.txt installs tzdata for it.
    If the zone still cannot be loaded, fall back to UTC-8, which starts the local
    budget day at most one hour early during daylight saving time."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo('America/Los_Angeles')
    except Exception:
        tz = timezone(timedelta(hours=-8))
    return datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()


def client_for(c, cfg, key, check):
    client = YouTubeClient(key)
    def request(endpoint):
        check(); start = pacific_day_start()
        search = endpoint == 'search'; n = c.execute('SELECT COUNT(*) FROM request_log WHERE at>=? AND ' + ("endpoint='search'" if search else "endpoint<>'search'"), (start,)).fetchone()[0]
        if n >= cfg['search_limit' if search else 'general_limit']: raise ValueError('Local daily request budget reached. Resume after quota reset.')
        c.execute('INSERT INTO request_log(endpoint,at) VALUES(?,?)', (endpoint, now())); c.commit()
    client.on_request = request; return client


def search(c, cfg, client, max_calls, check, progress):
    s = cfg['search']; p = cfg['study_period']; calls = 0
    for query in s['queries']:
        for order in s['orders']:
            for after, before in collect.month_windows(p['start'], p['end'], p['timezone_offset_hours']):
                spec = [query, order, after, before, s['region_code'], s['relevance_language'], s['video_duration'], s['max_pages_per_query']]; key = 'search:' + hashval(spec)
                cp = c.execute('SELECT * FROM checkpoints WHERE job_key=?', (key,)).fetchone(); token = cp['token'] if cp else None; pages = cp['pages'] if cp else 0
                if cp and cp['done']: continue
                while calls < max_calls and pages < int(s['max_pages_per_query']):
                    check(); data = client.search(query, after, before, order, s['region_code'], s['relevance_language'], s['video_duration'], token); calls += 1; pages += 1
                    items = data.get('items', []); ids = []
                    for item in items:
                        vid = item.get('id', {}).get('videoId')
                        if vid: register(c, vid, 'search', dumps({'query': query, 'order': order, 'after': after, 'before': before, 'page': pages, 'key': key})); ids.append(vid)
                    token = data.get('nextPageToken'); done = not token or pages >= int(s['max_pages_per_query'])
                    c.execute('INSERT OR REPLACE INTO checkpoints VALUES(?,?,?,?,?)', (key, token, pages, int(done), now()))
                    c.execute('INSERT INTO search_log(query,order_by,published_after,published_before,page,result_count,total_results,run_at) VALUES(?,?,?,?,?,?,?,?)', (query, order, after, before, pages, len(items), data.get('pageInfo', {}).get('totalResults'), now())); c.commit()
                    progress(f'{calls} search pages; {query}; {after[:10]}; ' + ('page cap reached' if token and done else ''))
                    if ids: ingest(c, cfg, client, ids)
                    if done: break
                if calls >= max_calls: return
    progress('All configured search windows processed (subject to page caps and API coverage).')


def expand(c, cfg, client, check, progress):
    ids = list(cfg['seeds']['channel_ids']); vids = []
    for value in cfg['seeds']['videos']:
        vid = extract_video_id(value)
        if vid: register(c, vid, 'seed', 'configured video'); vids.append(vid)
    if vids:
        ingest(c, cfg, client, vids); ids += [r[0] for r in c.execute('SELECT channel_id FROM videos WHERE video_id IN (' + ','.join('?' * len(vids)) + ')', vids) if r[0]]
    for handle in cfg['seeds']['handles']:
        item = client.channel_by_handle(handle)
        if item: ids.append(item['id'])
        else: progress('Handle not returned: ' + handle)
    for ch in client.channels_by_id(list(dict.fromkeys(ids))):
        db.upsert_channel(c, ch, True); c.commit(); playlist = ch.get('contentDetails', {}).get('relatedPlaylists', {}).get('uploads')
        if not playlist: continue
        key = 'playlist:' + hashval([playlist, cfg['study_period']]); cp = c.execute('SELECT * FROM checkpoints WHERE job_key=?', (key,)).fetchone(); token = cp['token'] if cp else None; pages = cp['pages'] if cp else 0
        if cp and cp['done']: continue
        while True:
            check(); data = client.get('playlistItems', part='contentDetails', playlistId=playlist, maxResults=50, pageToken=token); pages += 1; vids = []
            for item in data.get('items', []):
                d = item.get('contentDetails', {}); vid = d.get('videoId'); published = d.get('videoPublishedAt')
                if vid and (not published or in_period(published, cfg['study_period'])): register(c, vid, 'channel_expansion', ch['id'], channel_id=ch['id']); vids.append(vid)
            next_token = data.get('nextPageToken'); c.execute('INSERT OR REPLACE INTO checkpoints VALUES(?,?,?,?,?)', (key, next_token, pages, int(not next_token), now())); c.commit(); progress(f'{ch["id"]}: {pages} playlist pages')
            if vids: ingest(c, cfg, client, vids)
            if not next_token: break
            if next_token == token: raise ValueError('Repeated playlist token; coverage incomplete')
            token = next_token


# --- Observations ------------------------------------------------------------------
# Two separate dated categories. API retrieval status comes from availability_checks;
# playback availability comes from playback_checks recorded by a person. Within each
# category the latest observation wins; neither overwrites the other.

def record_playback(c, vid, status, reason='', observer='admin', min_hours=24):
    """Store a dated playback observation unless it repeats the latest one within min_hours."""
    if status not in ('viewable', 'unavailable'): return False
    last = c.execute('SELECT status,reason,observed_at FROM playback_checks WHERE video_id=? ORDER BY observed_at DESC,id DESC LIMIT 1', (vid,)).fetchone()
    if last and last['status'] == status and (last['reason'] or '') == (reason or '') and last['observed_at'] >= days_ago(min_hours / 24): return False
    c.execute('INSERT INTO playback_checks(video_id,observed_at,status,reason,observer) VALUES(?,?,?,?,?)', (vid, now(), status, reason or '', observer))
    c.execute('UPDATE inventory SET playback=?,playback_at=? WHERE video_id=?', (status, now(), vid)); return True


def is_available_for_gate(r, cfg):
    """Feasibility availability: latest API status public or unlisted, checked within the
    configured window, and the latest playback observation (if any) is viewable."""
    max_age = int(cfg['thresholds'].get('availability_max_age_days', 30))
    if r.get('api_status') not in ('public', 'unlisted'): return False
    if not r.get('api_checked') or r['api_checked'] < days_ago(max_age): return False
    return r.get('playback_status') in (None, 'viewable')


def library(c, cfg):
    q = '''SELECT i.video_id,i.retrieval,i.checked,i.group_id,i.group_note,i.manual_channel,
    i.creator_label,i.platform_label,i.label_at,i.screening,i.screening_note,i.screening_reason,i.screening_at,i.in_period AS period_flag,
    COALESCE(v.channel_id,i.channel_id) channel_id,v.title,v.channel_title,v.published_at,v.duration_seconds,v.fetched_at,
    v.synthetic_field_present,v.contains_synthetic_media,p.in_period,p.election_hits,p.ai_hits,p.is_short,
    (SELECT COUNT(*) FROM evidence e WHERE e.video_id=i.video_id) evidence_count,
    (SELECT a.status FROM availability_checks a WHERE a.video_id=i.video_id ORDER BY a.checked_at DESC,a.id DESC LIMIT 1) api_status,
    (SELECT a.checked_at FROM availability_checks a WHERE a.video_id=i.video_id ORDER BY a.checked_at DESC,a.id DESC LIMIT 1) api_checked,
    (SELECT b.status FROM playback_checks b WHERE b.video_id=i.video_id ORDER BY b.observed_at DESC,b.id DESC LIMIT 1) playback_status,
    (SELECT b.observed_at FROM playback_checks b WHERE b.video_id=i.video_id ORDER BY b.observed_at DESC,b.id DESC LIMIT 1) playback_checked,
    (SELECT b.reason FROM playback_checks b WHERE b.video_id=i.video_id ORDER BY b.observed_at DESC,b.id DESC LIMIT 1) playback_reason
    FROM inventory i LEFT JOIN videos v USING(video_id) LEFT JOIN prescreen p USING(video_id)
    ORDER BY CASE WHEN p.election_hits!='[]' AND p.ai_hits!='[]' THEN 0 WHEN p.election_hits!='[]' OR p.ai_hits!='[]' THEN 1 ELSE 2 END,i.video_id'''
    out = asrows(c, q)
    for r in out:
        r['screening'] = r.get('screening') or 'unscreened'
        r['playback'] = r['playback_status'] or 'unknown'
        r['priority'] = 'unknown' if r['in_period'] is None else ('high' if r['election_hits'] != '[]' and r['ai_hits'] != '[]' else 'medium' if r['election_hits'] != '[]' or r['ai_hits'] != '[]' else 'low')
        r['fresh'] = bool(r['fetched_at'] and r['fetched_at'] >= cutoff(cfg))
        r['active'] = bool(r['fresh'] and r['retrieval'] == 'public' and r['in_period'])
        r['flag'] = 'absent' if not r['synthetic_field_present'] else ('null' if r['contains_synthetic_media'] is None else str(bool(r['contains_synthetic_media'])).lower())
        r['viewable_now'] = r['api_status'] in ('public', 'unlisted') and r['playback_status'] in (None, 'viewable')
        r['available_for_gate'] = is_available_for_gate(r, cfg)
    return out


def latest(c, table, version):
    return asrows(c, f'SELECT a.* FROM {table} a JOIN (SELECT video_id,' + ('coder,' if table == 'annotations' else '') + f'MAX(id) id FROM {table} WHERE version=? GROUP BY video_id' + (',coder' if table == 'annotations' else '') + ') b ON a.id=b.id', (version,))


def screened_eligible(c, cfg):
    """Reliability sample pool: canonical uploads screened (or adjudicated) as eligible, inside the
    study period and viewable at the last check, so coders spend their time on in-scope videos."""
    finals = {r['video_id']: json.loads(r['payload']).get('eligibility') for r in latest(c, 'finals', cfg['version'])}
    return [r for r in library(c, cfg) if r['group_id'] == r['video_id'] and r['period_flag'] == 1 and r['viewable_now']
            and (r['screening'] == 'eligible' or finals.get(r['video_id']) == 'eligible')]


def validate_annotation(a, duration=None):
    if a.get('origin_judgment', 'uncertain') not in ['suspected_synthetic', 'suspected_genuine', 'uncertain']: raise ValueError('Invalid origin judgment')
    if a.get('eligibility') not in ['eligible', 'excluded', 'uncertain']: raise ValueError('Select eligibility')
    if a['eligibility'] == 'excluded' and a.get('exclusion_reason') not in EXCLUSION_REASONS: raise ValueError('Choose an exclusion reason from the list')
    if a.get('exclusion_reason') and a['exclusion_reason'] not in EXCLUSION_REASONS: raise ValueError('Unknown exclusion reason')
    def codes(data, fields):
        if not isinstance(data, dict): raise ValueError('Codes must be an object')
        for k, v in data.items():
            if k not in fields: raise ValueError('Unknown code ' + k)
            if isinstance(fields[k], list) and v not in fields[k] + ['missing', 'not_applicable', 'uncertain']: raise ValueError('Invalid code ' + k)
            if fields[k] == 'text' and not isinstance(v, str): raise ValueError('Text required for ' + k)
    codes(a.get('video', {}), VIDEO_FIELDS); seen = set()
    for p in a.get('personas', []):
        pid = str(p.get('id', '')).strip()
        if not pid or pid in seen: raise ValueError('Unique persona ID required')
        seen.add(pid); codes(p.get('codes', {}), PERSONA_FIELDS)
        start, end = p.get('start'), p.get('end')
        for v in (start, end):
            if v is not None and (not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0 or (duration is not None and v > duration)): raise ValueError('Invalid persona timestamp')
        if start is not None and end is not None and start > end: raise ValueError('Reversed timestamp')
    if a['eligibility'] == 'eligible' and not seen: raise ValueError('Eligible video requires at least one speaking persona')
    return a


def level(c, vid, version=None):
    """Origin verification level (proposal 7.4). Level 1/2 need evidence covering all speaking personas."""
    ev = asrows(c, 'SELECT * FROM evidence WHERE video_id=?', (vid,)); good = [e for e in ev if e['note'].strip() and e['persona'] == 'all' and (e['source'] or '').strip()]
    if any(e['kind'] == 'fact_check' for e in good): return 1
    if any(e['kind'] in ('creator_disclosure', 'platform_label') for e in good): return 2
    if any(e['kind'] == 'visual_judgment' for e in ev):
        # Two independent coders (any round) judged the personas suspected synthetic.
        rows = asrows(c, "SELECT coder,payload FROM annotations WHERE video_id=? AND coder<>'admin' AND round_id IS NOT NULL ORDER BY id", (vid,))
        last = {}
        for r in rows: last[r['coder']] = json.loads(r['payload'])
        if len([x for x in last.values() if x.get('origin_judgment') == 'suspected_synthetic']) >= 2: return 3
    return 0
