# Manual testing checklist, version 0.3.1

Status key: **PASSED** means it was run and passed in the build environment (Linux, headless Chrome). **NOT PERFORMED** means it could not be run there and needs you. **SKIPPED** means it was deliberately left out, with the reason given. Fill in the last column as you go.

Build environment: Linux, Python 3.13, Google Chrome (headless, via Playwright), 25 November 2026.

## A. What was run in the build environment

| # | Test | Status | Evidence |
|---|---|---|---|
| A1 | Offline test suite (`python -m pytest -q`) | PASSED | 68 tests, including regression tests for every reproduced defect. |
| A2 | Fresh Linux install with `bash start.sh` from a clean copy | PASSED | Dependencies installed, server answered, tests passed in the new environment. |
| A3 | Timezone lookup without a system timezone database (the Windows situation) | PASSED | `tzdata` resolves America/Los_Angeles with the system path removed; the code also falls back to UTC-8. |
| A4 | Every administrator page at 1366 px and 390 px: loads, shows guidance, no sideways scrolling, no browser errors | PASSED | 50 of the 84 browser checks in `tests/browser/browser_checks.py`. |
| A5 | Library shows totals, first 100 rows, Load more, filter by screening | PASSED | Browser checks. |
| A6 | Screening rules in the browser: excluding needs a reason; Next unscreened | PASSED | Browser checks. |
| A7 | Adjudication blocked while a video is in an open round | PASSED | Browser check and HTTP test. |
| A8 | Coder at 390 px and 1366 px: blind mode, local draft, leave warning, reload warning, draft restore, submit, draft cleared, Next uncoded | PASSED | 24 browser checks. |
| A9 | Search log and reproducibility package download from the browser | PASSED | Browser checks. |
| A10 | Reproducibility package: analysis script re-computes results and detects a tampered file | PASSED | Tests `test_reproducibility_package_runs_and_matches_stored_results`, `test_analysis_script_detects_tampering`. |

To re-run the browser checks: install Playwright and Chrome, then follow the comments at the top of `tests/browser/browser_checks.py`.

## B. Windows installation (NOT PERFORMED, needs your laptop)

| # | Step | Expected | Status | Your result |
|---|---|---|---|---|
| B1 | Install Python 3.12 or 3.13 from python.org with "Add Python to PATH" ticked | `python --version` works in a new Command Prompt | NOT PERFORMED | |
| B2 | Extract the ZIP to a folder without special characters in the path, double-click `START-WINDOWS.bat` | Dependencies install, then a browser tab opens | NOT PERFORMED | |
| B3 | Close the window, run `START-WINDOWS.bat` again | Starts without reinstalling | NOT PERFORMED | |
| B4 | In Command Prompt inside the folder: `.venv\Scripts\python -c "import zoneinfo; print(zoneinfo.ZoneInfo('America/Los_Angeles'))"` | Prints America/Los_Angeles | NOT PERFORMED | |
| B5 | `.venv\Scripts\python -m pytest -q` | 68 passed (the Gemini job test skips if the SDK is missing) | NOT PERFORMED | |
| B6 | If Windows Defender or SmartScreen warns, note the exact message | Note only | NOT PERFORMED | |

## C. Desktop browsers (NOT PERFORMED except headless Chrome)

Do these in Chrome, Edge and Firefox. Use a window about 1366 px wide.

| # | Check | Chrome | Edge | Firefox |
|---|---|---|---|---|
| C1 | Sign in through the link the launcher opens | | | |
| C2 | Visit every page in the menu: each shows "What this page is for", nothing overlaps | PASSED (headless) | | |
| C3 | Toggle Theme: text stays readable in dark mode | | | |
| C4 | Video page: the embedded player plays a public video | | | |
| C5 | Change a code, click Back to list: a warning appears | PASSED (headless) | | |
| C6 | Close the tab with unsaved changes: the browser asks first | | | |
| C7 | Reopen the video: "A draft ... is stored on this device" appears and Restore works | PASSED (headless) | | |
| C8 | Export the reproducibility package and open the ZIP | PASSED (headless) | | |

## D. Mobile browsers (NOT PERFORMED except headless Chrome at 390 px)

The app only runs on the computer where you started it, so a phone can reach it only through that computer's browser. For layout checks, use the desktop browser's device mode, or use a phone on the same computer through a USB debugging session.

| # | Check | Headless Chrome 390 px | Android Chrome | iPhone Safari |
|---|---|---|---|---|
| D1 | Menu button opens and closes the side menu | PASSED | | |
| D2 | No page scrolls sideways | PASSED | | |
| D3 | Coding form fields and buttons can be tapped without zooming | PASSED (visual) | | |
| D4 | Draft restore and Submit work | PASSED | | |

## E. Live integration (NOT PERFORMED, needs your keys)

Do not claim live functionality until these pass.

| # | Step | Expected | Status | Your result |
|---|---|---|---|---|
| E1 | API connections: save the YouTube key, Test connection | "YouTube responded" | NOT PERFORMED | |
| E2 | Import one video that visibly shows YouTube's AI label, run Retrieve missing metadata | Library shows its title, Period "in", YouTube check "public", and the API synthetic-media field | NOT PERFORMED | |
| E3 | Record whether the API synthetic-media field says true, false or absent for that video | Note the value | NOT PERFORMED | |
| E4 | Add one seed channel, run Expand saved channels, watch Jobs | Job completes; the channel's in-period uploads appear | NOT PERFORMED | |
| E5 | Pause the expand job mid-way, then Resume | It continues without repeating finished pages | NOT PERFORMED | |
| E6 | Run a search with 2 pages | Two rows in the search log export | NOT PERFORMED | |
| E7 | Compare request counts on API connections with the Google Cloud quota page | Numbers agree | NOT PERFORMED | |
| E8 | Gemini: save the key, list models, pick one that accepts YouTube links, screen 10 varied clips | Drafts appear on video pages; failures show the service's message | NOT PERFORMED | |
| E9 | Check three Gemini Bangla transcripts against the audio | Note accuracy | NOT PERFORMED | |

## F. Research workflow dry run (NOT PERFORMED, needs you and a second person)

| # | Step | Expected | Status | Your result |
|---|---|---|---|---|
| F1 | Screen 10 videos, marking at least 3 eligible and 2 excluded with reasons | Analysis flow shows the exclusions by reason | NOT PERFORMED | |
| F2 | Create two coder tokens; start a round of 3 videos | Each coder sees 3 assignments | NOT PERFORMED | |
| F3 | Second coder codes on their own browser profile using only CODEBOOK.md and the in-app help | They finish without asking technical questions | NOT PERFORMED | |
| F4 | Close the round | Result frozen; reliability shown with usable pairs, completeness and unmatched personas | NOT PERFORMED | |
| F5 | Adjudicate one sampled video, add Level 1 or 2 evidence | It appears in the coded corpus | NOT PERFORMED | |
| F6 | Export the reproducibility package and run `python analysis/analysis.py` inside it | "all recomputed values match the stored results" | NOT PERFORMED | |

## G. Skipped on purpose

| Item | Reason |
|---|---|
| Keyboard shortcuts | Out of scope for 0.3.1 by agreement. |
| Setup wizard | Replaced by guidance on every page and the Overview workflow, by agreement. |
| Automated cross-browser suite | Manual checks in sections C and D are enough for a single-user local pilot. |
