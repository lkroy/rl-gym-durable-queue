# Durable Job Queue — RL Gym task for coding agents

A single-executable CLI (`q`, Python 3 stdlib only) managing a persistent,
crash-safe job queue on disk: enqueue / list / show / claim / complete /
fail / stats / compact, with priorities, delayed scheduling, deduplication,
lease-based claiming, exponential-backoff retries, dead-lettering,
idempotent claim (`--idempotency-key`), atomic batch enqueue, a
write-ahead log + snapshot with torn-tail recovery, and `flock`-guarded
concurrency.

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
│   ├── tests/              # 46 black-box pytest checks (subprocess only)
│   ├── score.py            # weighted scorer (prints JSON)
│   ├── check_mutants.py    # verifies all 11 mutants are caught
│   ├── acceptance-criteria.yml
│   ├── scoring.yml         # weights sum to exactly 1.0
│   ├── mutants/            # 11 buggy copies of q + mutants.yml
│   └── proof-of-work/      # real run logs; model eval pending API keys
├── app-setup/              # build.sh / reset.sh / start.sh lifecycle scripts
└── scripts/                # generate.sh (real OpenHands runner), check_reference.sh
```

## Quick start

```bash
npm run check:reference   # reference -> score must be exactly 1.0
npm run check:mutants     # all 11 mutants must be caught
npm run score             # score $SOLUTION_DIR/q (Q_BIN env overrides)
npm run generate          # real OpenHands model run (needs LLM_API_KEY)
```

## Scoring

Weights (sum = 1.0): core 0.15, scheduling 0.15, retries 0.15, dedupe 0.10,
lease 0.10, recovery 0.10, concurrency 0.10, idempotency 0.05, batch 0.05,
cli 0.05. Per category: fraction of its checks passed x weight.
