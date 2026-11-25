"""Reproduce the descriptive tables and reliability results from an exported package.

Standard library only. Run from the package root:

    python analysis/analysis.py

Prints the tables, writes results/analysis_results.json and exits with code 1 if any
recomputed reliability result or headline count differs from the stored one.
"""
import csv, json, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOT_ENTERED = (None, '', 'missing')
STRICT_DROP = NOT_ENTERED + ('not_applicable',)
LOOSE_DROP = STRICT_DROP + ('unknown', 'uncertain')
NOT_A_PARTY = ('none', 'missing', 'not_applicable', 'uncertain', 'unknown', '')
RQ1 = ['gender', 'age', 'setting', 'disability_marker', 'visible_religion', 'stated_religion', 'visible_occupation', 'stated_occupation', 'voice', 'emotion']
RQ3 = ['format', 'interviewer', 'news_brand', 'captions', 'uniforms', 'regional_dialect', 'production_artifacts']


def read(name):
    with open(ROOT / name, encoding='utf-8') as fh: return list(csv.DictReader(fh))


def alpha_nominal(groups, drop=STRICT_DROP):
    counts = Counter(); total = 0.; disagree = 0.
    for vals in groups:
        vals = [v for v in vals if v not in drop]; m = len(vals)
        if m < 2: continue
        ct = Counter(vals); total += m; counts.update(ct); disagree += (m * m - sum(n * n for n in ct.values())) / (m - 1)
    if total < 2: return None
    expected = (total * total - sum(n * n for n in counts.values())) / (total - 1)
    return None if expected == 0 else 1 - disagree / expected


def entry(groups, slots):
    usable = sum(sum(v not in STRICT_DROP for v in g) >= 2 for g in groups)
    complete = sum(all(v not in NOT_ENTERED for v in g) for g in groups)
    return {'alpha': alpha_nominal(groups), 'usable_pairs': usable, 'alpha_excluding_uncertain': alpha_nominal(groups, LOOSE_DROP),
            'complete_units': complete, 'units': slots, 'completeness': round(complete / slots, 4) if slots else None}


def status(e, rules):
    if e['usable_pairs'] < rules['min_pairs']: return 'insufficient_pairs'
    if e['completeness'] is None or e['completeness'] < rules['min_completeness']: return 'incomplete'
    if e['alpha'] is None: return 'undefined'
    return 'met' if e['alpha'] >= rules['alpha'] else 'below_threshold'


def rebuild_submissions(rows):
    subs = defaultdict(lambda: defaultdict(lambda: {'video': {}, 'personas': {}}))
    for r in rows:
        a = subs[r['round_id']][(r['video_key'], r['coder'])]
        if r['unit'] == 'video':
            if r['variable'] in ('eligibility', 'origin_judgment'): a[r['variable']] = r['value']
            else: a['video'][r['variable']] = r['value']
        else:
            p = a['personas'].setdefault(r['persona_id'], {})
            if r['variable'] != '_present': p[r['variable']] = r['value']
    out = {}
    for rid, d in subs.items():
        byvid = defaultdict(dict)
        for (vid, coder), a in d.items(): byvid[vid][coder] = a
        out[rid] = byvid
    return out


def reliability(subs, codebook, rules):
    pairs = {v: d for v, d in subs.items() if len(d) >= 2}
    vfields = [k for k, v in codebook['video'].items() if isinstance(v, list)]
    pfields = [k for k, v in codebook['persona'].items() if isinstance(v, list)]
    out = {}
    for f in ['eligibility', 'origin_judgment'] + vfields:
        get = (lambda a, f=f: a.get(f)) if f in ('eligibility', 'origin_judgment') else (lambda a, f=f: a['video'].get(f))
        groups = [[get(a) for a in d.values()] for d in pairs.values()]; out[f] = entry(groups, len(groups))
    slots = 0; unmatched = 0; pg = defaultdict(list)
    for vid in sorted(pairs):
        d = pairs[vid]; sets = {k: set(a['personas']) for k, a in d.items()}
        union = set().union(*sets.values()); inter = set.intersection(*sets.values()); slots += len(union); unmatched += len(union - inter)
        for pid in sorted(inter):
            for f in pfields: pg[f].append([d[k]['personas'][pid].get(f) for k in sorted(d)])
    for f in pfields: out[f] = entry(pg[f], slots)
    crit = {k: status(out[k], rules) for k in rules['critical']}
    return {'double_coded': len(pairs), 'unmatched': unmatched, 'variables': out, 'critical': crit,
            'gate_met': len(pairs) >= rules['reliability_n'] and all(v == 'met' for v in crit.values())}


def close(a, b):
    if a is None or b is None: return a is None and b is None
    return abs(a - b) < 1e-9


def table(title, counter):
    print(f'\n{title}')
    for k, v in sorted(counter.items(), key=lambda x: (-x[1], str(x[0]))): print(f'  {v:>5}  {k}')


def main():
    problems = []
    videos = read('data/coded_videos.csv'); personas = read('data/coded_personas.csv'); uploads = read('data/uploads.csv')
    report = json.loads((ROOT / 'results/feasibility_report.json').read_text(encoding='utf-8'))
    rounds = json.loads((ROOT / 'reliability/rounds.json').read_text(encoding='utf-8'))
    included = [v for v in videos if v['included'] == '1' and v['canonical'] == '1']
    inc_keys = {v['video_key'] for v in included}
    print(f'Included unique videos: {len(included)}')
    if len(included) != report['eligible_unique']: problems.append(f"included count {len(included)} != report {report['eligible_unique']}")

    # RQ1 and RQ2 (persona level), RQ3 (video level), RQ4 (content and upload level)
    dist = Counter(); msgs = Counter()
    for p in personas:
        if p['video_key'] not in inc_keys: continue
        for k in RQ1: dist[k + ':' + p['p_' + k]] += 1
        if p['p_endorses_party'] not in NOT_A_PARTY: msgs['personas_endorsing_a_party'] += 1
        if p['p_attacks_party'] not in NOT_A_PARTY: msgs['personas_attacking_a_party'] += 1
        if p['p_factual_claim'] == 'yes': msgs['personas_with_factual_claim'] += 1
        if p['p_issues'].strip(): msgs['personas_raising_issues'] += 1
    parties = Counter(v['v_party_favoured'] for v in included)
    cues = {c: Counter(v['v_' + c] for v in included) for c in RQ3}
    by_level = Counter(v['evidence_level'] for v in included)
    members = defaultdict(list)
    for u in uploads: members[u['group_key']].append(u)
    labels = Counter()
    for v in included:
        if v['evidence_level'] in ('1', '3'):
            m = members.get(v['group_key'], [])
            labels['creator:' + ('yes' if any(x['creator_label'] == 'yes' for x in m) else 'no_or_unknown')] += 1
            labels['platform:' + ('yes' if any(x['platform_label'] == 'yes' for x in m) else 'no_or_unknown')] += 1
    upload_status = Counter(u['api_status'] or 'not_checked' for u in uploads if u['group_included'] == '1')
    table('RQ1 identity markers (persona level)', dist); table('RQ2 messages (persona level)', msgs)
    table('Party favoured (video level)', parties)
    for c in RQ3: table(f'RQ3 {c}', cues[c])
    table('Evidence level', by_level); table('RQ4 labels, Level 1 and 3 content', labels); table('RQ4 API status, uploads of included content', upload_status)
    cl = report['content_level']
    for name, mine, theirs in [('party_favoured', parties, cl['party_favoured']), ('distributions', dist, cl['distributions']),
                               ('message_counts', msgs, cl['message_counts']), ('labels_level_1_3', labels, cl['labels_level_1_3'])]:
        if dict(mine) != theirs: problems.append(f'{name} differs from the stored report')
    for c in RQ3:
        if dict(cues[c]) != report['rq3']['cues'][c]: problems.append(f'RQ3 {c} differs from the stored report')

    # Reliability, per round, against the stored results
    subs = rebuild_submissions(read('data/independent_annotations.csv'))
    rel_out = {}
    for rnd in rounds:
        rid = str(rnd['id']); res = reliability(subs.get(rid, {}), rnd['codebook'], rnd['rules']); stored = rnd['result']; rel_out[rid] = res
        print(f"\nReliability, round {rid} ({rnd['name']}, codebook {rnd['codebook_version']}): {res['double_coded']} double-coded, "
              f"{res['unmatched']} unmatched personas, gate {'met' if res['gate_met'] else 'not met'}")
        for k in rnd['rules']['critical']:
            e = res['variables'][k]; print(f"  {k}: alpha {e['alpha']}, usable pairs {e['usable_pairs']}, completeness {e['completeness']}, {res['critical'][k]}")
        if res['double_coded'] != stored['double_coded'] or res['unmatched'] != len(stored['unmatched_personas']) or res['gate_met'] != stored['gate_met']:
            problems.append(f'round {rid}: headline reliability differs from stored result')
        for k, e in res['variables'].items():
            s = stored['variables'][k]
            if not (close(e['alpha'], s['alpha']) and e['usable_pairs'] == s['usable_pairs'] and e['completeness'] == s['completeness']):
                problems.append(f'round {rid}: {k} differs from stored result')

    out = ROOT / 'results' / 'analysis_results.json'; out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({'included': len(included), 'rq1': dict(dist), 'rq2': dict(msgs), 'party_favoured': dict(parties),
                               'rq3': {c: dict(v) for c, v in cues.items()}, 'evidence_levels': dict(by_level), 'rq4_labels': dict(labels),
                               'rq4_upload_api_status': dict(upload_status), 'reliability': rel_out, 'problems': problems}, indent=2, ensure_ascii=False), encoding='utf-8')
    print('\nReproduction check: ' + ('all recomputed values match the stored results.' if not problems else 'DIFFERENCES FOUND:\n  ' + '\n  '.join(problems)))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
