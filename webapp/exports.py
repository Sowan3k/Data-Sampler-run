"""Research exports: search log, coded dataset and the reproducibility package.

Exports contain the researcher's own records only: discovery provenance, search logs,
dated observations, codes, evidence levels and reliability results. They never contain
YouTube API metadata (titles, descriptions, tags, statistics) or raw model output.
Video, channel and group IDs are replaced with stable pseudonymous keys unless the
'id_export' permission is recorded.
"""
import csv, hashlib, hmac, io, json, secrets, zipfile
from pathlib import Path
from . import core as C, research as R

ANALYSIS_SCRIPT = Path(__file__).resolve().parent / 'analysis' / 'analysis.py'


class Keys:
    """Maps real IDs to stable pseudonymous keys with a per-project secret salt."""
    def __init__(self, data_dir, use_real_ids):
        self.real = use_real_ids
        salt_file = Path(data_dir) / 'export.salt'
        if not salt_file.exists(): salt_file.write_text(secrets.token_hex(32))
        self.salt = salt_file.read_text().strip().encode()
        self.seen = {}

    def __call__(self, kind, value):
        if value in (None, ''): return ''
        if self.real: return value
        k = kind[0].upper() + hmac.new(self.salt, f'{kind}:{value}'.encode(), hashlib.sha256).hexdigest()[:12]
        self.seen[value] = k; return k

    def scrub(self, obj):
        """Replace any real ID seen so far wherever it appears as a whole string value."""
        if self.real: return obj
        if isinstance(obj, dict): return {self.seen.get(k, k): self.scrub(v) for k, v in obj.items()}
        if isinstance(obj, list): return [self.scrub(v) for v in obj]
        if isinstance(obj, str): return self.seen.get(obj, obj)
        return obj


def _csv(rows, header):
    s = io.StringIO(); w = csv.DictWriter(s, fieldnames=header, extrasaction='ignore'); w.writeheader()
    for r in rows: w.writerow({k: ('' if r.get(k) is None else r.get(k)) for k in header})
    return s.getvalue()


def search_log_csv(c):
    rows = C.asrows(c, 'SELECT query,order_by,published_after,published_before,page,result_count,total_results,run_at FROM search_log ORDER BY id')
    return _csv(rows, ['query', 'order_by', 'published_after', 'published_before', 'page', 'result_count', 'total_results', 'run_at'])


def discovery_summary_csv(c):
    rows = C.asrows(c, 'SELECT source,COUNT(DISTINCT video_id) distinct_videos,COUNT(*) records FROM discovery GROUP BY source ORDER BY source')
    return _csv(rows, ['source', 'distinct_videos', 'records'])


def dataset_tables(c, cfg, keys):
    lib = C.library(c, cfg); lookup = {r['video_id']: r for r in lib}
    rep = R.report(c, cfg); included = {x for x in _included_groups(c, cfg, lib)}
    vfields = list(C.VIDEO_FIELDS); pfields = list(C.PERSONA_FIELDS)
    videos, personas = [], []
    for f in C.latest(c, 'finals', cfg['version']):
        a = json.loads(f['payload']); v = f['video_id']; r = lookup.get(v, {}); g = r.get('group_id') or v
        row = {'video_key': keys('video', v), 'group_key': keys('group', g), 'channel_key': keys('channel', r.get('channel_id')),
               'canonical': int(g == v), 'eligibility': a.get('eligibility'), 'exclusion_reason': a.get('exclusion_reason', ''),
               'origin_judgment': a.get('origin_judgment', ''), 'evidence_level': C.level(c, v), 'included': int(v in included),
               'in_study_period': r.get('period_flag'), 'api_status': r.get('api_status'), 'api_checked': r.get('api_checked'),
               'playback_status': r.get('playback_status'), 'playback_checked': r.get('playback_checked'), 'playback_reason': r.get('playback_reason'),
               'creator_label': r.get('creator_label'), 'platform_label': r.get('platform_label'), 'label_observed': r.get('label_at'),
               'available_for_gate': int(bool(r.get('available_for_gate'))), 'adjudicated_at': f['created'], 'codebook_version': f['version']}
        for k in vfields: row['v_' + k] = a.get('video', {}).get(k, 'missing' if isinstance(C.VIDEO_FIELDS[k], list) else '')
        videos.append(row)
        for p in a.get('personas', []):
            prow = {'video_key': keys('video', v), 'group_key': keys('group', g), 'persona_id': p.get('id'), 'start_s': p.get('start'), 'end_s': p.get('end'), 'included': int(v in included)}
            for k in pfields: prow['p_' + k] = p.get('codes', {}).get(k, 'missing' if isinstance(C.PERSONA_FIELDS[k], list) else '')
            personas.append(prow)
    groups = {r['group_id'] or r['video_id'] for r in lib if (r['group_id'] or r['video_id']) in {f['video_id'] for f in C.latest(c, 'finals', cfg['version'])}}
    uploads = [{'upload_key': keys('video', r['video_id']), 'group_key': keys('group', r['group_id'] or r['video_id']), 'channel_key': keys('channel', r.get('channel_id')),
                'canonical': int((r['group_id'] or r['video_id']) == r['video_id']), 'group_included': int((r['group_id'] or r['video_id']) in included),
                'in_study_period': r.get('period_flag'), 'screening': r['screening'], 'screening_reason': r.get('screening_reason'),
                'api_status': r.get('api_status'), 'api_checked': r.get('api_checked'), 'playback_status': r.get('playback_status'), 'playback_checked': r.get('playback_checked'),
                'creator_label': r.get('creator_label'), 'platform_label': r.get('platform_label'), 'label_observed': r.get('label_at')}
               for r in lib if (r['group_id'] or r['video_id']) in groups]
    annotations = []; rounds = []
    for s in R.rounds_summary(c):
        rnd = dict(c.execute('SELECT * FROM rounds WHERE id=?', (s['id'],)).fetchone())
        for vid, d in R.round_submissions(c, rnd).items():
            for coder, a in d.items():
                base = {'round_id': s['id'], 'codebook_version': rnd['codebook_version'], 'coder': coder, 'video_key': keys('video', vid), 'submitted_at': a.get('_submitted')}
                for k in ('eligibility', 'origin_judgment'): annotations.append({**base, 'unit': 'video', 'persona_id': '', 'variable': k, 'value': a.get(k, 'missing')})
                for k, v in a.get('video', {}).items(): annotations.append({**base, 'unit': 'video', 'persona_id': '', 'variable': k, 'value': v})
                for p in a.get('personas', []):
                    for k, v in p.get('codes', {}).items(): annotations.append({**base, 'unit': 'persona', 'persona_id': p.get('id'), 'variable': k, 'value': v})
                    annotations.append({**base, 'unit': 'persona', 'persona_id': p.get('id'), 'variable': '_present', 'value': 'yes'})
        res = R.reliability(c, s['id'])
        rounds.append({**s, 'codebook': json.loads(rnd['codebook']), 'result': res})
    return {'videos': videos, 'personas': personas, 'uploads': uploads, 'annotations': annotations, 'rounds': rounds, 'report': rep,
            'headers': {'videos': list(videos[0]) if videos else ['video_key'], 'personas': list(personas[0]) if personas else ['video_key'],
                        'uploads': list(uploads[0]) if uploads else ['upload_key'],
                        'annotations': ['round_id', 'codebook_version', 'coder', 'video_key', 'unit', 'persona_id', 'variable', 'value', 'submitted_at']}}


def _included_groups(c, cfg, lib):
    lookup = {r['video_id']: r for r in lib}
    for f in C.latest(c, 'finals', cfg['version']):
        a = json.loads(f['payload']); v = f['video_id']; r = lookup.get(v, {})
        if (r.get('group_id') or v) == v and a.get('eligibility') == 'eligible' and r.get('period_flag') == 1 and C.level(c, v):
            yield v


def _public_config(cfg, keys):
    out = json.loads(C.dumps(cfg))
    if not keys.real: out['seeds'] = {'note': 'Seed handles, channel IDs and video IDs withheld without the id_export permission.'}
    out['storage'] = {'api_data_max_age_days': cfg['storage']['api_data_max_age_days']}
    return out


def dataset_zip(c, cfg, data_dir):
    keys = Keys(data_dir, cfg['permissions'].get('id_export', False)); t = dataset_tables(c, cfg, keys)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('coded_videos.csv', _csv(t['videos'], t['headers']['videos']))
        z.writestr('coded_personas.csv', _csv(t['personas'], t['headers']['personas']))
        z.writestr('uploads.csv', _csv(t['uploads'], t['headers']['uploads']))
        z.writestr('independent_annotations.csv', _csv(t['annotations'], t['headers']['annotations']))
        z.writestr('README.txt', _dataset_readme(keys.real))
    return buf.getvalue()


def package_zip(c, cfg, data_dir):
    keys = Keys(data_dir, cfg['permissions'].get('id_export', False)); t = dataset_tables(c, cfg, keys)
    files = {
        'data/coded_videos.csv': _csv(t['videos'], t['headers']['videos']),
        'data/coded_personas.csv': _csv(t['personas'], t['headers']['personas']),
        'data/uploads.csv': _csv(t['uploads'], t['headers']['uploads']),
        'data/independent_annotations.csv': _csv(t['annotations'], t['headers']['annotations']),
        'data/search_log.csv': search_log_csv(c),
        'data/discovery_summary.csv': discovery_summary_csv(c),
        'data/flow.json': json.dumps(keys.scrub(t['report']['flow']), ensure_ascii=False, indent=2),
        'reliability/rounds.json': json.dumps(keys.scrub(t['rounds']), ensure_ascii=False, indent=2),
        'results/feasibility_report.json': json.dumps(keys.scrub(t['report']), ensure_ascii=False, indent=2),
        'codebook/codebook.json': json.dumps(C.codebook_snapshot(cfg['version']), ensure_ascii=False, indent=2),
        'config/study_config.json': json.dumps(_public_config(cfg, keys), ensure_ascii=False, indent=2),
        'analysis/analysis.py': ANALYSIS_SCRIPT.read_text(encoding='utf-8'),
        'README.md': _package_readme(keys.real, cfg),
    }
    manifest = {name: hashlib.sha256(body.encode('utf-8')).hexdigest() for name, body in files.items()}
    files['MANIFEST.json'] = json.dumps({'app_version': C.APP_VERSION, 'created': C.now(), 'real_ids': keys.real, 'sha256': manifest}, indent=2)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, body in files.items(): z.writestr('reproducibility_package/' + name, body)
    return buf.getvalue()


def _dataset_readme(real):
    return ('Coded dataset exported from the Synthetic Citizens control centre.\n\n'
            'coded_videos.csv: one row per adjudicated upload (adjudicated codes, evidence level, inclusion, dated observations).\n'
            'coded_personas.csv: one row per speaking persona in adjudicated uploads.\n'
            'uploads.csv: every upload of adjudicated content, for upload-level disclosure and availability.\n'
            'independent_annotations.csv: long format, one row per coder, video, persona and variable, per coding round.\n\n'
            + ('IDs are real YouTube IDs (id_export permission recorded).\n' if real else
               'IDs are pseudonymous keys. The mapping stays on the research computer and is not exported.\n')
            + 'No YouTube API metadata or model output is included.\n')


def _package_readme(real, cfg):
    return f"""# Reproducibility package

Study: {cfg['title']}. Codebook version {cfg['version']}. Exported by the control centre version {C.APP_VERSION}.

## Contents

- `data/coded_videos.csv`, `data/coded_personas.csv`: adjudicated codes. `included` marks the analysed corpus (eligible, inside the study period, with origin evidence; reposts grouped).
- `data/uploads.csv`: every upload of adjudicated content, for upload-level disclosure and availability (RQ4).
- `data/independent_annotations.csv`: independent coder submissions per round, the input to reliability.
- `data/search_log.csv`, `data/discovery_summary.csv`: logged keyword searches and discovery sources for the methods section.
- `data/flow.json`: identification, screening, exclusion reasons and inclusion counts for the flow diagram.
- `reliability/rounds.json`: each coding round with its frozen codebook, pre-registered rules and stored result.
- `results/feasibility_report.json`: the report as shown in the application.
- `codebook/codebook.json`, `config/study_config.json`: codebook and study settings (no API keys).
- `analysis/analysis.py`: re-computes the descriptive tables and every round's reliability from the CSV files, and checks them against the stored results.

## Run the analysis

Python 3.10 or later, standard library only:

```
python analysis/analysis.py
```

It prints the tables, writes `results/analysis_results.json`, and exits with code 1 if a recomputed reliability result differs from the stored one.

## Data notes

{'IDs are real YouTube IDs because the id_export permission was recorded.' if real else 'IDs are pseudonymous keys. The mapping stays on the research computer.'} The package contains no YouTube API metadata (titles, descriptions, tags, statistics) and no model output. Availability and label columns are dated observations, not election-time states.
"""
