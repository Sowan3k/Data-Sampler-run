# Architecture

`run.py` starts a localhost FastAPI application and opens the browser. `webapp/static/` contains the responsive interface. `webapp/server.py` exposes token-protected routes and a cooperative job worker. `webapp/core.py` manages persistent jobs, discovery checkpoints, evidence, annotations, reliability and feasibility. `pilot/` retains the original project's API, schema, date parsing and Gemini code with selected fixes. The old CLI and report are retired.

SQLite separates inventory locators, API metadata, discovery provenance, evidence, independent coding revisions, final decisions, assignments, model runs, configuration and audit records. API requests are counted before attempts. Search checkpoints are keyed by query/window/order/filters. Playlist checkpoints are keyed by playlist and study period. The latest manual annotation is distinct from adjudicated coding. The inventory keeps the channel ID as a locator and the admin's screening decision; both survive the metadata purge. Availability comes from the dated availability_checks log. The app stores no downloaded audiovisual files.

The database and administrator token are private local state. There is one research project per data directory. Server-side role checks protect blind coder endpoints. No public hosting or institutional authentication is implemented.
