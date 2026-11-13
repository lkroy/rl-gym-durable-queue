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

Result: **ALL MUTANTS CAUGHT (20/20)**.

Method: targeted runs of each mutant's mapped `must_fail` checks with
`Q_BIN=<mutant>` (the default `check_mutants.py` mode). Those checks are
score-bearing, so a failed mapped check implies overall score `< 1.0`.
Set `MUTANT_FULL=1` to additionally run the full weighted suite per mutant
(slow: schedule tests wait on minute boundaries).

New v3 mutants:
- m18_deps — claim ignores `depends_on`
- m19_pause — pause flag not persisted across process restart
- m20_cascade — `--cascade` only cancels direct dependents

`evaluation/score.py` uses a unique tempfile for the junit report so
overlapping score runs cannot corrupt each other.

## Frontier-model difficulty evaluation

### Blocker: no LLM API keys available

The task author / Cloud Agent environment **does not have frontier-model API
keys**. Therefore the contracted protocol — two different frontier models,
medium reasoning, single-pass OpenHands, both scores `< 0.30` — **cannot be
executed here**. No scores are invented.

Harness is ready for when keys exist:
- `npm run generate` → `scripts/generate.sh` (OpenHands local/process runtime)
- `npm run generate:two` → `scripts/eval_two_models.sh`

```bash
export LLM_MODEL="anthropic/claude-sonnet-4-20250514"
export LLM_API_KEY="<key-A>"
export SOLUTION_DIR=/tmp/solution-a
export OPENHANDS_LOG_NAME=openhands-model-a.log
npm run generate
Q_BIN=/tmp/solution-a/q npm run score | tee evaluation/proof-of-work/score-model-a.json

export LLM_MODEL="openai/gpt-4.1"   # different frontier model
export LLM_API_KEY="<key-B>"
export SOLUTION_DIR=/tmp/solution-b
export OPENHANDS_LOG_NAME=openhands-model-b.log
npm run generate
Q_BIN=/tmp/solution-b/q npm run score | tee evaluation/proof-of-work/score-model-b.json
```

### Supporting difficulty evidence (not a substitute for OpenHands)

`gemini-2.5-flash-run2.response.txt` was a one-shot solution for the *prior*
hardened spec. Re-scored unchanged against the v3 suite
(`gemini-2.5-flash-run2-rescored-v3.json`):

- **Score: 0.2198 (21/93)** — below the 0.30 gate
- Failures include pause/cancel/fencing/concurrency/retries/tz at 0.0 and
  weak deps/recovery/cli

This supports that the v3 surface is hard, but it is **not** two different
frontier models on the current instruction via OpenHands.

Per the application brief, post-submission review runs two top frontier
models (e.g. Opus / Astra, high reasoning) with an expected bar of `< 40%`.
That is the appropriate harness for the remaining difficulty gate.

## Access / privacy notes

- Application requires a **private** GitHub repository and collaborator access
  for `content.team@problemsetters.com`.
- `content-team-hr` currently has write access; confirm that covers the
  required mailbox, and set repository visibility to private.
