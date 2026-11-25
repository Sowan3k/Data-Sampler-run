# Decisions

- Local FastAPI plus plain HTML/CSS/JS: no second runtime and simpler setup than the previously proposed Next.js architecture.
- API keys held in process memory by default; optional environment variables for repeat launches.
- Retain all current in-period uploads for review; terms determine priority, not exclusion.
- Save locator and provenance before hydration; explicit recovery job for pending metadata.
- Use conservative origin verification: whole-persona coverage is required for Level 1/2; Level 3 requires independent human judgments.
- Count unique content groups, require current playback and metadata, separate adjudication from blind coding.
- No automatic policy certification. Only permission-gated aggregate exports; no bulk raw data export.
- Fixed initial codebook and descriptive analysis for pilot; advanced modelling and comparison corpus deferred.
- Corpus membership is fixed by adjudication plus origin evidence. Availability is an outcome (RQ4), never an exclusion. The 30-day rule applies to API metadata, not to the researcher's own observations and codes.
- Reliability samples come from screened-eligible videos only, so coder time is spent on in-scope content.
- Variables that are counted or reliability-tested are categorical (codebook 1.1).
- The feasibility gate uses alpha with unknown and uncertain kept as categories; the looser figure is shown for comparison.
- Automatic Gemini batches skip uploads above a configurable length; explicit IDs are always attempted.
