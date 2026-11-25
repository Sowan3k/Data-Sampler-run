# Test plan

## Automated (run with `python -m pytest -q`)

68 tests in four files:

- `tests/test_pipeline.py`: collection client, parsing, Bangla matching, time windows, Gemini output parsing.
- `tests/test_control_centre.py`: checkpoints, hydration, alpha values, access control, permissions.
- `tests/test_fixes.py`: 0.3.0 defects (corpus locking, channel locators, sample pool, codebook, timestamps, Gemini cap). The Gemini job test skips when the SDK is not installed.
- `tests/test_v031.py`: 0.3.1 defects and deliverables: out-of-period after expiry, unknown period, separate dated observations, freshness, usable pairs, completeness, unmatched personas, frozen and immutable rounds, two codebook versions, RQ3 and upload-level reporting, exclusion reasons, pseudonymised exports, search log, reproducibility package round trip and tamper detection, timezone fallback, config and legacy migration, HTTP screening rules, round lifecycle and export permissions.

## Browser (manual run, see `tests/browser/browser_checks.py`)

84 checks in headless Chrome at desktop and mobile widths with fixture data.

## Manual acceptance

TESTING_CHECKLIST.md: Windows, desktop and mobile browsers, live API integration and a research workflow dry run.
