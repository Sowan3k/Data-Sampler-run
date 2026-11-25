# Synthetic Citizens Research Control Centre

Version 0.3.1. Local research tool for the feasibility pilot of "Who Gets Synthesised? AI-Generated 'Ordinary Voters' on YouTube in Bangladesh's 2026 Election".

The application collects candidate videos through the official YouTube Data API, supports screening, origin verification, independent double-coding and adjudication, and produces the feasibility decision in section 7.9 of the proposal together with a reproducible research dataset. It runs on one computer, in the browser, with no data leaving that computer except the API requests you start. It contains no example data and generates no findings on its own.

## Quick start

**Windows.** Install Python 3.11, 3.12 or 3.13 from python.org and tick "Add Python to PATH". Extract the ZIP and double-click `START-WINDOWS.bat`. The first run installs dependencies (it reinstalls automatically when `requirements.txt` changes). A browser tab opens. Keep the black window open while you work. The address contains your private administrator token; do not share it.

**macOS or Linux.** Run `bash start.sh` in the extracted folder.

The application listens only on `http://127.0.0.1:8765` (change with `RESEARCH_PORT`). Do not expose it to a network.

## Workflow

Every page explains its purpose, how to read it and the next step. The Overview page shows which steps are done.

1. **Research setup.** Check the study period, search terms and feasibility thresholds. Agree the reliability rules with your supervisor (see RELIABILITY.md). Record each permission only once it has been granted.
2. **API connections.** Paste and test your YouTube Data API key. Gemini is optional. Keys stay in memory until restart, or can be set as `YOUTUBE_API_KEY` and `GEMINI_API_KEY`.
3. **Data discovery.** Import fact-check links, then run "Retrieve missing metadata". Save seed channels and expand them. Run logged keyword searches in small batches. Watch progress on Jobs.
4. **Video library.** Open videos from the top. Record a screening decision on each: eligible, excluded with a reason, or uncertain. Only uploads inside the study period can be marked eligible. Record playback checks with the message YouTube shows when a video is unavailable.
5. **Origin evidence and adjudication.** Add evidence (fact-check, disclosure, label, or visual judgment) and save the adjudicated coding. Level 1 and 2 evidence must cover every speaking persona.
6. **Coding & reliability.** Create two coder tokens and start a round. The sample is drawn from screened-eligible videos with a recorded seed. Coders work blind on their own browser profiles. Close the round when every assignment is submitted; its result is then frozen. Adjudicate sampled videos only after the round closes.
7. **Analysis & reports.** Work through the feasibility checklist. The report shows the flow of records with exclusion reasons, availability and disclosure at content and upload level, reliability per round, and descriptive results for RQ1 to RQ4.
8. **Data compliance.** Refresh metadata before reporting. Export the search log, the coded dataset, or the full reproducibility package.

CODEBOOK.md holds every variable definition for the second coder. The same text appears under each field in the coding form.

## Research rules the software enforces

- **Corpus.** The coded corpus is every adjudicated eligible upload, inside the study period, with origin evidence, counting reposts once. It stays fixed when a video is later removed or its metadata expires. Uploads whose study period was never established are excluded and counted, never assumed in.
- **Observations.** YouTube API status and playback checks are separate dated observations. Within each category the latest observation wins.
- **Availability for the decision.** A video counts as available when its latest YouTube check is public or unlisted and no older than the configured window (default 30 days), and its latest playback check, if any, is viewable.
- **Reliability.** See RELIABILITY.md. Rules are frozen per round. A critical variable needs enough usable pairs, enough completeness and alpha at or above the threshold. Unmatched personas are reported.
- **Content and upload level.** Identity, message and cue statistics count each unique video once. Disclosure and availability are also reported for every upload, because a repost can be labelled or removed separately.

## Data handling

- `data/research.db` and `data/admin.token` are created on first run and are excluded from Git. Keep the folder private.
- YouTube metadata (titles, descriptions, statistics) older than 30 days is removed automatically. Video IDs, the study-period classification, dated checks, screening decisions and codes are research records and are kept.
- Exports contain your own records only, never YouTube metadata or AI output. IDs become stable pseudonymous keys unless the "ID export" permission is recorded. The key mapping (`data/export.salt`) never leaves the computer.
- No video files are downloaded.

## Reproducibility package

Data compliance, "Export reproducibility package", produces a ZIP with the coded data, independent annotations per round, search log, flow counts, codebook, study settings, round rules and stored results, the report, and `analysis/analysis.py`. The script uses only the Python standard library. It re-computes the descriptive tables and every round's reliability from the CSV files and exits with an error if anything differs from the stored results.

## Testing

`python -m pytest -q` runs 68 offline tests. TESTING_CHECKLIST.md lists what was tested in the build environment (including 84 browser checks in headless Chrome at desktop and mobile widths) and the manual checks that still need your Windows laptop, other browsers, your API keys and a second coder. Live YouTube and Gemini integration has not been tested yet.

## Not included

A configurable codebook editor, the genuine vox pop comparison corpus, automatic fact-check ingestion, inferential statistics, keyboard shortcuts, remote coder accounts and automatic duplicate detection. The next milestone is data collection and the feasibility assessment, not new features.

## Changes in 0.3.1

- Out-of-period uploads can no longer enter the corpus after their metadata expires; the study-period classification is now a kept research record.
- API status and playback are separate dated observations; playback checks record YouTube's message.
- A configurable freshness window decides which availability checks count.
- Coding rounds with frozen codebook and rules; closed rounds are immutable; adjudication is blocked during an open round; two rounds stay reproducible.
- Reliability requires usable pairs and completeness per critical variable; unmatched personas are reported.
- New report sections: flow with exclusion reasons, RQ3 cue tables, content versus upload level, actionable checklist.
- Exports: search log, coded dataset, reproducibility package with analysis script.
- Interface: guidance on every page, field definitions, Load more with totals, local drafts with unsaved-change warnings, previous, next and next-uncoded navigation.
- `tzdata` dependency and timezone fallback for Windows; launchers reinstall when requirements change.

## Changes in 0.3.0

Corpus locking, screened-eligible sampling, categorical codebook 1.1, alpha with two missing-data rules, Gemini error detail and duration cap.
