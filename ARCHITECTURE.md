# Architecture

`run.py` starts a localhost FastAPI application and opens the browser. `webapp/static/` holds the interface (plain JavaScript, no build step). `webapp/server.py` exposes token-protected routes and a cooperative job worker.

- `webapp/core.py`: schema and migrations, collection jobs (search, channel expansion, metadata), the inventory, dated observations, the codebook and annotation validation.
- `webapp/research.py`: coding rounds, reliability (pure function, re-derivable from exports), and the feasibility report with flow, RQ3, content and upload level, and checklist.
- `webapp/exports.py`: search log, coded dataset and reproducibility package, with pseudonymous keys.
- `webapp/analysis/analysis.py`: the standalone script shipped inside the package.
- `pilot/`: YouTube client, pre-screen and Gemini prompt and validation.

SQLite tables separate API metadata (`videos`, `channels`, `prescreen`, purged after 30 days) from research records (`inventory`, `discovery`, `availability_checks`, `playback_checks`, `evidence`, `rounds`, `round_assignments`, `annotations`, `finals`, `search_log`, `audit`). The database and administrator token are private local state. One research project per data directory.
