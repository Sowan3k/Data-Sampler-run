# Reliability protocol

This protocol fixes how inter-coder reliability is assessed before any coding starts. The application enforces it.

## Coding rounds

A coding round is one independent double-coding exercise. When the administrator starts a round, the application records:

- the codebook version and a full copy of the codebook,
- the reliability rules below, copied from Research setup,
- the random seed and the size of the sampling pool,
- the sampled videos and the coders assigned to each.

Changing the settings afterwards does not change a round that has already started. The proposal allows one codebook revision, so a study normally has two rounds: round 1 on codebook 1.1, and, if a critical variable fails, round 2 on the revised codebook (for example 1.2). Both rounds stay in the database and in the exports, and each can be reproduced on its own.

Only one round can be open at a time.

## Sampling pool

The sample is drawn at random, with the recorded seed, from canonical uploads (not reposts) that the administrator screened as eligible, that lie inside the study period, and that were viewable at the last check. This keeps coder time on in-scope videos.

## Independence

- Each coder signs in with their own token and sees only their own answers. AI drafts, evidence and the other coder's answers are hidden by the server.
- Coders may revise their answers while the round is open. The assessment uses each coder's latest submission made before the round closed.
- Closing a round freezes its result. The stored result is what the report and exports use, and coders cannot submit to a closed round.
- The administrator cannot save an adjudicated decision for a video while it is in an open round. Adjudication therefore always comes after the independent assessment.

## Definitions

- **Unit**: a double-coded video (for video-level variables) or a persona slot (for persona-level variables). A persona slot exists for every persona number that any coder used for that video.
- **Matched persona**: a persona number used by every coder of the video. Only matched personas enter alpha.
- **Unmatched persona**: a persona number used by some coders and not others. Unmatched personas are listed in the report and count as incomplete.
- **Usable pair**: a unit where at least two coders entered a category, that is, a value other than *missing* or *not applicable*.
- **Completeness**: complete units divided by all units, where a complete unit is one where every coder entered something other than *missing*.
- **Alpha**: Krippendorff's alpha for nominal data. *Unknown* and *uncertain* count as categories. *Missing* and *not applicable* are left out. A second alpha that also drops *unknown* and *uncertain* is shown for comparison only, because it can overstate agreement.

## Decision rule

The reliability condition of the feasibility decision (proposal section 7.9) is met for a round when all of the following hold:

1. At least the required number of videos is double-coded (default 50).
2. For each critical variable (perceived gender, perceived age group, endorsed party):
   - usable pairs are at least the minimum (default 40),
   - completeness is at least the minimum (default 80%),
   - alpha is defined and at least the threshold (default 0.67).

A variable is reported as *insufficient pairs*, *incomplete*, *undefined* (every coder used one category, so alpha cannot be computed) or *below threshold* when it fails. The feasibility checklist uses the latest closed round. An open round is shown as provisional and never decides.

## Default values and their basis

| Rule | Default | Basis |
|---|---|---|
| Double-coded videos | 50 | Proposal pilot: both coders code 50 videos. |
| Minimum alpha | 0.67 | Proposal: minimum for tentative conclusions (0.80 is the target). |
| Usable pairs per critical variable | 40 | 80% of 50 videos, so a variable cannot pass on a small subset of the sample. |
| Completeness | 80% | Most of the sample must be fully coded before alpha is interpreted. |

Agree the values with the supervisor and record them in Research setup before starting round 1. Report the values, the number of usable pairs, the completeness and both alpha figures for every variable in the article.
