# Durable Job Queue — RL Gym task for coding agents

A single-executable CLI (`q`, Python 3 stdlib only) managing a persistent,
crash-safe job queue on disk: enqueue / list / show / claim / complete /
fail / stats / compact / pause / drain / resume / cancel, with priorities,
delayed scheduling, deduplication, lease-based claiming, exponential-backoff
retries, dead-lettering, idempotent claim (`--idempotency-key`), atomic
batch enqueue, recurring schedules (`--cron`, timezone-aware via `--tz`),
message TTL, lease extension, fencing tokens for stale-worker protection,
multi-claim (`claim --count N`), job dependencies (`--depends-on`), job
tags (`--tag`), durable pause/drain/resume, cascade cancel, a write-ahead
log + snapshot with torn-tail recovery, and `flock`-guarded concurrency.

## Repository structure

```
.
├── package.json            # npm run generate | score | check:mutants | check:reference
├── task/
│   ├── instruction.md      # model-facing spec (observable behavior only)
│   └── public/             # starter stub `q` + README for the model
├── environment/Dockerfile  # python:3.11-slim + pytest + pyyaml, WORKDIR /work
├── reference/              # reference solution (scores 1.0)
├── evaluation/
│   ├── tests/              # black-box pytest checks (subprocess only)
│   ├── score.py            # weighted scorer (prints JSON)
│   ├── check_mutants.py    # verifies all mutants are caught
│   ├── acceptance-criteria.yml
│   ├── scoring.yml         # weights sum to exactly 1.0
│   ├── mutants/            # buggy copies of q + mutants.yml
│   └── proof-of-work/      # reference/mutant logs; OpenHands eval needs API keys
├── app-setup/              # build.sh / reset.sh / start.sh lifecycle scripts
└── scripts/                # generate.sh (real OpenHands runner), check_reference.sh
```

## Quick start

```bash
npm run check:reference   # reference -> score must be exactly 1.0
npm run check:mutants     # all mutants must be caught
npm run score             # score $SOLUTION_DIR/q (Q_BIN env overrides)
npm run generate          # real OpenHands model run (needs LLM_API_KEY)
```

## Scoring

Weights sum to exactly **1.0**; no category exceeds **0.10** (workshop deck
cap). Largest shares: interactions 0.10, recovery 0.10, concurrency 0.09,
fencing 0.08, deps 0.08; then drain/tags/pause/cancel and many smaller
categories (retries, lease, schedules, tz, ttl, scheduling, idempotency,
batch, claim_batch, cli, dedupe, core). Per category: fraction of its
checks passed × weight.
