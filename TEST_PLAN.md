# Test plan

## Executed offline

`python -m pytest -q`: 44 tests. `tests/test_fixes.py` covers corpus locking after removal and old playback checks, channel locators after purge, repost-group availability, label prevalence from Level 1 and 3 only, the screened-eligible sample pool, both alpha rules, the categorical codebook, timestamp formats, key redaction, the screening and evidence-scope endpoints, and the Gemini duration cap with error detail. Covers parsing, Bangla matching, timezone boundaries, fake YouTube API, search checkpoints, unavailable ID retention, metadata expiry, interrupted hydration, synthetic flag states, malformed model responses, timestamp bounds, nominal alpha, feasibility exclusion, retry accounting, HTTP authorization, blind coder data isolation and permission gating. `node --check webapp/static/app.js` passed.

## Researcher acceptance tests (not executed live)

- Launch on target OS, inspect each page in normal and mobile-width browser, switch theme, save setup and confirm persistence on restart.
- Connect real API keys; retrieve one known video and inspect synthetic flag alongside dated manual observation. Expand one channel. Pause/restart and resume a limited search; reconcile actual records against API console quotas.
- Run ten diverse videos through the selected model; validate transcription, timestamps and persona boundaries manually. Record failures. Do not use model inference as proof of AI generation.
- Create two independent coder identities and complete shared sample; check that original submissions remain separate and alpha is calculated before adjudication. Independently reproduce statistics in R or Python before use in paper.
- Test data handling against actual permission terms, including retained locator keys, provenance, backups and export restrictions. Obtain ethics determination and platform permission before collection at scale.
