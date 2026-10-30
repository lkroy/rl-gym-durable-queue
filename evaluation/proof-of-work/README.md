# Proof of work

## Reference solution

`reference-run.log` is the real output of `npm run check:reference`
(reference installed as the solution, full verifier suite run).
Result: **score 1.0, 44/44 checks passed** (all 10 categories: core,
scheduling, retries, dedupe, lease, recovery, concurrency, idempotency,
batch, cli), verified 2026-10-29 after the reviewer iteration (idempotent
claim + atomic batch features; layout-agnostic persistence check;
deterministic torn-write recovery test; staggered SIGKILL tests;
concurrency scored at 10%).

## Mutant verification

`mutant-check.log` is the real output of `npm run check:mutants`
(verified 2026-10-29, reviewer iteration).
Result: **all 11 mutants caught** (each scores < 1.0 and fails its mapped
checks), including the three new discrimination mutants:
- m04_single_copy (no redundant storage) — caught by single-file deletion
- m08_compact (compact drops non-pending jobs) — caught by reclaim check
- m09_nolock (no OS-level locking) — caught by the parallel-claim check
  (now scored: concurrency category, 10% weight)
- m10_no_torn_repair (no torn-write repair) — caught by the deterministic
  torn-append recovery test: without repair the next command crashes with
  JSONDecodeError instead of recovering
- m11_no_dead_letter (fail never transitions to dead) — caught by the
  dead-letter check

## Frontier-model difficulty evaluation

**Status: partial — one model evaluated under a documented substitute
protocol; second model and OpenHands runs still pending.**

No scores are invented anywhere in this repo. What was actually run:

- `gemini-2.5-flash-run1.md` (+ `.response.txt`): one-shot direct API
  evaluation against the original (overly prescriptive) spec.
  **Score: 0.93 (32/34).** This exposed that the first spec read like an
  implementation recipe, so the task was hardened (see below).
- `gemini-2.5-flash-run2.md` (+ `.response.txt`): one-shot direct API
  evaluation against the hardened spec (guarantees without prescribed
  design; SIGKILL/single-file-deletion fault injection in the verifier).
  **Score: 0.6708 (17/33).** Failure categories: exit-code discipline
  (systematic), retry/backoff semantics, redundant storage, concurrency,
  delayed scheduling.

Protocol note (why not OpenHands): OpenHands requires a Docker daemon for
its agent sandbox and none is available in this build environment, so the
contract's exact harness could not run here. Rather than fabricate
OpenHands logs, each evaluation above is exactly ONE API call — the full
`task/instruction.md` plus the starter stub, one attempt, no iteration, no
tool use — with the output scored by the real hidden verifier. This is
strictly harsher than an OpenHands single pass (where the agent may take
many read/write/run/debug actions), so these scores are the model's
best case; an agentic run would face additional failure modes.

Difficulty gate (< 0.30 for two different frontier models): **not yet
demonstrated**. A third one-shot run against the newest spec (with the
idempotent-claim and batch features) was not performed — no API key was
available. Per the reviewer's note, difficulty will be judged by their own
post-submission runs (two top frontier models, expected < 40% each), which
is the appropriate harness for this bar. Recommendation: run the two contracted OpenHands
evaluations with the exact commands below before judging the gate — if
those also land well above 0.30, broaden the task's interacting
workflows rather than tightening the spec further.

```bash
# Model A (single pass via OpenHands)
export LLM_MODEL="<frontier-model-A>"
export LLM_API_KEY="<key-A>"
npm run generate          # agent builds $SOLUTION_DIR/q from task/instruction.md
npm run score             # Q_BIN defaults to ./q; prints {"score": ...}

# Model B (single pass, fresh solution dir)
export SOLUTION_DIR=/tmp/solution-b
export LLM_MODEL="<frontier-model-B>"
export LLM_API_KEY="<key-B>"
npm run generate
Q_BIN=/tmp/solution-b/q npm run score
```

Record the model names, the OpenHands logs
(`evaluation/proof-of-work/openhands-run.log`), scores and failure
categories here when the runs complete.
