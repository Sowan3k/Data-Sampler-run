# Decisions

- Local FastAPI plus plain HTML/CSS/JS: no second runtime and simpler setup than the previously proposed Next.js architecture.
- API keys held in process memory by default; optional environment variables for repeat launches.
- Retain all current in-period uploads for review; terms determine priority, not exclusion.
- Save locator and provenance before hydration; explicit recovery job for pending metadata.
- Use conservative origin verification: whole-persona coverage is required for Level 1/2; Level 3 requires independent human judgments.
- Count unique content groups, require current playback and metadata, separate adjudication from blind coding.
- No automatic policy certification. Only permission-gated aggregate exports; no bulk raw data export.
- Fixed initial codebook and descriptive analysis for pilot; advanced modelling and comparison corpus deferred.
