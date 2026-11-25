# Requirements and implementation status

| ID | Requirement | State |
|---|---|---|
| R01 | Browser-based guided setup, API keys and service tests | Implemented; live API pending |
| R02 | Seed/import/search with durable per-page checkpoints | Implemented; live API pending |
| R03 | Preserve unavailable IDs and prioritise rather than hard-exclude long or keyword-poor videos | Implemented |
| R04 | Local background jobs with status, cooperative pause/cancel, retry | Implemented |
| R05 | Inventory, manual group/repost, dated playback and disclosure | Implemented |
| R06 | Gemini structured drafts, local validation and model/config/prompt hashes | Implemented; SDK/service integration unverified |
| R07 | Persona/video annotation, evidence registry and revision history | Implemented with fixed categorical codebook 1.1 |
| R08 | Blind coder access, sample assignment from screened-eligible videos, independent submissions and adjudication | Implemented local-only |
| R09 | Nominal alpha (two missing-data rules), descriptive statistics, availability outcome, feasibility gates | Implemented; scientific validation required |
| R10 | Retention checks and permission-gated aggregate export | Partial; policy review remains required |
| R11 | Help, responsive navigation, light/dark styles, launcher | Implemented; browser test pending |
| R12 | Matched comparison corpus, configurable codebook, formal audit sample, inferential models | Deferred |
| R13 | Remote collaboration, automatic content deduplication, bulk annotation import | Deferred |

Scientific constraints: discovery is not inclusion; AI output is not provenance; current disclosure is not election-time disclosure; no raw downloads; unknown is not false; missing videos are not automatically classified as deleted. Counts are descriptive of a discoverable corpus, not an exhaustive population. All permission flags are self-attestations.
