# Proof of work

## Reference solution (difficulty iteration v3)

`reference-run-v3.json` is the real scorer output against the v3 reference
(`Q_BIN=reference/q`, same procedure as `npm run check:reference`).

Result: **score 1.0, 93/93 checks passed** across 18 categories (core,
scheduling, retries, dedupe, lease, recovery, concurrency, idempotency,
batch, cli, schedules, ttl, fencing, tz, claim_batch, deps, pause, cancel).

v3 adds interacting workflows that agents commonly get wrong in combination:
job dependency DAGs (claim gating + dead-cascade), durable pause/resume, and
transitive cancel `--cascade`. Weights in `evaluation/scoring.yml` sum to
exactly 1.0.

`dst-verification.md` records white-box DST verification for `--tz` schedules.

## Mutant verification

`mutant-check-v3.log` records `npm run check:mutants` against **20 mutants**.
Each mutant must score `< 1.0` and fail its mapped `must_fail` checks.

New v3 mutants:
- m18_deps — claim ignores `depends_on`
- m19_pause — pause flag not persisted across process restart
- m20_cascade — `--cascade` only cancels direct dependents

`evaluation/score.py` now uses a unique tempfile for the junit report so
overlapping score runs cannot corrupt each other via a shared `.junit.xml`.

## Frontier-model difficulty evaluation

### Historical one-shot (pre-OpenHands) — rescoring against v3

`gemini-2.5-flash-run2.response.txt` was the model's one-shot solution for
the *prior* hardened spec (no deps/pause/cancel). Re-scored unchanged against
the v3 suite (`gemini-2.5-flash-run2-rescored-v3.json`):

- **Score: 0.2198 (21/93)** — below the 0.30 gate
- Failure categories include: pause 0.0, cancel 0.0, fencing 0.0,
  concurrency 0.0, retries 0.0, deps 0.29, recovery 0.4, cli 0.25, tz 0.0

This is evidence the v3 surface is hard, but it is **not** a substitute for
the contracted protocol (two different frontier models, OpenHands, single
pass on the current `task/instruction.md`).

### Contracted OpenHands dual-model runs

**Status: blocked on API credentials in this environment.**

Harness is ready:
- `npm run generate` → `scripts/generate.sh` (OpenHands headless / local runtime)
- `npm run generate:two` → `scripts/eval_two_models.sh` (model A + model B)

Required secrets (requested via Cloud Agent setup actions):
- `LLM_API_KEY` (and `LLM_MODEL`) for model A
- `LLM_API_KEY_B` or a second provider key for a *different* frontier model B

```bash
# Model A
export LLM_MODEL="anthropic/claude-sonnet-4-20250514"
export LLM_API_KEY="<key-A>"
export SOLUTION_DIR=/tmp/solution-a
export OPENHANDS_LOG_NAME=openhands-model-a.log
npm run generate
Q_BIN=/tmp/solution-a/q npm run score | tee evaluation/proof-of-work/score-model-a.json

# Model B (different frontier model)
export LLM_MODEL="openai/gpt-4.1"
export LLM_API_KEY="<key-B>"
export SOLUTION_DIR=/tmp/solution-b
export OPENHANDS_LOG_NAME=openhands-model-b.log
npm run generate
Q_BIN=/tmp/solution-b/q npm run score | tee evaluation/proof-of-work/score-model-b.json
```

Both scores must be **< 0.30**. Record model names, OpenHands logs, scores,
and failure categories here when the runs complete.

## Access / privacy notes

- Application requires a **private** GitHub repository and collaborator access
  for `content.team@problemsetters.com`.
- `content-team-hr` currently has write access on this repo; confirm that
  covers the required mailbox, and set the repository visibility to private.
