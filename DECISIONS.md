# Decisions

- Local FastAPI plus plain HTML, CSS and JavaScript: no second runtime and simple setup.
- API keys in process memory by default; optional environment variables.
- Retain all in-period uploads for review; terms set priority, not exclusion.
- Save locator and provenance before metadata; explicit recovery job for pending metadata.
- Conservative origin verification: Level 1 and 2 evidence must cover every speaking persona; Level 3 needs two independent judgments.
- Corpus membership is fixed by adjudication, study period and origin evidence. Availability is an outcome (RQ4), never an exclusion. The 30-day rule applies to API metadata, not to the researcher's own observations and codes.
- The study-period classification is stored as a research record when metadata is retrieved. Unknown period means excluded and counted.
- API status and playback are separate dated observation categories; the latest observation wins within each.
- The feasibility decision counts availability only from checks inside a configurable window.
- Reliability runs in coding rounds with frozen codebook and rules. Closed rounds are immutable. Adjudication waits until the round closes.
- Critical variables need usable pairs, completeness and alpha (unknown kept as a category). The looser alpha is shown for comparison only.
- Reliability samples come from screened-eligible canonical videos.
- Exports hold researcher records only and pseudonymise IDs unless ID export is permitted. The reproducibility package ships a standard-library analysis script that checks the stored results.
- Guidance on every page instead of a setup wizard.
- No new features before data collection.
