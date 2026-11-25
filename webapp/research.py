"""Coding rounds, reliability and the feasibility report.

Definitions used here are written out in RELIABILITY.md and on the Analysis page.
"""
import json, random
from collections import Counter, defaultdict
from . import core as C

# ---------------------------------------------------------------------------------
# Krippendorff's alpha (nominal) and the two missing-data rules
# ---------------------------------------------------------------------------------
# A slot left as 'missing' (or empty) was never coded. 'not_applicable' is a completed
# judgment but carries no category, so it is left out of alpha. STRICT keeps 'unknown'
# and 'uncertain' as categories and is used for every decision; LOOSE drops them too
# and is shown for comparison only, because it can overstate agreement.
NOT_ENTERED = (None, '', 'missing')
STRICT_DROP = NOT_ENTERED + ('not_applicable',)
LOOSE_DROP = STRICT_DROP + ('unknown', 'uncertain')


def alpha_nominal(groups, drop=STRICT_DROP):
    counts = Counter(); total = 0.; disagree = 0.
    for vals in groups:
        vals = [v for v in vals if v not in drop]; m = len(vals)
        if m < 2: continue
        ct = Counter(vals); total += m; counts.update(ct); disagree += (m * m - sum(n * n for n in ct.values())) / (m - 1)
    if total < 2: return None
    expected = (total * total - sum(n * n for n in counts.values())) / (total - 1)
    return None if expected == 0 else 1 - disagree / expected


def variable_entry(groups, slots):
    """groups: one list of coder values per coded unit that every coder saw.
    slots: all units for this variable, including persona slots that only some coders coded."""
    usable = sum(sum(v not in STRICT_DROP for v in g) >= 2 for g in groups)
    complete = sum(all(v not in NOT_ENTERED for v in g) for g in groups)
    return {'alpha': alpha_nominal(groups, STRICT_DROP), 'usable_pairs': usable,
            'alpha_excluding_uncertain': alpha_nominal(groups, LOOSE_DROP),
            'usable_pairs_excluding_uncertain': sum(sum(v not in LOOSE_DROP for v in g) >= 2 for g in groups),
            'complete_units': complete, 'units': slots, 'completeness': round(complete / slots, 4) if slots else None}


def critical_status(entry, rules):
    if entry['usable_pairs'] < rules['min_pairs']: return 'insufficient_pairs'
    if entry['completeness'] is None or entry['completeness'] < rules['min_completeness']: return 'incomplete'
    if entry['alpha'] is None: return 'undefined'
    return 'met' if entry['alpha'] >= rules['alpha'] else 'below_threshold'


def compute_reliability(subs, codebook, rules):
    """subs: {video_id: {coder: payload}} for one round. Pure function, so stored results
    can be re-derived by the exported analysis script."""
    pairs = {v: d for v, d in subs.items() if len(d) >= 2}
    vfields = [k for k, v in codebook['video'].items() if isinstance(v, list)]
    pfields = [k for k, v in codebook['persona'].items() if isinstance(v, list)]
    out = {}
    for field in ['eligibility', 'origin_judgment'] + vfields:
        getter = (lambda a, f=field: a.get(f)) if field in ('eligibility', 'origin_judgment') else (lambda a, f=field: a.get('video', {}).get(f))
        groups = [[getter(a) for a in d.values()] for d in pairs.values()]
        out[field] = variable_entry(groups, len(groups))
    unmatched = []; persona_groups = defaultdict(list); slots = 0; count_agree = 0; matched = 0
    for vid in sorted(pairs):
        d = pairs[vid]
        sets = {coder: {str(p['id']) for p in a.get('personas', [])} for coder, a in d.items()}
        union = set().union(*sets.values()); inter = set.intersection(*sets.values())
        slots += len(union); matched += len(inter)
        count_agree += int(len({len(s) for s in sets.values()}) == 1)
        for pid in sorted(union - inter):
            unmatched.append({'video_id': vid, 'persona_id': pid,
                              'coded_by': sorted(k for k, s in sets.items() if pid in s),
                              'missing_for': sorted(k for k, s in sets.items() if pid not in s)})
        for pid in sorted(inter):
            byc = {coder: next(p for p in a.get('personas', []) if str(p['id']) == pid).get('codes', {}) for coder, a in d.items()}
            for field in pfields: persona_groups[field].append([byc[k].get(field) for k in sorted(byc)])
    for field in pfields: out[field] = variable_entry(persona_groups[field], slots)
    critical = {k: {'status': critical_status(out[k], rules), **out[k]} for k in rules['critical']}
    enough_videos = len(pairs) >= rules['reliability_n']
    return {'double_coded': len(pairs), 'target_double_coded': rules['reliability_n'], 'enough_double_coded': enough_videos,
            'persona_slots': slots, 'matched_personas': matched, 'unmatched_personas': unmatched,
            'persona_count_agreement': round(count_agree / len(pairs), 4) if pairs else None,
            'variables': out, 'critical': critical,
            'gate_met': enough_videos and all(v['status'] == 'met' for v in critical.values())}


# ---------------------------------------------------------------------------------
# Coding rounds
# ---------------------------------------------------------------------------------

def rules_from_config(cfg):
    t = cfg['thresholds']
    return {'alpha': float(t['alpha']), 'min_pairs': int(t['min_pairs']), 'min_completeness': float(t['min_completeness']),
            'reliability_n': int(t['reliability_n']), 'critical': list(C.CRITICAL_PERSONA), 'missing_rule': 'strict'}


def open_round(c):
    r = c.execute('SELECT * FROM rounds WHERE closed IS NULL ORDER BY id DESC LIMIT 1').fetchone(); return dict(r) if r else None


def create_round(c, cfg, name, coders, n, seed):
    if open_round(c): raise ValueError('Close the open coding round before starting a new one.')
    if len(set(coders)) < 2: raise ValueError('Choose at least two independent coders.')
    known = {r[0] for r in c.execute('SELECT name FROM coders')}
    if not set(coders) <= known: raise ValueError('Unknown coder')
    if not 1 <= int(n) <= 10000: raise ValueError('Sample size must be positive')
    pool = sorted(r['video_id'] for r in C.screened_eligible(c, cfg))
    if not pool: raise ValueError('No screened-eligible videos yet. Mark videos as eligible in the screening field on each video page first.')
    sample = random.Random(int(seed)).sample(pool, min(int(n), len(pool)))
    rules = rules_from_config(cfg)
    cur = c.execute('INSERT INTO rounds(name,codebook_version,codebook,rules,seed,pool_size,created) VALUES(?,?,?,?,?,?,?)',
                    (name.strip() or 'Round', cfg['version'], C.dumps(C.codebook_snapshot(cfg['version'])), C.dumps(rules), int(seed), len(pool), C.now()))
    rid = cur.lastrowid
    for v in sample:
        for coder in sorted(set(coders)): c.execute('INSERT INTO round_assignments VALUES(?,?,?)', (rid, v, coder))
    c.commit(); C.audit(c, 'round_created', {'round': rid, 'seed': int(seed), 'pool': len(pool), 'n': len(sample), 'coders': sorted(set(coders)), 'ids': sample, 'rules': rules, 'codebook_version': cfg['version']})
    return {'round_id': rid, 'assigned': len(sample), 'pool': len(pool)}


def round_submissions(c, rnd):
    """Latest submission per coder and video in the round, made before the round closed."""
    assigned = {(r['video_id'], r['coder']) for r in c.execute('SELECT video_id,coder FROM round_assignments WHERE round_id=?', (rnd['id'],))}
    q = 'SELECT * FROM annotations WHERE round_id=?' + (' AND created<=?' if rnd['closed'] else '') + ' ORDER BY id'
    rows = C.asrows(c, q, (rnd['id'], rnd['closed']) if rnd['closed'] else (rnd['id'],))
    subs = defaultdict(dict)
    for r in rows:
        if (r['video_id'], r['coder']) in assigned: subs[r['video_id']][r['coder']] = {**json.loads(r['payload']), '_submitted': r['created']}
    return subs


def reliability(c, round_id):
    rnd = dict(c.execute('SELECT * FROM rounds WHERE id=?', (round_id,)).fetchone())
    if rnd['closed'] and rnd['result']: return json.loads(rnd['result'])
    subs = round_submissions(c, rnd)
    clean = {v: {k: {x: y for x, y in a.items() if x != '_submitted'} for k, a in d.items()} for v, d in subs.items()}
    res = compute_reliability(clean, json.loads(rnd['codebook']), json.loads(rnd['rules']))
    res.update({'round_id': rnd['id'], 'name': rnd['name'], 'codebook_version': rnd['codebook_version'], 'rules': json.loads(rnd['rules']),
                'closed': rnd['closed'], 'provisional': not rnd['closed']})
    return res


def close_round(c, round_id):
    rnd = c.execute('SELECT * FROM rounds WHERE id=?', (round_id,)).fetchone()
    if not rnd: raise ValueError('Round not found')
    if rnd['closed']: raise ValueError('Round already closed')
    closed = C.now(); c.execute('UPDATE rounds SET closed=? WHERE id=?', (closed, round_id)); c.commit()
    res = reliability(c, round_id); res['closed'] = closed; res['provisional'] = False
    c.execute('UPDATE rounds SET result=? WHERE id=?', (C.dumps(res), round_id)); c.commit()
    C.audit(c, 'round_closed', {'round': round_id, 'gate_met': res['gate_met'], 'double_coded': res['double_coded']})
    return res


def rounds_summary(c):
    out = []
    for r in C.asrows(c, 'SELECT * FROM rounds ORDER BY id'):
        n_assigned = c.execute('SELECT COUNT(*) FROM round_assignments WHERE round_id=?', (r['id'],)).fetchone()[0]
        n_done = c.execute('SELECT COUNT(*) FROM (SELECT DISTINCT a.video_id,a.coder FROM annotations a JOIN round_assignments x ON x.round_id=a.round_id AND x.video_id=a.video_id AND x.coder=a.coder WHERE a.round_id=?)', (r['id'],)).fetchone()[0]
        out.append({'id': r['id'], 'name': r['name'], 'codebook_version': r['codebook_version'], 'rules': json.loads(r['rules']), 'seed': r['seed'], 'pool_size': r['pool_size'],
                    'created': r['created'], 'closed': r['closed'], 'assigned': n_assigned, 'submitted': n_done,
                    'coders': [x[0] for x in c.execute('SELECT DISTINCT coder FROM round_assignments WHERE round_id=? ORDER BY coder', (r['id'],))]})
    return out


def coder_open_round(c, video_id, coder):
    r = c.execute('SELECT r.id FROM rounds r JOIN round_assignments a ON a.round_id=r.id WHERE r.closed IS NULL AND a.video_id=? AND a.coder=? ORDER BY r.id DESC LIMIT 1', (video_id, coder)).fetchone()
    return r[0] if r else None


def video_in_open_round(c, video_id):
    return c.execute('SELECT 1 FROM rounds r JOIN round_assignments a ON a.round_id=r.id WHERE r.closed IS NULL AND a.video_id=?', (video_id,)).fetchone() is not None


# ---------------------------------------------------------------------------------
# Feasibility report
# ---------------------------------------------------------------------------------
NOT_A_PARTY = ('none', 'missing', 'not_applicable', 'uncertain', 'unknown', '')


def report(c, cfg):
    lib = C.library(c, cfg); lookup = {r['video_id']: r for r in lib}
    finals = C.latest(c, 'finals', cfg['version']); t = cfg['thresholds']
    members_of = defaultdict(list)
    for r in lib: members_of[r['group_id'] or r['video_id']].append(r)

    # --- flow (proposal 7.3): identified, grouped, screened, adjudicated, included -------
    canonical = [r for r in lib if (r['group_id'] or r['video_id']) == r['video_id']]
    flow = {'identified_uploads': len(lib),
            'identified_by_source': {r['source']: r['n'] for r in C.asrows(c, 'SELECT source,COUNT(DISTINCT video_id) n FROM discovery GROUP BY source ORDER BY source')},
            'grouped_as_reposts': len(lib) - len(canonical), 'unique_content': len(canonical),
            'screened': sum(r['screening'] != 'unscreened' for r in canonical),
            'screening_eligible': sum(r['screening'] == 'eligible' for r in canonical),
            'screening_uncertain': sum(r['screening'] == 'uncertain' for r in canonical),
            'screening_excluded': sum(r['screening'] == 'excluded' for r in canonical),
            'screening_excluded_by_reason': dict(Counter((r['screening_reason'] or 'not_recorded') for r in canonical if r['screening'] == 'excluded')),
            'adjudicated': 0, 'adjudication_uncertain': 0, 'adjudication_excluded': 0, 'adjudication_excluded_by_reason': Counter(),
            'eligible_adjudicated': 0, 'adjudications_on_reposts_ignored': 0, 'excluded_period_unknown': 0, 'excluded_outside_period': 0, 'eligible_without_origin_evidence': 0}

    groups = {}
    for f in finals:
        a = json.loads(f['payload']); v = f['video_id']; r = lookup.get(v, {})
        if (r.get('group_id') or v) != v: flow['adjudications_on_reposts_ignored'] += 1; continue   # adjudicate the canonical upload
        flow['adjudicated'] += 1
        if a['eligibility'] == 'excluded':
            flow['adjudication_excluded'] += 1; flow['adjudication_excluded_by_reason'][a.get('exclusion_reason') or 'not_recorded'] += 1; continue
        if a['eligibility'] != 'eligible': flow['adjudication_uncertain'] += 1; continue
        flow['eligible_adjudicated'] += 1
        # The in-period classification is a research record that survives the metadata purge.
        # An upload whose period was never established is excluded and counted, never assumed in.
        if r.get('period_flag') is None: flow['excluded_period_unknown'] += 1; continue
        if r.get('period_flag') == 0: flow['excluded_outside_period'] += 1; continue
        lev = C.level(c, v)
        if not lev: flow['eligible_without_origin_evidence'] += 1; continue
        groups[v] = (lev, a)
    flow['adjudication_excluded_by_reason'] = dict(flow['adjudication_excluded_by_reason'])

    # --- content level (unique videos) and upload level (every upload of included content) ---
    rows = []
    for g, (lev, a) in groups.items():
        mem = members_of.get(g) or [lookup.get(g, {'video_id': g})]
        rows.append({'group': g, 'level': lev, 'codes': a, 'members': mem,
                     'available': any(m.get('available_for_gate') for m in mem),
                     'viewable_now': any(m.get('viewable_now') for m in mem),
                     'api_states': [m.get('api_status') or 'not_checked' for m in mem]})
    flow['included'] = len(rows); flow['included_by_level'] = dict(Counter(str(x['level']) for x in rows))
    available = [x for x in rows if x['available']]
    flow['included_available_at_recent_check'] = len(available)
    chan = lambda g: lookup.get(g, {}).get('channel_id') or 'unknown'
    channels_all = {chan(x['group']) for x in rows} - {'unknown'}; channels_av = {chan(x['group']) for x in available} - {'unknown'}
    verified = sum(x['level'] in (1, 2) for x in rows); verified_av = sum(x['level'] in (1, 2) for x in available)

    dist = Counter(); by_level = defaultdict(Counter); messages = Counter(); parties = Counter(); by_channel = Counter()
    cue_counts = {cue: Counter() for cue in C.RQ3_CUES}; cue_by_party = {cue: defaultdict(Counter) for cue in C.RQ3_CUES}
    content_avail = Counter(); content_labels = Counter(); content_playback = Counter()
    up = {'uploads': 0, 'api_status': Counter(), 'playback': Counter(), 'creator_label': Counter(), 'platform_label': Counter(),
          'labels_level_1_3_uploads': Counter()}
    for x in rows:
        g = x['group']; vc = x['codes'].get('video', {}); by_channel[chan(g)] += 1
        party = vc.get('party_favoured', 'missing'); parties[party] += 1
        for cue in C.RQ3_CUES:
            val = vc.get(cue, 'missing'); cue_counts[cue][val] += 1; cue_by_party[cue][party][val] += 1
        for p in x['codes'].get('personas', []):
            codes = p.get('codes', {})
            for k in ('gender', 'age', 'setting', 'disability_marker', 'visible_religion', 'stated_religion', 'visible_occupation', 'stated_occupation', 'voice', 'emotion'):
                dist[k + ':' + codes.get(k, 'missing')] += 1
            by_level[str(x['level'])]['age:' + codes.get('age', 'missing')] += 1
            if codes.get('endorses_party', 'missing') not in NOT_A_PARTY: messages['personas_endorsing_a_party'] += 1
            if codes.get('attacks_party', 'missing') not in NOT_A_PARTY: messages['personas_attacking_a_party'] += 1
            if codes.get('factual_claim') == 'yes': messages['personas_with_factual_claim'] += 1
            if str(codes.get('issues', '')).strip(): messages['personas_raising_issues'] += 1
        content_avail['viewable_at_last_check' if x['viewable_now'] else 'not_viewable_at_last_check'] += 1
        content_playback[next((m.get('playback_status') for m in x['members'] if m.get('playback_status')), 'not_checked')] += 1
        if x['level'] in (1, 3):
            content_labels['creator:' + ('yes' if any(m.get('creator_label') == 'yes' for m in x['members']) else 'no_or_unknown')] += 1
            content_labels['platform:' + ('yes' if any(m.get('platform_label') == 'yes' for m in x['members']) else 'no_or_unknown')] += 1
        for m in x['members']:
            up['uploads'] += 1; up['api_status'][m.get('api_status') or 'not_checked'] += 1; up['playback'][m.get('playback_status') or 'not_checked'] += 1
            up['creator_label'][m.get('creator_label') or 'unknown'] += 1; up['platform_label'][m.get('platform_label') or 'unknown'] += 1
            if x['level'] in (1, 3):
                up['labels_level_1_3_uploads']['creator:' + (m.get('creator_label') or 'unknown')] += 1
                up['labels_level_1_3_uploads']['platform:' + (m.get('platform_label') or 'unknown')] += 1
    checks = [m.get('api_checked') for x in rows for m in x['members'] if m.get('api_checked')]
    stale = sum(1 for x in rows if x['viewable_now'] and not x['available'])

    # --- reliability: the gate uses the latest closed round; an open round is provisional --
    summaries = rounds_summary(c); closed = [s for s in summaries if s['closed']]; open_ = [s for s in summaries if not s['closed']]
    gate_round = reliability(c, closed[-1]['id']) if closed else None
    provisional = reliability(c, open_[-1]['id']) if open_ else None
    rel_cond = None if gate_round is None else bool(gate_round['gate_met'])
    lit = True if cfg['literature'] == 'clear' and cfg['literature_note'].strip() else False if cfg['literature'] == 'overlap' else None
    perms = all(cfg['permissions'][k] for k in ['ethics', 'collection', 'analysis'])
    cond = {'eligible_available': len(available) >= t['videos'], 'channels_available': len(channels_av) >= t['channels'],
            'verified_share': None if not available else verified_av / len(available) * 100 >= t['verified'],
            'reliability': rel_cond, 'literature': lit, 'permissions': perms}
    checklist = _checklist(cfg, t, cond, len(available), len(channels_av), verified_av, stale, gate_round, provisional, summaries, flow)
    return {'app_version': C.APP_VERSION, 'discovered': len(lib), 'active': sum(r['active'] for r in lib), 'unavailable': sum(r['retrieval'] == 'unavailable' for r in lib),
            'screened': c.execute('SELECT COUNT(DISTINCT video_id) FROM model_runs WHERE ok=1').fetchone()[0], 'screened_eligible': flow['screening_eligible'],
            'finalized': flow['adjudicated'], 'excluded': flow['adjudication_excluded'],
            'eligible_unique': len(rows), 'eligible_available': len(available), 'channels': len(channels_all), 'channels_available': len(channels_av),
            'verified': verified, 'verified_pct': round(verified / len(rows) * 100, 2) if rows else None,
            'verified_available_pct': round(verified_av / len(available) * 100, 2) if available else None,
            'stale_availability': stale, 'availability_window_days': int(t['availability_max_age_days']),
            'conditions': cond, 'decision': 'MET' if all(v is True for v in cond.values()) else 'NOT ESTABLISHED', 'checklist': checklist,
            'reliability': {'gate_round': gate_round, 'provisional_round': provisional, 'rounds': summaries},
            'flow': flow,
            'content_level': {'groups': len(rows), 'availability': dict(content_avail), 'playback': dict(content_playback), 'labels_level_1_3': dict(content_labels),
                              'evidence_levels': dict(Counter(str(x['level']) for x in rows)), 'party_favoured': dict(parties), 'distributions': dict(dist),
                              'message_counts': dict(messages), 'age_by_evidence_level': {k: dict(v) for k, v in by_level.items()}},
            'upload_level': {k: (dict(v) if isinstance(v, Counter) else v) for k, v in up.items()},
            'rq3': {'cues': {k: dict(v) for k, v in cue_counts.items()}, 'by_party': {k: {p: dict(cnt) for p, cnt in v.items()} for k, v in cue_by_party.items()}},
            'availability_checks': {'oldest': min(checks) if checks else None, 'newest': max(checks) if checks else None},
            'channel_concentration': {'distinct_channels': len(by_channel), 'largest_channel_count': max(by_channel.values(), default=0), 'leave_largest_channel_out_n': len(rows) - max(by_channel.values(), default=0)},
            'note': 'Counts describe the discoverable corpus, not a platform census. Coded eligible videos stay in the corpus after removal; availability is reported as an outcome. Content level counts each unique video once; upload level counts every upload of included content.'}


def _checklist(cfg, t, cond, n_av, ch_av, ver_av, stale, gate_round, provisional, rounds, flow):
    def item(key, label, current, target, action_met, action_unmet):
        status = 'met' if cond[key] is True else 'pending' if cond[key] is None else 'not_met'
        return {'id': key, 'criterion': label, 'status': status, 'current': current, 'target': target, 'action': action_met if status == 'met' else action_unmet}
    out = [item('permissions', 'Ethics, collection and analysis permissions recorded', 'recorded' if cond['permissions'] else 'not recorded', 'all three recorded',
                'No action.', 'Record each permission in Research setup once it has actually been granted.'),
           item('eligible_available', 'Eligible unique videos available at a recent check', n_av, t['videos'],
                'No action.', ('Refresh metadata: ' + str(stale) + ' included videos have an availability check older than ' + str(t['availability_max_age_days']) + ' days. ' if stale else '')
                + 'Screen more candidates, adjudicate eligible videos and record origin evidence. ' + str(flow['eligible_without_origin_evidence']) + ' eligible videos still lack origin evidence.'),
           item('channels_available', 'Channels contributing available eligible videos', ch_av, t['channels'], 'No action.', 'Add channels of confirmed videos as seeds and expand them, or import more fact-check leads.'),
           item('verified_share', 'Share of available eligible videos verified at Level 1 or 2', f'{round(ver_av / n_av * 100, 1)}%' if n_av else 'no videos yet', f"{t['verified']}%",
                'No action.', 'Look for fact-checks (Level 1) or explicit disclosures covering every speaking persona (Level 2) for Level 3 videos.')]
    if gate_round is None:
        rel_action = ('Finish coding the open round, then close it on the Coding page to run the reliability assessment.' if provisional else
                      'Mark at least ' + str(t['reliability_n']) + ' videos eligible in screening, then create a coding round on the Coding page.')
        current = 'no closed round'
    else:
        failing = [f"{k}: {v['status'].replace('_', ' ')}" for k, v in gate_round['critical'].items() if v['status'] != 'met']
        if not gate_round['enough_double_coded']: failing.insert(0, f"double-coded videos {gate_round['double_coded']} of {gate_round['target_double_coded']}")
        current = 'met' if gate_round['gate_met'] else '; '.join(failing)
        rel_action = 'Revise the codebook for failing variables, bump the codebook version in Research setup, and run a second round (the proposal allows one revision).'
    out.append(item('reliability', 'Reliability on identity and endorsement codes (latest closed round)', current,
                    f"alpha >= {t['alpha']}, >= {t['min_pairs']} usable pairs, >= {int(float(t['min_completeness']) * 100)}% complete", 'No action.', rel_action))
    out.append(item('literature', 'Structured literature search finds no overlapping study', cfg['literature'], 'clear, with a written note',
                    'No action.', 'Run the Scopus search and record the method and result in Research setup.'))
    return out
