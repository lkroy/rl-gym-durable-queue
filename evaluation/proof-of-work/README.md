# Proof of work

## Reference solution (difficulty iteration v4)

`reference-run-v4.json` is the real scorer output against the v4 reference
(`Q_BIN=reference/q`, same procedure as `npm run check:reference`).

Result: **score 1.0, 119/119 checks passed** across 21 categories.

### Why v4 targets Opus / Astra &lt; 40%

Post-submission reviewers run top frontier models with **high reasoning**.
Checklist features alone are not enough — strong agents implement them.

v4 therefore:

1. Adds interlocking workflows models commonly get wrong in combination:
   durable **drain**, hard **tag partitions** on claim, and the
   **pause + idempotency** in-flight exception.
2. Puts **~86% of score weight** on hard domains: interactions, recovery
   (SIGKILL / torn writes / single-file loss), concurrency races, fencing,
   deps, drain, tags, pause, cancel, retries, lease.
3. Leaves only **~14%** on easy surface (core/cli/dedupe/batch/schedules/…).
4. Adds crash/race interaction checks (kill mid-batch-with-deps, meta
   survival after single-file loss, stale-fence vs dependents, parallel
   drain vs enqueue, parallel claim with deps).

Weights in `evaluation/scoring.yml` sum to exactly **1.0**.

`dst-verification.md` records white-box DST verification for `--tz` schedules.

## Mutant verification

`mutant-check-v4.log` records `npm run check:mutants` against **25 mutants**.

Result: **ALL MUTANTS CAUGHT (25/25)**.

## Frontier-model difficulty evaluation

### No author API keys

OpenHands dual-model runs were **not** executed here (no LLM API keys).
No scores are invented. Harness: `npm run generate` / `npm run generate:two`.

### Supporting signal (not a substitute)

Prior Gemini 2.5 Flash one-shot (old spec) rescored on v4
(`gemini-2.5-flash-run2-rescored-v4.json`): score well below 0.40.

This is incomplete evidence (wrong model, wrong protocol, old attempt).
The contracted post-submission Opus/Astra high-reasoning runs are the gate.

### Expected reviewer protocol

Single-pass OpenHands on current `task/instruction.md` with two top models
(e.g. Opus 5.5, Astra), high reasoning — both should score **&lt; 0.40**.

## Workshop deck alignment

Aligned with HackerRank RL Gym workshop guidance:

1. **PRD instruction** — `task/instruction.md` is outcomes / rules / CLI
   contract (not an implementation plan). Storage recipes (fsync, flock,
   WAL, snapshot layout) are not prescribed; durability/crash/concurrency
   are stated as observable outcomes. Background work is obligations, not
   a numbered pre-step recipe.
2. **Weight cap ≤ 10%** — every category in `evaluation/scoring.yml` is
   ≤ 0.10; weights sum to exactly 1.0; many small checks.
3. **Paired guards** — “did it” checks paired with “didn’t break” guards
   (cascade leave unrelated jobs alone; drain preserves enqueued work;
   tagged complete leaves untagged claimable; pause still allows
   complete/fail of claimed jobs; cancel one branch does not kill
   siblings).
4. **Stub ≈ 0 / reference = 1.0** — unchanged public stub scores near 0;
   reference still scores 1.0; mutants remain caught.

## Access / privacy

- Repo should be **private**; invite `content.team@problemsetters.com`.
- `content-team-hr` currently has write access.
