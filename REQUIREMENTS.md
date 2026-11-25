# Requirements and implementation status

| ID | Requirement | State |
|---|---|---|
| R01 | Browser-based guided setup, API keys and service tests | Implemented; live API pending |
| R02 | Seed/import/search with durable per-page checkpoints | Implemented; live API pending |
| R03 | Preserve unavailable IDs and prioritise rather than hard-exclude long or keyword-poor videos | Implemented |
| R04 | Local background jobs with status, cooperative pause/cancel, retry | Implemented |
| R05 | Inventory, manual group/repost, separate dated API and playback observations, disclosure | Implemented |
| R06 | Gemini structured drafts, local validation and model/config/prompt hashes | Implemented; SDK/service integration unverified |
| R07 | Persona/video annotation, evidence registry and revision history | Implemented with fixed categorical codebook 1.1 |
| R08 | Blind coder access, coding rounds with frozen rules, immutable closed rounds, adjudication after rounds | Implemented local-only |
| R09 | Alpha with usable pairs, completeness and unmatched personas; flow with exclusion reasons; RQ3; content and upload level; checklist | Implemented; scientific validation required |
| R10 | Retention checks, permission-gated exports, coded dataset and reproducibility package | Implemented; policy review remains required |
| R11 | Page guidance, field help, drafts, navigation, Load more, light/dark styles, launcher | Implemented; headless Chrome tested, other browsers pending |
| R12 | Matched comparison corpus, configurable codebook, formal audit sample, inferential models | Deferred |
| R13 | Remote collaboration, automatic content deduplication, bulk annotation import, keyboard shortcuts, setup wizard | Deferred |

Scientific constraints: discovery is not inclusion; AI output is not provenance; current disclosure is not election-time disclosure; no raw downloads; unknown is not false; missing videos are not automatically classified as deleted. Counts are descriptive of a discoverable corpus, not an exhaustive population. All permission flags are self-attestations.
