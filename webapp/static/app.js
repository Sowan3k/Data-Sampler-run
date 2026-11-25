'use strict';
// Synthetic Citizens control centre, browser client (v0.3.1). Plain JavaScript, no build step.
const $ = s => document.querySelector(s), root = $('#content');
const esc = x => String(x ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const line = x => esc(x).replace(/\n/g, '<br>');
const pretty = x => String(x ?? '').replaceAll('_', ' ');
const fmtDate = x => x ? esc(String(x).slice(0, 16).replace('T', ' ')) : '<span class="muted">never</span>';
const pct = x => x === null || x === undefined ? '—' : (Math.round(x * 1000) / 10) + '%';
const fix3 = x => x === null || x === undefined ? 'undefined' : Number(x).toFixed(3);

let token = sessionStorage.getItem('sc-token') || '', role = '', page = 'Overview', cfg = null, lib = [], video = null, book = null, draft = null;
let viewId = 0, queueTimer = null, libShown = 100, navIds = [], dirty = false, draftTimer = null;
if (location.hash.startsWith('#token=')) { token = decodeURIComponent(location.hash.slice(7)); sessionStorage.setItem('sc-token', token); history.replaceState(null, '', location.pathname); }

const NAV = [['START', ['Overview', 'Research setup', 'API connections']], ['COLLECT', ['Data discovery', 'Video library', 'AI screening', 'Jobs']],
             ['VERIFY', ['Coding & reliability', 'Analysis & reports', 'Data compliance']], ['SUPPORT', ['Activity log', 'Help']]];

// Every page explains its purpose, how to read it, and what to do next.
const PAGE_HELP = {
  'Overview': ['Shows where the study stands and the next action.', 'Each step is marked done or pending. Numbers count records in this computer\'s database only.', 'Follow the first step marked pending.'],
  'Research setup': ['Defines the study: period, search terms, feasibility thresholds, reliability rules and recorded permissions.', 'Reliability rules are copied into a coding round when you create it. Changing them later does not alter a round already started.', 'Save, then open API connections.'],
  'API connections': ['Connects YouTube (needed for collection) and Gemini (optional AI drafts).', '"Connection responded" means the service answered a test request. It does not mean you have permission to use the data.', 'Open Data discovery.'],
  'Data discovery': ['Brings video leads into the database: fact-check links, seed channels and logged keyword searches.', 'Every imported ID is a lead, not a finding. Collection runs as background jobs; watch them on the Jobs page.', 'Expand the seed channels, then open the Video library.'],
  'Video library': ['Lists every upload found, with priority, study period, dated availability checks and your screening decision.', 'Priority comes from words in titles and descriptions and only orders the list; low priority is never excluded. "out" under Period means the upload date is outside the study; "unknown" means metadata was never retrieved.', 'Open unscreened videos from the top and record a screening decision on each.'],
  'AI screening': ['Optional. Asks Gemini to draft observations for public videos.', 'A draft is never evidence that a video is AI-generated and never decides eligibility. Compare it with your own viewing.', 'Review drafts on each video page.'],
  'Jobs': ['Shows background collection and screening jobs.', 'Queued: waiting. Running: working now. Paused: stopped between requests; Resume continues from the last checkpoint. Failed: read the error, fix the cause, then Retry.', 'Return to the Video library when a job completes.'],
  'Coding & reliability': ['Runs independent double-coding rounds and closes them to produce the reliability assessment.', 'A round samples screened-eligible videos at random with a recorded seed. Coders see only their own work. Closing a round freezes its result; later edits cannot change it.', 'Create two coder tokens, start a round, wait until every assignment is submitted, then close the round.'],
  'My assignments': ['Lists the videos assigned to you for independent coding.', 'Submitted means your answer is saved. You can revise it until the administrator closes the round. Do not discuss videos with the other coder.', 'Open the first pending video, then use "Next uncoded" to move through the list.'],
  'Analysis & reports': ['Answers the feasibility question in section 7.9 of the proposal and shows the descriptive results.', 'The coded corpus is every eligible video with origin evidence; it stays fixed after removals. The decision counts only videos available at a recent check. Content level counts each video once; upload level counts every repost.', 'Work through the unmet checklist items from top to bottom.'],
  'Data compliance': ['Keeps YouTube API data within the 30-day rule and produces the research exports.', 'Refresh re-checks every upload. Exports contain your own codes and observations only, with IDs replaced by keys unless ID export is permitted.', 'Refresh metadata before reading the report or exporting.'],
  'Activity log': ['Records configuration changes, imports, coding rounds and exports.', 'Use it to document the procedure in the methods section.', 'No action needed.'],
  'Help': ['Explains the terms and rules used in this workspace.', 'Read "Coding rules" before your first video.', 'Return to your assignments or the library.'],
  'Video review': ['Watch one video, record what you observe, and code it.', 'The legend above the codes explains missing, unknown, uncertain and not applicable. Your work is kept as a draft on this device until you submit it.', 'Submit, then use "Next uncoded" (coders) or "Next unscreened" (administrator).'],
};

// --- small builders ------------------------------------------------------------------
function notice(t, err = false) { $('#notice').textContent = t; $('#notice').className = err ? 'error' : ''; }
async function api(path, method = 'GET', data) {
  const r = await fetch('/api' + path, {method, headers: {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}, ...(data === undefined ? {} : {body: JSON.stringify(data)})});
  if (!r.ok) { let t = await r.text(); try { t = JSON.parse(t).detail; } catch {} throw Error(typeof t === 'string' ? t : JSON.stringify(t)); }
  return r.json();
}
function btn(t, action, cls = '') { return `<button type="button" class="${cls}" data-action="${esc(action)}">${esc(t)}</button>`; }
function inp(id, v = '', type = 'text', extra = '') { return `<input id="${id}" type="${type}" value="${esc(v)}" ${extra}>`; }
function field(label, body, help = '') { return `<label for="${(body.match(/id="([^"]+)"/) || [])[1] || ''}">${esc(label)}</label>${body}${help ? `<small class="fieldhelp">${esc(help)}</small>` : ''}`; }
function ta(id, v = '', rows = 4) { return `<textarea id="${id}" rows="${rows}">${esc(v)}</textarea>`; }
function sel(id, values, v) { return `<select id="${id}">${values.map(x => `<option value="${esc(x)}" ${x === v ? 'selected' : ''}>${esc(pretty(x))}</option>`).join('')}</select>`; }
function checked(id, txt, v) { return `<label class="check"><input id="${id}" type="checkbox" ${v ? 'checked' : ''}>${esc(txt)}</label>`; }
const val = id => $('#' + id).value, num = id => Number(val(id)), yes = id => $('#' + id).checked, lines = id => val(id).split('\n').map(x => x.trim()).filter(Boolean);
function pageHelp(p) { const h = PAGE_HELP[p]; return h ? `<div class="pagehelp"><div><b>What this page is for</b>${esc(h[0])}</div><div><b>How to read it</b>${esc(h[1])}</div><div><b>Next step</b>${esc(h[2])}</div></div>` : ''; }
function title(k, t, d) { return `<div class="kicker">${esc(k)}</div><h1>${esc(t)}</h1><p class="lead">${esc(d)}</p>${pageHelp(page)}`; }
function guide(t, d) { return `<div class="guide"><strong>${esc(t)}</strong>${esc(d)}</div>`; }
function card(t, b) { return `<section class="card"><h2>${esc(t)}</h2>${b}</section>`; }
function metrics(o) { return `<div class="metrics">${Object.entries(o).map(([k, v]) => `<div class="metric"><span>${esc(k)}</span><b>${esc(v ?? '—')}</b></div>`).join('')}</div>`; }
function table(headers, rows, empty = 'No records yet.') { return `<div class="table-wrap"><table><thead><tr>${headers.map(x => `<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr>${r.map(x => `<td>${x}</td>`).join('')}</tr>`).join('') || `<tr><td colspan="${headers.length}" class="empty">${esc(empty)}</td></tr>`}</tbody></table></div>`; }
function tag(status) { const s = String(status); const cls = ['met', 'done', 'closed', 'submitted', 'viewable', 'public', 'eligible'].includes(s) ? 'ok' : ['pending', 'open', 'unscreened', 'unknown', 'uncertain', 'not checked', 'provisional'].includes(s) ? 'wait' : 'bad'; return `<span class="tag ${cls}">${esc(pretty(s))}</span>`; }
function counterTable(title, obj, label = 'Value') { const rows = Object.entries(obj || {}).sort((a, b) => b[1] - a[1]).map(([k, v]) => [esc(pretty(k)), esc(v)]); return `<h3>${esc(title)}</h3>` + table([label, 'Count'], rows, 'Nothing counted yet.'); }

// --- session and navigation ---------------------------------------------------------
function navRender() {
  const groups = role === 'admin' ? NAV : [['BLIND CODING', ['My assignments', 'Help']]];
  $('#nav').innerHTML = `<div class="nav">${groups.map(([k, ps]) => `<small>${k}</small>${ps.map(p => `<button class="${p === page ? 'active' : ''}" data-page="${p}">${p}</button>`).join('')}`).join('')}</div>`;
  $('#identity').textContent = role || 'Not signed in'; $('#crumb').textContent = page;
}
async function login() {
  try { role = (await api('/session')).role; page = role === 'admin' ? 'Overview' : 'My assignments'; await render(); }
  catch (e) {
    role = ''; $('#nav').innerHTML = '';
    root.innerHTML = `<div class="kicker">Access</div><h1>Sign in</h1><p class="lead">Enter the administrator token printed in the launcher window, or the coder token the administrator gave you.</p>` +
      card('Access token', field('Token', inp('loginToken', '', 'password')) + `<div class="actions">${btn('Sign in', 'login')}</div>`);
    notice('No active session.');
  }
}
function leaveOk() {
  if (!dirty) return true;
  if (!confirm('This video has unsaved changes. They are kept as a draft on this device. Leave anyway?')) return false;
  clearTimeout(draftTimer); saveDraftLocal(); dirty = false; return true;
}
window.addEventListener('beforeunload', e => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });

const PAGES = {};
async function render() {
  const thisView = ++viewId; clearInterval(queueTimer); navRender(); root.innerHTML = '<p class="muted">Loading…</p>';
  try {
    if (role === 'admin') cfg = await api('/config');
    const html = await (PAGES[page] || PAGES['Help'])();
    if (thisView !== viewId) return;
    root.innerHTML = html;
    if (page === 'Video library') drawLibrary();
    if (page === 'Jobs') { await updateJobs(); queueTimer = setInterval(updateJobs, 2000); }
  } catch (e) { if (thisView === viewId) { root.innerHTML = card('Unable to load', esc(e.message)); notice(e.message, true); } }
}

// --- pages ---------------------------------------------------------------------------
PAGES['Overview'] = async () => {
  lib = await api('/library'); const conn = await api('/connections'); const rounds = await api('/rounds'); const r = await api('/report');
  const screened = lib.filter(x => x.screening !== 'unscreened').length, eligible = lib.filter(x => x.screening === 'eligible').length;
  const closed = rounds.rounds.filter(x => x.closed).length, open = rounds.rounds.find(x => !x.closed);
  const steps = [
    ['Research setup', cfg.permissions.collection, 'Record collection permission and check the study settings.', cfg.permissions.collection ? 'Collection permission recorded.' : ''],
    ['API connections', conn.youtube, 'Paste and test your YouTube Data API key (keys are kept in memory until restart).', conn.youtube ? 'YouTube key loaded.' : ''],
    ['Data discovery', lib.length > 0, 'Import fact-check links and expand seed channels.', `${lib.length} uploads discovered.`],
    ['Video library', screened > 0, 'Open videos and record screening decisions.', `${screened} screened, ${eligible} eligible.`],
    ['Coding & reliability', closed > 0, open ? `Round "${open.name}" is open: ${open.submitted} of ${open.assigned} assignments submitted. Close it when complete.` : 'Create a coding round once enough videos are screened eligible.', closed ? `${closed} closed round(s).` : ''],
    ['Analysis & reports', !r.blocked && r.decision === 'MET', r.blocked ? 'Record analysis permission to compute the report.' : 'Work through the feasibility checklist.', r.blocked ? '' : `Decision: ${r.decision}.`]];
  const next = steps.find(s => !s[1]);
  return title('01 / Start', 'Research overview', `${cfg.title} · ${cfg.study_period.start} to ${cfg.study_period.end}`) +
    metrics({'Discovered uploads': lib.length, 'Screened': screened, 'Screened eligible': eligible, 'Eligible with evidence': r.blocked ? '—' : r.eligible_unique, 'Available (recent check)': r.blocked ? '—' : r.eligible_available}) +
    guide('Next action', next ? `${next[0]}: ${next[2]}` : 'All steps are complete. Export the reproducibility package from Data compliance.') +
    card('Study workflow', steps.map(([p, done, todo, status], i) => `<div class="step"><span class="num">${i + 1}</span><div><b>${esc(p)}</b> ${tag(done ? 'done' : 'pending')}<br><small>${esc(done ? status : todo)}</small></div><button class="secondary" data-page="${esc(p)}">Open</button></div>`).join(''));
};

PAGES['Research setup'] = async () => {
  const p = cfg.study_period, t = cfg.thresholds, s = cfg.search, pr = cfg.prescreen;
  const perms = {ethics: 'Institutional ethics determination recorded', collection: 'Collection and storage authorised for this study', analysis: 'Cross-channel analysis and derived statistics authorised', gemini: 'Third-party video processing (Gemini) authorised', export: 'Aggregate and coded-dataset export authorised', id_export: 'Export of real YouTube video and channel IDs authorised (otherwise exports use pseudonymous keys)'};
  return title('01 / Setup', 'Research configuration', 'Defaults come from the proposal. Change a value only when the protocol changes, and note why in the activity log.') +
    guide('Before collecting', 'Record a permission only once it has actually been granted. A checked box is your record, not legal approval. Change the codebook version whenever coding rules change.') +
    card('1. Study scope', field('Study title', inp('title', cfg.title)) + `<div class="grid">${field('Start date', inp('start', p.start, 'date'))}${field('End date (inclusive)', inp('end', p.end, 'date'))}</div>` +
      field('Eligibility criteria and study notes', ta('notes', cfg.study_notes)) + field('Codebook version', inp('version', cfg.version), 'Coding rounds record this version. Bump it (for example 1.1 to 1.2) after a codebook revision.')) +
    card('2. Search and screening', field('Search queries (one per line)', ta('queries', s.queries.join('\n'))) +
      `<div class="grid">${field('Pages per query, window and sort', inp('pages', s.max_pages_per_query, 'number'))}${field('Region preference', inp('region', s.region_code))}${field('Language preference', inp('language', s.relevance_language))}${field('Sort modes', sel('orders', ['relevance and date', 'relevance', 'date'], s.orders.length > 1 ? 'relevance and date' : s.orders[0]))}</div>` +
      field('Election terms (one per line)', ta('election', pr.election_terms.join('\n'))) + field('AI terms (one per line)', ta('aiterms', pr.ai_terms.join('\n'))) + '<small>All durations are kept. These terms only set review priority.</small>') +
    card('3. Feasibility thresholds (proposal 7.9)', `<div class="grid">${field('Eligible unique videos', inp('minvideos', t.videos, 'number'))}${field('Channels', inp('minchannels', t.channels, 'number'))}${field('Verified at Level 1 or 2 (%)', inp('minverified', t.verified, 'number'))}${field('Availability check must be within (days)', inp('availdays', t.availability_max_age_days, 'number'), 'Only videos whose latest YouTube check is this recent count as available.')}</div>` +
      field('Literature assessment', sel('literature', ['pending', 'clear', 'overlap'], cfg.literature)) + field('Search method, references and conclusion', ta('litnote', cfg.literature_note))) +
    card('4. Reliability rules for the next coding round', `<p class="muted">Set these before a round starts. They are frozen into the round when you create it, so the assessment is pre-registered.</p><div class="grid">${field('Minimum alpha', `<input type="number" id="minalpha" step="0.01" value="${esc(t.alpha)}">`)}${field('Double-coded videos needed', inp('reln', t.reliability_n, 'number'))}${field('Minimum usable pairs per critical variable', inp('minpairs', t.min_pairs, 'number'), 'A usable pair is a unit where at least two coders entered a category (not missing, not not applicable).')}${field('Minimum completeness (%)', inp('mincomp', Math.round(t.min_completeness * 100), 'number'), 'Share of units where every coder entered something. Unmatched personas count as incomplete.')}</div><small>Critical variables: perceived gender, perceived age group and endorsed party. Alpha keeps "unknown" and "uncertain" as categories.</small>`) +
    card('5. Permissions and data handling', Object.entries(perms).map(([k, txt]) => checked('perm_' + k, txt, cfg.permissions[k])).join('') + field('Metadata lifetime in days (maximum 30)', inp('retention', cfg.storage.api_data_max_age_days, 'number'))) +
    `<div class="actions">${btn('Save configuration', 'save-config')}${btn('Continue to API connections', 'goto-api', 'secondary')}</div>`;
};

PAGES['API connections'] = async () => {
  const a = await api('/connections');
  return title('02 / Connect', 'API connections', 'Keys stay in this program\'s memory only. Re-enter them after a restart, or set them as environment variables.') +
    guide('How to get keys', 'YouTube: create a Google Cloud project, enable "YouTube Data API v3", and create an API key. Gemini: create a key in Google AI Studio.') +
    `<div class="grid">${card('YouTube Data API', `<p>${tag(a.youtube ? 'done' : 'pending')} ${a.youtube ? 'Key loaded' : 'Not configured'}</p><a href="https://console.cloud.google.com/" target="_blank" rel="noreferrer">Open Google Cloud Console ↗</a>${field('API key', inp('youtubeKey', '', 'password'))}<div class="actions">${btn('Save key', 'save-youtube')}${btn('Test connection', 'test-youtube', 'secondary')}</div>`)}` +
    `${card('Gemini API (optional)', `<p>${tag(a.gemini ? 'done' : 'pending')} ${a.gemini ? 'Key loaded' : 'Not configured'}</p><a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">Open Google AI Studio ↗</a>${field('API key', inp('geminiKey', '', 'password'))}<div class="actions">${btn('Save key', 'save-gemini')}${btn('List available models', 'test-gemini', 'secondary')}</div><div id="models"></div>${field('Model ID', inp('model', cfg.gemini.model), 'Check on the Gemini documentation that the model accepts YouTube links.')}${field('Delay between requests (seconds)', inp('delay', cfg.gemini.seconds_between_calls, 'number'))}${field('Longest video in automatic batches (seconds)', inp('maxdur', cfg.gemini.max_duration_seconds ?? 180, 'number'))}${btn('Save model settings', 'save-model')}`)}</div>` +
    card('Local quota guard', `<p class="muted">Counts this program's own requests per YouTube quota day (midnight US Pacific). It cannot see other programs using the same key.</p><div class="grid">${field('Daily search requests', inp('searchlimit', cfg.search_limit, 'number'))}${field('Daily other requests', inp('generallimit', cfg.general_limit, 'number'))}</div>${btn('Save limits', 'save-quota')}<h3>Requests so far</h3>${table(['Endpoint', 'Requests'], a.requests.map(r => [esc(r.endpoint), esc(r.count)]))}`);
};

PAGES['Data discovery'] = async () => title('03 / Collect', 'Data discovery', 'Start with fact-check links and known channels, then use logged keyword searches.') +
  card('Import video leads', field('Source', sel('source', ['manual', 'fact_check', 'dismislab'], 'manual')) + field('Source URL (optional)', inp('sourceurl')) + field('Input format', sel('importformat', ['lines', 'csv'], 'lines')) +
    field('One URL or ID per line, or CSV with video_id or url, source_url, note', ta('importtext')) + `<div class="actions">${btn('Import leads', 'import')}${btn('Retrieve missing metadata', 'hydrate', 'secondary')}</div><small>After importing, run "Retrieve missing metadata" so each upload gets its study-period status.</small>`) +
  card('Seed-channel expansion', field('Channel handles, one per line', ta('handles', cfg.seeds.handles.join('\n'))) + field('Channel IDs, one per line', ta('channels', cfg.seeds.channel_ids.join('\n'))) + field('Seed video URLs or IDs, one per line', ta('seeds', cfg.seeds.videos.join('\n'))) +
    `<div class="actions">${btn('Save seeds', 'save-seeds')}${btn('Expand saved channels', 'expand', 'secondary')}</div><small>Expansion retrieves every upload of each channel inside the study period and resumes from checkpoints.</small>`) +
  card('Systematic keyword search', `<p>${cfg.search.queries.length} queries × ${cfg.search.orders.length} sort modes × monthly windows × up to ${cfg.search.max_pages_per_query} pages. Search covers only part of YouTube even when every window finishes.</p>${field('Maximum search pages this run', inp('searchpages', 20, 'number'), 'YouTube allows about 100 search requests a day by default.')}<div class="actions">${btn('Run or continue search', 'search')}${btn('Edit query bank', 'goto-setup', 'secondary')}</div>`);

PAGES['Video library'] = async () => {
  lib = await api('/library'); libShown = 100;
  return title('04 / Inspect', 'Video library', 'Every discovered upload, including unavailable and unclassified leads.') +
    card('Filter', `<div class="grid">${field('Search title, channel or ID', inp('filter'))}${field('Show', sel('statusfilter', ['all', 'unscreened', 'eligible', 'excluded', 'uncertain', 'high', 'medium', 'low', 'unknown', 'in period', 'out of period', 'period unknown', 'public', 'unavailable', 'pending', 'stale'], 'all'))}</div><div class="actions">${btn('Random low-priority review', 'random-low', 'secondary')}${btn('Retrieve missing metadata', 'hydrate', 'secondary')}</div><div id="librarytable"></div>`);
};
function periodLabel(x) { return x.period_flag === 1 ? 'in' : x.period_flag === 0 ? 'out' : 'unknown'; }
function libraryRows() {
  const q = (val('filter') || '').toLowerCase(), s = val('statusfilter');
  return lib.filter(x => [x.video_id, x.title, x.channel_id, x.channel_title].join(' ').toLowerCase().includes(q) &&
    (s === 'all' || x.priority === s || x.retrieval === s || x.screening === s || (s === 'in period' && x.period_flag === 1) || (s === 'out of period' && x.period_flag === 0) || (s === 'period unknown' && x.period_flag == null)));
}
function drawLibrary() {
  const rows = libraryRows(); navIds = rows.map(x => x.video_id);
  const shown = rows.slice(0, libShown);
  $('#librarytable').innerHTML = `<p class="muted">Showing ${shown.length} of ${rows.length} matching uploads (${lib.length} in total).</p>` +
    table(['Video', 'Channel', 'Priority', 'Period', 'YouTube check', 'Playback check', 'Screening', ''], shown.map(x => [
      esc(x.title || x.video_id) + `<br><small>${esc(x.published_at ? x.published_at.slice(0, 10) : 'date not retrieved')} · ${esc(x.duration_seconds ?? '?')}s</small>`,
      esc(x.channel_title || x.channel_id || 'unknown'), esc(x.priority), esc(periodLabel(x)),
      `${tag(x.api_status || 'not checked')}<br><small>${fmtDate(x.api_checked)}</small>`,
      `${tag(x.playback_status || 'not checked')}<br><small>${fmtDate(x.playback_checked)}</small>`,
      tag(x.screening) + (x.screening_reason ? `<br><small>${esc(pretty(x.screening_reason))}</small>` : ''),
      `<button class="secondary" data-video="${esc(x.video_id)}">Open</button>${x.channel_id ? ` <button class="quiet" data-seed="${esc(x.channel_id)}" title="Add this channel to the seed list">+ seed</button>` : ''}`])) +
    (rows.length > shown.length ? `<div class="actions">${btn(`Load ${Math.min(100, rows.length - shown.length)} more`, 'load-more', 'secondary')}<small>${rows.length - shown.length} not shown yet.</small></div>` : '');
}

PAGES['AI screening'] = async () => {
  lib = await api('/library');
  return title('05 / Optional', 'AI-assisted screening', 'Draft transcripts and observations from public video links. Nothing is downloaded.') +
    guide('Model output is not evidence of origin', 'Check transcripts, timestamps and persona boundaries yourself. Independent coders never see model output. Try ten varied clips first.') +
    card('Screening batch', `<p>Current model: <b>${esc(cfg.gemini.model || 'not selected')}</b></p><p>${lib.filter(x => x.active).length} public uploads inside the study period. Videos already screened with the same model and prompt are skipped. Automatic batches skip uploads longer than ${esc(cfg.gemini.max_duration_seconds ?? 180)} seconds; list IDs to screen them anyway.</p>${field('Maximum videos', inp('batch', 10, 'number'))}${field('Optional video IDs, one per line', ta('screenids'))}<div class="actions">${btn('Queue screening', 'gemini')}${btn('API settings', 'goto-api', 'secondary')}</div>`);
};

PAGES['Jobs'] = async () => title('Operations', 'Job monitor', 'Collection and model jobs run while this program stays open.') + card('Recent jobs', '<div id="jobtable"></div>');
async function updateJobs() {
  try {
    const j = await api('/jobs'); if (!$('#jobtable')) return;
    $('#jobtable').innerHTML = table(['Job', 'State', 'Progress or error', 'Controls'], j.map(x => [esc('#' + x.id + ' ' + x.kind), tag(x.state), line(x.progress) + (x.error ? `<p class="error">${esc(x.error)}</p>` : ''),
      `${['running', 'queued'].includes(x.state) ? `<button class="secondary" data-job="${x.id}:paused">Pause</button>` : ''}${['paused', 'failed'].includes(x.state) ? `<button data-job="${x.id}:queued">Resume / retry</button>` : ''}${['running', 'queued', 'paused', 'failed'].includes(x.state) ? ` <button class="quiet" data-job="${x.id}:cancelled">Cancel</button>` : ''}`]), 'No jobs yet. Start one from Data discovery, AI screening or Data compliance.');
  } catch (e) { notice(e.message, true); }
}

PAGES['Coding & reliability'] = async () => {
  const coders = await api('/coders'), info = await api('/rounds'), assign = await api('/assignments');
  const open = info.rounds.find(r => !r.closed), rules = info.rules_next_round;
  const openAssign = open ? assign.filter(a => a.round_id === open.id) : [];
  navIds = [...new Set(openAssign.map(a => a.video_id))];
  return title('06 / Verify', 'Independent coding rounds', 'Two or more coders code the same random sample without seeing each other\'s work or AI drafts.') +
    guide('Keep coders independent', 'Give each coder only their own token. Each coder uses a separate browser profile. Persona IDs must follow order of appearance (1, 2, 3) so they can be matched.') +
    card('Rules that the next round will freeze', table(['Rule', 'Value'], [['Codebook version', esc(info.codebook_version)], ['Minimum alpha (unknown kept as a category)', esc(rules.alpha)], ['Double-coded videos needed', esc(rules.reliability_n)], ['Minimum usable pairs per critical variable', esc(rules.min_pairs)], ['Minimum completeness', esc(Math.round(rules.min_completeness * 100) + '%')], ['Critical variables', esc(rules.critical.map(pretty).join(', '))]]) + `<div class="actions">${btn('Change rules in Research setup', 'goto-setup', 'secondary')}</div>`) +
    card('1. Create coder tokens', field('Coder short name', inp('codername'), 'Letters, digits and hyphens. The token is shown once.') + btn('Create access token', 'create-coder') + '<div id="newtoken"></div>' + `<p class="muted">Existing coders: ${coders.map(x => esc(x.name)).join(', ') || 'none'}</p>`) +
    card('2. Start a round', open ? `<p>${tag('open')} Round "${esc(open.name)}" is open. Close it before starting another.</p>` :
      `<p>${info.pool} canonical videos are screened eligible, inside the study period and viewable at the last check. The sample is drawn from these.</p>` + field('Round name', inp('roundname', `Round ${info.rounds.length + 1}`)) +
      (coders.map(x => checked('coder_' + x.name, x.name, false)).join('') || '<p class="muted">Create coder tokens first.</p>') +
      `<div class="grid">${field('Sample size', inp('sample', rules.reliability_n, 'number'))}${field('Random seed', inp('randomseed', 42, 'number'), 'Recorded in the round so the sample can be reproduced.')}</div>${btn('Start round', 'create-round')}`) +
    card('3. Rounds', table(['Round', 'Codebook', 'Started', 'Status', 'Submitted', ''], info.rounds.slice().reverse().map(r => [esc(`#${r.id} ${r.name}`), esc(r.codebook_version), fmtDate(r.created), tag(r.closed ? 'closed' : 'open') + (r.closed ? `<br><small>${fmtDate(r.closed)}</small>` : ''), esc(`${r.submitted} of ${r.assigned}`),
      r.closed ? `<button class="secondary" data-page="Analysis & reports">View result</button>` : `<button data-close="${r.id}" data-pending="${r.assigned - r.submitted}">Close and assess</button>`]), 'No rounds yet.') +
      '<small>Closing runs the reliability assessment with the frozen rules and stores the result. Coders cannot change a closed round. Adjudicate a sampled video only after its round is closed.</small>') +
    (open ? card(`Assignments in "${open.name}"`, table(['Video', 'Coder', 'Status'], openAssign.map(x => [`<button class="secondary" data-video="${esc(x.video_id)}">${esc(x.video_id)}</button>`, esc(x.coder), tag(x.done ? 'submitted' : 'pending')]))) : '');
};

PAGES['My assignments'] = async () => {
  const a = await api('/assignments'); const open = a.filter(x => !x.closed);
  navIds = open.map(x => x.video_id);
  const todo = open.filter(x => !x.done).length;
  return title('Independent coding', 'My assignments', 'Only your own answers are visible to you. Use the codebook and do not consult the other coder.') +
    guide(todo ? `${todo} video(s) still to code` : (open.length ? 'All assigned videos are submitted' : 'No open assignments'), todo ? 'Open the first pending video. Your work is saved as a draft on this device until you press Submit.' : 'You can revise a submission until the administrator closes the round.') +
    card('Open round', table(['Video', 'Round', 'Status'], open.map(x => [`<button class="secondary" data-video="${esc(x.video_id)}">${esc(x.video_id)}</button>`, esc(x.round_name), tag(x.done ? 'submitted' : 'pending')]), 'Nothing assigned to you in an open round.')) +
    (a.length > open.length ? card('Closed rounds (read only)', table(['Video', 'Round', 'Status'], a.filter(x => x.closed).map(x => [esc(x.video_id), esc(x.round_name), tag(x.done ? 'submitted' : 'not submitted')]))) : '');
};

function reliabilityBlock(res, heading) {
  if (!res) return '';
  const crit = Object.entries(res.critical).map(([k, v]) => [esc(pretty(k)), esc(v.usable_pairs), esc(pct(v.completeness)), esc(fix3(v.alpha)), esc(fix3(v.alpha_excluding_uncertain)), tag(v.status)]);
  const all = Object.entries(res.variables).map(([k, v]) => [esc(pretty(k)), esc(v.usable_pairs), esc(pct(v.completeness)), esc(fix3(v.alpha)), esc(fix3(v.alpha_excluding_uncertain))]);
  const um = res.unmatched_personas.map(u => [esc(u.video_id), esc(u.persona_id), esc(u.coded_by.join(', ')), esc(u.missing_for.join(', '))]);
  return card(heading, `<p>${tag(res.provisional ? 'provisional' : (res.gate_met ? 'met' : 'not met'))} Round "${esc(res.name)}", codebook ${esc(res.codebook_version)}. ${esc(res.double_coded)} of ${esc(res.target_double_coded)} needed videos double-coded. ${esc(res.matched_personas)} matched and ${esc(res.unmatched_personas.length)} unmatched personas; coders agreed on the number of personas in ${esc(pct(res.persona_count_agreement))} of videos.</p>` +
    `<p class="muted">Rules: alpha at least ${esc(res.rules.alpha)}, at least ${esc(res.rules.min_pairs)} usable pairs and ${esc(Math.round(res.rules.min_completeness * 100))}% completeness for each critical variable. ${res.provisional ? 'This round is still open, so these figures can change.' : 'Frozen when the round closed.'}</p>` +
    '<h3>Critical variables</h3>' + table(['Variable', 'Usable pairs', 'Completeness', 'Alpha (unknown kept)', 'Alpha (unknown dropped)', 'Status'], crit) +
    (um.length ? '<h3>Unmatched personas</h3><p class="muted">Personas one coder coded and another did not. They count as incomplete. Check whether coders numbered personas by order of appearance.</p>' + table(['Video', 'Persona', 'Coded by', 'Missing for'], um) : '') +
    `<details><summary>All variables</summary>${table(['Variable', 'Usable pairs', 'Completeness', 'Alpha (unknown kept)', 'Alpha (unknown dropped)'], all)}</details>`);
}

PAGES['Analysis & reports'] = async () => {
  const r = await api('/report');
  if (r.blocked) return title('07 / Analyse', 'Feasibility and analysis', 'Analysis is locked.') + guide('Analysis locked', r.note) + btn('Review permissions', 'goto-setup');
  const f = r.flow, cl = r.content_level, ul = r.upload_level;
  const flowRows = [['Uploads identified', f.identified_uploads], ['Grouped as reposts', f.grouped_as_reposts], ['Unique content', f.unique_content], ['Screened', f.screened], ['Excluded at screening', f.screening_excluded], ['Screened eligible', f.screening_eligible], ['Adjudicated', f.adjudicated], ['Excluded at adjudication', f.adjudication_excluded], ['Eligible at adjudication', f.eligible_adjudicated], ['Removed: study period unknown', f.excluded_period_unknown], ['Removed: outside study period', f.excluded_outside_period], ['Removed: no origin evidence yet', f.eligible_without_origin_evidence], ['Included (coded corpus)', f.included], ['Included and available at a recent check', f.included_available_at_recent_check]];
  return title('07 / Analyse', 'Feasibility and analysis', `Decision: ${r.decision}. Availability counts only YouTube checks from the last ${r.availability_window_days} days.`) +
    metrics({'Eligible (coded corpus)': r.eligible_unique, 'Available, recent check': r.eligible_available, 'Channels (available)': r.channels_available, 'Verified L1/L2 (available)': r.verified_available_pct === null ? '—' : r.verified_available_pct + '%', 'Decision': r.decision}) +
    card('Feasibility checklist', table(['Criterion', 'Status', 'Now', 'Target', 'What to do'], r.checklist.map(i => [esc(i.criterion), tag(i.status), esc(i.current), esc(i.target), esc(i.action)])) + '<small>The decision is MET only when every row is met. Pending means the information does not exist yet.</small>') +
    card('Flow of records (for the flow diagram)', table(['Stage', 'Count'], flowRows.map(([k, v]) => [esc(k), esc(v)])) + `<div class="grid"><div>${counterTable('Exclusion reasons at screening', f.screening_excluded_by_reason, 'Reason')}</div><div>${counterTable('Exclusion reasons at adjudication', f.adjudication_excluded_by_reason, 'Reason')}</div></div>` + counterTable('Discovery sources (distinct uploads)', f.identified_by_source, 'Source') + `<small>${esc(f.adjudications_on_reposts_ignored)} adjudications recorded on reposts were ignored; adjudicate the canonical upload instead.</small>`) +
    card('Availability and disclosure (RQ4)', `<p class="muted">Content level counts each unique video once. Upload level counts every upload of included content, because a repost can be removed or labelled separately. Label prevalence uses only Level 1 and 3 videos, whose inclusion did not depend on a label. YouTube checks range from ${fmtDate(r.availability_checks.oldest)} to ${fmtDate(r.availability_checks.newest)}.</p>` +
      `<div class="grid"><div>${counterTable('Content: viewable at last check', cl.availability)}${counterTable('Content: labels (Level 1 and 3)', cl.labels_level_1_3)}</div><div>${counterTable(`Uploads (${ul.uploads}): YouTube status`, ul.api_status)}${counterTable('Uploads: playback checks', ul.playback)}${counterTable('Uploads: creator disclosure', ul.creator_label)}${counterTable('Uploads: YouTube label', ul.platform_label)}</div></div>`) +
    reliabilityBlock(r.reliability.gate_round, 'Reliability: latest closed round (used for the decision)') +
    reliabilityBlock(r.reliability.provisional_round, 'Reliability: open round (provisional)') +
    (!r.reliability.gate_round && !r.reliability.provisional_round ? card('Reliability', '<p>No coding round yet. Start one on the Coding page.</p>') : '') +
    card('Identity and messages (RQ1, RQ2)', `<div class="grid"><div>${counterTable('Party favoured (videos)', cl.party_favoured, 'Party')}${counterTable('Messages (personas)', cl.message_counts, 'Message')}</div><div>${counterTable('Identity markers (personas)', cl.distributions, 'Code')}</div></div>`) +
    card('Authenticity cues (RQ3)', Object.entries(r.rq3.cues).map(([cue, counts]) => counterTable(pretty(cue), counts)).join('') + `<details><summary>Cues by party favoured</summary><pre>${esc(JSON.stringify(r.rq3.by_party, null, 2))}</pre></details>`) +
    card('Concentration and evidence', table(['Measure', 'Value'], [['Evidence levels (content)', esc(JSON.stringify(cl.evidence_levels))], ['Distinct channels', esc(r.channel_concentration.distinct_channels)], ['Largest channel contributes', esc(r.channel_concentration.largest_channel_count)], ['Corpus without the largest channel', esc(r.channel_concentration.leave_largest_channel_out_n)]]) + `<p class="muted">${esc(r.note)}</p>`) +
    card('Aggregate exports', `<p>Counts only, with IDs replaced by keys unless ID export is permitted. The full research exports are on the Data compliance page.</p><div class="actions">${btn('Export JSON', 'export-json')}${btn('Export CSV', 'export-csv')}${btn('Export Markdown', 'export-md')}${btn('Print or save PDF', 'print', 'secondary')}</div>`);
};

PAGES['Data compliance'] = async () => title('Governance', 'Data compliance and exports', 'Refresh API metadata, keep within the retention rule, and export the research record.') +
  guide('Important limitation', 'This is a policy-aware prototype, not a compliance certification. Do not publish restricted records.') +
  card('Permission register', table(['Permission', 'Recorded'], Object.entries(cfg.permissions).map(([k, v]) => [esc(pretty(k)), tag(v ? 'done' : 'pending')])) + btn('Review permissions', 'goto-setup', 'secondary')) +
  card('Metadata retention', `<p>Metadata lifetime: ${esc(cfg.storage.api_data_max_age_days)} days. Titles, descriptions and statistics older than that are removed automatically. Video IDs, the study-period classification, dated checks, screening decisions and codes are research records and are kept.</p><div class="actions">${btn('Refresh all metadata', 'refresh')}${btn('Remove expired metadata', 'purge', 'secondary')}</div>`) +
  card('Research exports', `<p>These files hold your own records only: discovery and search logs, dated observations, codes, evidence levels and reliability results. They contain no YouTube titles, descriptions, statistics or AI output. IDs are ${cfg.permissions.id_export ? '<b>real YouTube IDs</b> (ID export is permitted)' : 'replaced by stable pseudonymous keys'}.</p>` +
    table(['Export', 'Contents'], [['Search log (CSV)', 'Every logged search: query, sort, date window, page, result count, time.'], ['Coded dataset (ZIP)', 'Adjudicated videos and personas, uploads of included content, and independent annotations per round.'], ['Reproducibility package (ZIP)', 'Everything above plus flow counts, codebook, study settings, round rules and results, the report, and an analysis script that re-computes the results and checks them.']].map(r => r.map(esc))) +
    `<div class="actions">${btn('Export search log', 'export-searchlog')}${btn('Export coded dataset', 'export-dataset')}${btn('Export reproducibility package', 'export-package')}</div><small>Needs export permission; the dataset and package also need analysis permission.</small>`);

PAGES['Activity log'] = async () => { const a = await api('/audit'); return title('Provenance', 'Activity log', 'Configuration, imports, rounds and exports recorded on this computer.') + card('Recent actions', table(['Date', 'Action', 'Detail'], a.map(x => [fmtDate(x.created), esc(x.action), `<details><summary>View</summary><pre>${esc(x.detail)}</pre></details>`]))); };

PAGES['Help'] = async () => {
  const b = book || await api('/codebook'); book = b;
  return title('Reference', 'Help and coding rules', 'Plain-language definitions for coders and administrators.') +
    card('Coding rules', '<ol><li>Watch the whole video at least once before coding.</li><li>Add one persona for each person who speaks or is interviewed, numbered by order of appearance: 1, 2, 3.</li><li>Code what a viewer would perceive. Visible markers and what the person says are coded separately.</li><li>Never infer religion from a name.</li><li>A party name or symbol shown without support is not an endorsement.</li><li>Leave nothing as "missing" when you submit.</li></ol>') +
    card('Missing, unknown, uncertain, not applicable', table(['Value', 'Meaning'], Object.entries(b.missing_values).map(([k, v]) => [esc(pretty(k)), esc(v)]))) +
    card('Eligibility and exclusion reasons', '<p>A video is <b>eligible</b> when at least one AI-generated person, presented as an ordinary member of the public, expresses a political view about the 2026 election, and the upload falls inside the study period.</p>' + table(['Exclusion reason'], b.exclusion_reasons.map(x => [esc(pretty(x))]))) +
    card('Verification levels', table(['Level', 'Basis', 'Use'], [['1', 'A fact-checking organisation examined this clip and rated the speaking persona(s) AI-generated.', 'Main corpus'], ['2', 'YouTube\'s "altered or synthetic" label or an explicit creator disclosure that covers every speaking persona.', 'Main corpus'], ['3', 'Two trained coders independently judged the persona(s) AI-generated using the artifact checklist.', 'Reported separately'], ['0', 'No qualifying evidence yet.', 'Not in the corpus']].map(r => r.map(esc)))) +
    card('Reliability terms', table(['Term', 'Meaning'], [['Usable pair', 'A unit where at least two coders entered a category (not missing, not not applicable).'], ['Completeness', 'Share of units where every coder entered something. Unmatched personas count as incomplete.'], ['Unmatched persona', 'A persona number one coder used and another did not.'], ['Alpha (unknown kept)', 'Krippendorff\'s alpha with unknown and uncertain as real categories. Used for decisions.'], ['Alpha (unknown dropped)', 'Shown for comparison; it can overstate agreement.'], ['Closed round', 'A round whose result is frozen. Coders cannot change it.']].map(r => r.map(esc)))) +
    card('Field definitions', table(['Field', 'Meaning'], Object.entries(b.help).map(([k, v]) => [esc(pretty(k)), esc(v)]))) +
    card('Troubleshooting', '<p>API key rejected: check that the API is enabled and the key is not restricted to another service. Missing videos: keep their IDs; do not assume deletion. Model failure: read the error on the video page, choose a model that accepts YouTube links, and retry a small batch.</p>');
};

// --- video review ------------------------------------------------------------------
function draftKey() { return `sc-draft:${role}:${video.video_id}:${role === 'admin' ? 'final:' + (video.version || '') : 'round:' + (video.round?.id || '')}`; }
function saveDraftLocal() { try { localStorage.setItem(draftKey(), JSON.stringify({saved: new Date().toISOString(), data: collectDraft()})); } catch {} }
function readDraftLocal() { try { return JSON.parse(localStorage.getItem(draftKey()) || 'null'); } catch { return null; } }
function clearDraftLocal() { try { localStorage.removeItem(draftKey()); } catch {} }
function markDirty() { dirty = true; clearTimeout(draftTimer); draftTimer = setTimeout(saveDraftLocal, 500); const s = $('#savestate'); if (s) s.textContent = 'Unsaved changes (draft kept on this device)'; }

function makeCodeFields(prefix, fields, data) {
  return Object.entries(fields).map(([k, choices]) => field(pretty(k), Array.isArray(choices) ? sel(prefix + k, ['missing', ...choices, 'uncertain', 'not_applicable'], data?.[k] || 'missing') : ta(prefix + k, data?.[k] || '', 2), book.help?.[k] || '')).join('');
}
function personaBlock(p, i) {
  return `<div class="persona" data-index="${i}"><div class="split"><h3>Speaking persona ${i + 1}</h3><button type="button" class="quiet" data-remove="${i}">Remove</button></div>${field('Persona ID (order of appearance)', inp('pid' + i, p.id))}<div class="grid">${field('Start (seconds)', inp('pstart' + i, p.start ?? '', 'number'))}${field('End (seconds)', inp('pend' + i, p.end ?? '', 'number'))}</div>${makeCodeFields('p' + i + '_', book.persona, p.codes)}</div>`;
}
function collectDraft() {
  if (!$('#eligibility')) return draft;
  const read = (prefix, f) => Object.fromEntries(Object.keys(f).map(k => [k, val(prefix + k)]));
  const d = {eligibility: val('eligibility'), reason: val('reason'), origin_judgment: val('originjudgment'), video: read('v_', book.video),
    personas: [...document.querySelectorAll('.persona')].map(e => { const i = e.dataset.index; return {id: val('pid' + i), start: val('pstart' + i) === '' ? null : num('pstart' + i), end: val('pend' + i) === '' ? null : num('pend' + i), codes: read('p' + i + '_', book.persona)}; })};
  if (d.eligibility === 'excluded' || val('exclreason') !== '') d.exclusion_reason = val('exclreason') || undefined;
  return d;
}
function drawPersonas() { $('#personas').innerHTML = draft.personas.map(personaBlock).join(''); }

function videoNav(id) {
  const i = navIds.indexOf(id), n = navIds.length;
  const nextLabel = role === 'admin' ? 'Next unscreened' : 'Next uncoded';
  return `<div class="videonav">${i >= 0 ? `<span class="muted">${i + 1} of ${n}</span>` : ''}<button class="secondary" data-action="nav-prev" ${i <= 0 ? 'disabled' : ''}>← Previous</button><button class="secondary" data-action="nav-next" ${i < 0 || i >= n - 1 ? 'disabled' : ''}>Next →</button><button data-action="nav-todo">${nextLabel}</button><button class="quiet" data-action="back">Back to list</button></div>`;
}

async function openVideo(id, opts = {}) {
  ++viewId; clearInterval(queueTimer); dirty = false;
  video = await api('/video/' + id); book = await api('/codebook');
  const server = role === 'admin' ? video.final : video.own_annotation;
  const local = readDraftLocal();
  draft = opts.restore && local ? local.data : (server || {eligibility: 'uncertain', reason: '', video: {}, personas: []});
  draft.personas = draft.personas || [];
  page = 'Video review'; navRender();
  const closedRound = role !== 'admin' && video.round?.closed;
  const savedAt = role === 'admin' ? video.final_saved : video.own_submitted;
  const banner = local && !opts.restore ? `<div class="draftbar"><span>A draft from ${fmtDate(local.saved)} is stored on this device${savedAt ? ` (last submitted ${fmtDate(savedAt)})` : ''}.</span>${btn('Restore draft', 'restore-draft')}${btn('Discard draft', 'discard-draft', 'secondary')}</div>` : '';
  const left = role === 'admin' ? adminCards() : guide('Blind coding', 'AI drafts, evidence and the other coder\'s answers are hidden. Code only what you see and hear.');
  root.innerHTML = title('Review', video.title || id, `Video ID ${id} · Codebook ${role === 'admin' ? book.version : video.version}` + (video.round ? ` · ${video.round.name}` : '')) + videoNav(id) + banner +
    `<div class="grid review"><div>${card('Watch the video', `<iframe src="https://www.youtube-nocookie.com/embed/${esc(id)}" title="YouTube video" allow="encrypted-media; picture-in-picture" allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe><a href="https://www.youtube.com/watch?v=${esc(id)}" target="_blank" rel="noreferrer">Open on YouTube ↗</a><p class="muted">If the player shows an error, open the video on YouTube and copy the message into the playback note.</p>`)}${left}</div>` +
    `<div>${card(role === 'admin' ? 'Adjudicated coding' : 'Your independent coding', '<div class="annot">' +
      (role === 'admin' && video.in_open_round ? guide('Adjudication blocked', 'This video is in an open coding round. Close the round first so the independent assessment is not affected.') : '') +
      (closedRound ? guide('Round closed', 'This round is closed. Your answers are final and cannot be changed.') : '') +
      `<details class="legend"><summary>What missing, unknown, uncertain and not applicable mean</summary>${table(['Value', 'Meaning'], Object.entries(book.missing_values).map(([k, v]) => [esc(pretty(k)), esc(v)]))}</details>` +
      field('Eligibility', sel('eligibility', ['uncertain', 'eligible', 'excluded'], draft.eligibility), 'Eligible: an AI-generated ordinary person expresses a political view about the election.') +
      field('Exclusion reason', sel('exclreason', ['', ...book.exclusion_reasons], draft.exclusion_reason || ''), 'Required when excluded.') +
      field('Origin judgment (your impression, not proof)', sel('originjudgment', ['uncertain', 'suspected_synthetic', 'suspected_genuine'], draft.origin_judgment || 'uncertain')) +
      field('Note on eligibility or uncertainty', ta('reason', draft.reason || '', 2)) +
      `<details open><summary>Video-level codes</summary>${makeCodeFields('v_', book.video, draft.video)}</details><h3>Speaking personas</h3><p class="muted">One block per person who speaks or is interviewed, in order of appearance.</p><div id="personas"></div>` +
      `<div class="actions">${btn('Add persona', 'add-persona', 'secondary')}${closedRound ? '' : btn(role === 'admin' ? 'Save adjudicated decision' : 'Submit independent annotation', 'save-annotation')}</div><p id="savestate" class="muted">${savedAt ? 'Last saved ' + fmtDate(savedAt) : 'Not submitted yet.'}</p></div>`)}</div></div>`;
  drawPersonas();
  if (opts.restore) markDirty();
}

function adminCards() {
  const v = video;
  const levels = {0: 'no qualifying evidence yet', 1: 'Level 1 (fact-check)', 2: 'Level 2 (disclosure or label)', 3: 'Level 3 (two coder judgments)'};
  return card('Screening and dated observations',
      `<p class="muted">Study period: <b>${esc(periodLabel(v))}</b>. Latest YouTube check: ${tag(v.api_status || 'not checked')} ${fmtDate(v.api_checked)}. Latest playback check: ${tag(v.playback_status || 'not checked')} ${fmtDate(v.playback_checked)}. API synthetic-media field: ${esc(v.flag)}.</p>` +
      field('Screening decision', sel('screening', ['unscreened', 'eligible', 'excluded', 'uncertain'], v.screening), 'Eligible videos form the pool for coding rounds. Only uploads inside the study period can be marked eligible.') +
      field('Exclusion reason', sel('screenreason', ['', ...book.exclusion_reasons], v.screening_reason || '')) + field('Screening note', ta('screeningnote', v.screening_note || '', 2)) +
      field('Playback now', sel('playback', ['unknown', 'viewable', 'unavailable'], 'unknown'), 'Choose viewable or unavailable only when you have just tried to play it. Each check is stored with today\'s date.') +
      field('Message YouTube shows (required if unavailable)', inp('playbackreason', '')) +
      `<div class="grid">${field('Creator AI disclosure', sel('creatorlabel', ['unknown', 'yes', 'no'], v.creator_label))}${field('YouTube AI label', sel('platformlabel', ['unknown', 'yes', 'no'], v.platform_label))}</div>` +
      field('Repost of (canonical video ID)', inp('group', v.group_id || v.video_id), 'Leave as this video\'s own ID unless it repeats another upload.') + field('Why it is a repost', ta('groupnote', v.group_note || '', 2)) +
      btn('Save screening and observations', 'observe') +
      `<details><summary>YouTube check history (${v.api_checks.length})</summary>${table(['Date', 'Status'], v.api_checks.map(x => [fmtDate(x.checked_at), tag(x.status)]))}</details>` +
      `<details><summary>Playback check history (${v.playback_checks.length})</summary>${table(['Date', 'Status', 'Message'], v.playback_checks.map(x => [fmtDate(x.observed_at), tag(x.status), esc(x.reason)]))}</details>`) +
    card('Origin evidence', `<p>Current verification: <b>${esc(levels[v.level])}</b></p>` + field('Evidence type', sel('evkind', ['fact_check', 'creator_disclosure', 'platform_label', 'visual_judgment', 'provenance', 'watermark', 'other'], 'fact_check')) + field('Source URL', inp('evurl')) + field('Observation date', inp('evdate', new Date().toISOString().slice(0, 10), 'date')) +
      field('Which personas the evidence covers', sel('evpersona', ['unclear', 'all', 'some_personas'], 'unclear'), 'Choose "all" only if it covers every speaking persona. Only "all" counts for Level 1 or 2.') + field('Rationale and timestamp', ta('evnote', '', 2)) + btn('Add evidence', 'evidence') +
      `<details><summary>Recorded evidence (${v.evidence.length})</summary>${table(['Type', 'Scope', 'Date', 'Source', 'Note'], v.evidence.map(e => [esc(pretty(e.kind)), esc(e.persona), esc(e.observed), e.source ? `<a href="${esc(e.source)}" target="_blank" rel="noreferrer">link</a>` : '', esc(e.note)]))}</details>` +
      `<details><summary>Discovery provenance (${v.discoveries.length})</summary>${table(['Source', 'Detail', 'Date'], v.discoveries.map(d => [esc(d.source), esc(d.detail), fmtDate(d.discovered_at)]))}</details>`) +
    card('AI drafts and independent annotations', `<p class="muted">For adjudication only. Never show these to coders.</p><details><summary>Model runs (${v.model.length})</summary>${table(['Date', 'Model', 'Result'], v.model.map(m => [fmtDate(m.created), esc(m.model), m.ok ? `<pre>${esc(JSON.stringify(JSON.parse(m.payload), null, 2))}</pre>` : `<span class="error">${esc(m.error)}</span>`]))}</details>` +
      `<details><summary>Independent submissions (${v.annotations.length})</summary>${table(['Round', 'Coder', 'Submitted', 'Answer'], v.annotations.map(a => [esc(a.round_id), esc(a.coder), fmtDate(a.created), `<pre>${esc(JSON.stringify(JSON.parse(a.payload), null, 2))}</pre>`]))}</details>`);
}

async function navigateVideo(direction) {
  if (!leaveOk()) return;
  const i = navIds.indexOf(video.video_id);
  if (direction === 'prev' && i > 0) return openVideo(navIds[i - 1]);
  if (direction === 'next' && i >= 0 && i < navIds.length - 1) return openVideo(navIds[i + 1]);
  if (direction === 'todo') {
    let pending;
    if (role === 'admin') { if (!lib.length) lib = await api('/library'); const unscreened = new Set(lib.filter(x => x.screening === 'unscreened').map(x => x.video_id)); pending = navIds.filter(x => unscreened.has(x) && x !== video.video_id); }
    else { const a = await api('/assignments'); const todo = new Set(a.filter(x => !x.closed && !x.done).map(x => x.video_id)); pending = navIds.filter(x => todo.has(x) && x !== video.video_id); }
    const after = pending.find(x => navIds.indexOf(x) > i) || pending[0];
    if (after) return openVideo(after);
    notice(role === 'admin' ? 'No unscreened videos left in this list.' : 'All your assigned videos are submitted.');
  }
}

// --- actions -------------------------------------------------------------------------
async function saveCfg() { await api('/config', 'POST', cfg); notice('Configuration saved.'); await render(); }
async function queue(kind, limit = 10, ids = []) { if (!confirm(`Start a ${kind} job? It may use API quota.`)) return; await api('/jobs', 'POST', {kind, limit, ids}); notice('Job queued.'); page = 'Jobs'; await render(); }
async function download(fmt, name) {
  const r = await fetch('/api/export/' + fmt, {headers: {Authorization: 'Bearer ' + token}});
  if (!r.ok) { let t = await r.text(); try { t = JSON.parse(t).detail; } catch {} throw Error(t || 'Export blocked; review permissions.'); }
  const u = URL.createObjectURL(await r.blob()), el = document.createElement('a'); el.href = u; el.download = name; el.click(); setTimeout(() => URL.revokeObjectURL(u), 1000);
  notice('Downloaded ' + name + '.');
}
const ACTIONS = {
  'login': async () => { token = val('loginToken').trim(); sessionStorage.setItem('sc-token', token); await login(); },
  'goto-api': async () => { page = 'API connections'; await render(); },
  'goto-setup': async () => { page = 'Research setup'; await render(); },
  'back': async () => { if (!leaveOk()) return; page = role === 'admin' ? 'Video library' : 'My assignments'; await render(); },
  'save-config': async () => {
    Object.assign(cfg, {title: val('title'), version: val('version'), study_notes: val('notes'), literature: val('literature'), literature_note: val('litnote')});
    Object.assign(cfg.study_period, {start: val('start'), end: val('end')});
    Object.assign(cfg.search, {queries: lines('queries'), max_pages_per_query: num('pages'), region_code: val('region'), relevance_language: val('language'), orders: val('orders') === 'relevance and date' ? ['relevance', 'date'] : [val('orders')], video_duration: 'any'});
    cfg.prescreen.election_terms = lines('election'); cfg.prescreen.ai_terms = lines('aiterms');
    cfg.thresholds = {videos: num('minvideos'), channels: num('minchannels'), verified: num('minverified'), alpha: num('minalpha'), reliability_n: num('reln'), min_pairs: num('minpairs'), min_completeness: num('mincomp') / 100, availability_max_age_days: num('availdays')};
    for (const k in cfg.permissions) cfg.permissions[k] = yes('perm_' + k);
    cfg.storage.api_data_max_age_days = num('retention'); await saveCfg();
  },
  'save-youtube': async () => { await api('/connections', 'POST', {youtube: val('youtubeKey')}); $('#youtubeKey').value = ''; notice('YouTube key saved in memory.'); await render(); },
  'save-gemini': async () => { await api('/connections', 'POST', {gemini: val('geminiKey')}); $('#geminiKey').value = ''; notice('Gemini key saved in memory.'); await render(); },
  'test-youtube': async () => { await api('/test-connection', 'POST', {service: 'youtube'}); notice('YouTube responded. Collection can start once collection permission is recorded.'); },
  'test-gemini': async () => { const r = await api('/test-connection', 'POST', {service: 'gemini'}); notice('Gemini responded.'); $('#models').innerHTML = field('Available model names', sel('modellist', r.models, r.models[0])) + btn('Use selected name', 'choose-model', 'secondary'); },
  'choose-model': async () => { $('#model').value = val('modellist').replace(/^models\//, ''); },
  'save-model': async () => { cfg.gemini.model = val('model').trim(); cfg.gemini.seconds_between_calls = Math.max(0, num('delay')); cfg.gemini.max_duration_seconds = num('maxdur'); await saveCfg(); },
  'save-quota': async () => { cfg.search_limit = num('searchlimit'); cfg.general_limit = num('generallimit'); await saveCfg(); },
  'save-seeds': async () => { cfg.seeds = {handles: lines('handles'), channel_ids: lines('channels'), videos: lines('seeds')}; await saveCfg(); },
  'import': async () => { const r = await api('/import', 'POST', {source: val('source'), source_url: val('sourceurl'), format: val('importformat'), text: val('importtext')}); notice(`${r.accepted} leads accepted. Not recognised: ${r.invalid.join(', ') || 'none'}. Next: Retrieve missing metadata.`); },
  'search': async () => queue('search', num('searchpages')),
  'gemini': async () => queue('gemini', num('batch'), lines('screenids')),
  'expand': async () => queue('expand'), 'refresh': async () => queue('refresh'), 'purge': async () => queue('purge'), 'hydrate': async () => queue('hydrate'),
  'load-more': async () => { libShown += 100; drawLibrary(); },
  'random-low': async () => { const pool = lib.filter(x => x.active && x.priority === 'low'); if (!pool.length) throw Error('No current low-priority videos.'); await openVideo(pool[Math.floor(Math.random() * pool.length)].video_id); },
  'observe': async () => {
    const r = await api('/video/' + video.video_id + '/observe', 'POST', {screening: val('screening'), screening_reason: val('screenreason'), screening_note: val('screeningnote'), playback: val('playback'), playback_reason: val('playbackreason'), creator_label: val('creatorlabel'), platform_label: val('platformlabel'), group_id: val('group'), group_note: val('groupnote')});
    const d = collectDraft(); const keepDirty = dirty; await openVideo(video.video_id); if (keepDirty) { draft = d; drawPersonas(); markDirty(); }
    notice('Saved.' + (r.playback_recorded ? ' Playback check recorded with today\'s date.' : ''));
  },
  'evidence': async () => { await api('/video/' + video.video_id + '/evidence', 'POST', {kind: val('evkind'), source: val('evurl'), observed: val('evdate'), persona: val('evpersona'), note: val('evnote')}); const d = collectDraft(); const keep = dirty; await openVideo(video.video_id); if (keep) { draft = d; drawPersonas(); markDirty(); } notice('Evidence saved.'); },
  'add-persona': async () => { draft = collectDraft(); let next = 1; while (draft.personas.some(p => String(p.id) === String(next))) next++; draft.personas.push({id: String(next), start: null, end: null, codes: {}}); drawPersonas(); markDirty(); },
  'save-annotation': async () => {
    draft = collectDraft();
    await api('/video/' + video.video_id + '/annotation', 'POST', {version: role === 'admin' ? book.version : video.version, payload: draft, final: role === 'admin'});
    clearTimeout(draftTimer); clearDraftLocal(); dirty = false; $('#savestate').textContent = 'Saved ' + new Date().toLocaleString() + '.';
    notice(role === 'admin' ? 'Adjudicated decision saved.' : 'Submitted. Use "Next uncoded" for the next video.');
  },
  'restore-draft': async () => openVideo(video.video_id, {restore: true}),
  'discard-draft': async () => { clearTimeout(draftTimer); clearDraftLocal(); await openVideo(video.video_id); notice('Draft discarded.'); },
  'nav-prev': async () => navigateVideo('prev'), 'nav-next': async () => navigateVideo('next'), 'nav-todo': async () => navigateVideo('todo'),
  'create-coder': async () => { const r = await api('/coders', 'POST', {name: val('codername')}); $('#newtoken').innerHTML = `<p>Copy this token now and give it only to ${esc(r.name)}. It will not be shown again.</p><pre>${esc(r.token)}</pre><button data-action="copy-token">Copy token</button>`; $('#newtoken').dataset.token = r.token; notice('Coder created.'); },
  'copy-token': async () => { await navigator.clipboard.writeText($('#newtoken').dataset.token); notice('Token copied.'); },
  'create-round': async () => { const names = [...root.querySelectorAll('input[id^=coder_]:checked')].map(x => x.id.slice(6)); const r = await api('/rounds', 'POST', {name: val('roundname'), coders: names, n: num('sample'), seed: num('randomseed')}); notice(`Round started: ${r.assigned} videos assigned to each coder from a pool of ${r.pool}.`); await render(); },
  'export-json': async () => download('json', 'feasibility.json'), 'export-csv': async () => download('csv', 'feasibility.csv'), 'export-md': async () => download('md', 'feasibility.md'),
  'export-searchlog': async () => download('searchlog', 'search_log.csv'), 'export-dataset': async () => download('dataset', 'coded_dataset.zip'), 'export-package': async () => download('package', 'reproducibility_package.zip'),
  'print': async () => { if (!cfg.permissions.export) throw Error('Record export permission before printing.'); window.print(); },
};

document.addEventListener('click', async e => {
  const b = e.target.closest('button'); if (!b) return;
  try {
    if (b.dataset.page) { if (!leaveOk()) return; page = b.dataset.page; document.body.classList.remove('open'); notice(''); await render(); }
    else if (b.dataset.video) { if (!leaveOk()) return; notice(''); await openVideo(b.dataset.video); }
    else if (b.dataset.seed) { if (!cfg.seeds.channel_ids.includes(b.dataset.seed)) cfg.seeds.channel_ids.push(b.dataset.seed); await api('/config', 'POST', cfg); notice('Channel added to the seed list. Run "Expand saved channels" on Data discovery.'); }
    else if (b.dataset.job) { const [id, state] = b.dataset.job.split(':'); await api('/jobs/' + id, 'POST', {state}); await updateJobs(); }
    else if (b.dataset.close) { const pending = Number(b.dataset.pending); if (!confirm((pending ? `${pending} assignment(s) are not submitted and will count as missing. ` : '') + 'Close this round and freeze its reliability result? This cannot be undone.')) return; const r = await api('/rounds/' + b.dataset.close + '/close', 'POST', {}); notice(`Round closed. Reliability decision: ${r.gate_met ? 'met' : 'not met'}. See Analysis & reports.`); await render(); }
    else if (b.dataset.remove !== undefined) { draft = collectDraft(); draft.personas.splice(Number(b.dataset.remove), 1); drawPersonas(); markDirty(); }
    else if (b.dataset.action && ACTIONS[b.dataset.action]) { b.disabled = true; try { await ACTIONS[b.dataset.action](); } finally { b.disabled = false; } }
  } catch (err) { notice(err.message, true); }
});
document.addEventListener('input', e => { if (e.target.id === 'filter' && $('#librarytable')) { libShown = 100; drawLibrary(); } if (e.target.closest('.annot')) markDirty(); });
document.addEventListener('change', e => { if (e.target.id === 'statusfilter') { libShown = 100; drawLibrary(); } if (e.target.closest('.annot')) markDirty(); });
$('#logout').onclick = () => { if (!leaveOk()) return; sessionStorage.removeItem('sc-token'); token = ''; location.reload(); };
$('#theme').onclick = () => { document.body.classList.toggle('dark'); localStorage.setItem('sc-theme', document.body.classList.contains('dark') ? 'dark' : 'light'); };
if (localStorage.getItem('sc-theme') === 'dark') document.body.classList.add('dark');
$('#menu').onclick = () => document.body.classList.toggle('open');
login();
