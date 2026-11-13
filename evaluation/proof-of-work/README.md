# Proof of work

## Reference solution (difficulty iteration v4)

`reference-run-v4.json` is the real scorer output against the v4 reference
(`Q_BIN=reference/q`, same procedure as `npm run check:reference`).

v4 targets **Opus / Astra high-reasoning OpenHands runs scoring below 40%**
via heavy weight on interlocking cross-feature behavior (`interactions` 0.18)
plus durable drain mode, job tags (hard claim partition), and the
pause+idempotency in-flight exception that models commonly miss.

Result: **score 1.0** across 21 categories (interactions, deps, pause, cancel,
drain, tags, recovery, concurrency, fencing, retries, lease, schedules, tz,
ttl, scheduling, idempotency, batch, claim_batch, cli, dedupe, core).

Weights in `evaluation/scoring.yml` sum to exactly 1.0.

`dst-verification.md` records white-box DST verification for `--tz` schedules.

## Mutant verification

`mutant-check-v4.log` records `npm run check:mutants` against **25 mutants**.

Result: **ALL MUTANTS CAUGHT (25/25)**.

Method: targeted runs of each mutant's mapped `must_fail` checks with
`Q_BIN=<mutant>` (the default `check_mutants.py` mode). Those checks are
score-bearing, so a failed mapped check implies overall score `< 1.0`.
Set `MUTANT_FULL=1` to additionally run the full weighted suite per mutant
(slow: schedule tests wait on minute boundaries).

New v4 mutants:
- m21_drain_persist — drain flag not persisted across process restart
- m22_tag_leak — claim without `--tag` also returns tagged jobs
- m23_pause_idem — while paused, idempotency key never returns in-flight job
- m24_count_deps — claim `--count` does not skip unmet deps
- m25_resume_partial — resume clears paused but not draining

`evaluation/score.py` uses a unique tempfile for the junit report so
overlapping score runs cannot corrupt each other.

## Frontier-model difficulty evaluation

### Blocker: no LLM API keys available

The task author / Cloud Agent environment **does not have frontier-model API
keys**. Therefore the contracted protocol — two different frontier models,
high reasoning, single-pass OpenHands, both scores `< 0.40` — **cannot be
executed here**. No scores are invented.

Harness is ready for when keys exist:
- `npm run generate` → `scripts/generate.sh` (OpenHands local/process runtime)
- `npm run generate:two` → `scripts/eval_two_models.sh`

```bash
export LLM_MODEL="anthropic/claude-opus-4-20250514"
export LLM_API_KEY="<key-A>"
export SOLUTION_DIR=/tmp/solution-a
export OPENHANDS_LOG_NAME=openhands-model-a.log
npm run generate
Q_BIN=/tmp/solution-a/q npm run score | tee evaluation/proof-of-work/score-model-a.json

export LLM_MODEL="astra/..."   # different frontier model
export LLM_API_KEY="<key-B>"
export SOLUTION_DIR=/tmp/solution-b
export OPENHANDS_LOG_NAME=openhands-model-b.log
npm run generate
Q_BIN=/tmp/solution-b/q npm run score | tee evaluation/proof-of-work/score-model-b.json
```

### Supporting difficulty evidence (not a substitute for OpenHands)

`gemini-2.5-flash-run2.response.txt` was a one-shot solution for a *prior*
hardened spec. Re-scored unchanged against later suites it lands well below
the 0.40 gate — supporting that the surface is hard, but it is **not** two
different frontier models on the current instruction via OpenHands.

Per the application brief, post-submission review runs two top frontier
models (e.g. Opus / Astra, high reasoning) with an expected bar of `< 40%`.
v4’s interaction weight and interlocking semantics are aimed at that bar.

## Access / privacy notes

- Application requires a **private** GitHub repository and collaborator access
  for `content.team@problemsetters.com`.
- `content-team-hr` currently has write access; confirm that covers the
  required mailbox, and set repository visibility to private.
