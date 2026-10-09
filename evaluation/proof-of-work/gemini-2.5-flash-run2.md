# Model evaluation record — gemini-2.5-flash, run 2 (hardened task)

Date: 2026-10-09
Model: `gemini-2.5-flash` (temperature 0.5, maxOutputTokens 65536)
Task spec version: hardened `task/instruction.md`
  (durability/crash-recovery stated as observable guarantees and fault
  scenarios; NO prescribed storage format; NO per-command lifecycle recipe)

## Protocol

Same documented deviation as run 1 (no Docker available for OpenHands):
exactly ONE API call — the full hardened `task/instruction.md` plus the
starter stub, one attempt, no iteration, no tool use. Output extracted
verbatim from the single ```python code block, saved as executable `q`,
scored with the real hidden verifier:
`Q_BIN=/tmp/gemini-eval2/q python3 evaluation/score.py`.

## Result

- Score: **0.6708** (17/33 checks)
- Category breakdown:
  - core 1.00, dedupe 1.00 — solid
  - recovery 0.75, scheduling 0.67, lease 0.50 — partial
  - cli 0.25, retries 0.00 — weak
- Failure analysis (from direct probes of the model's binary):
  - Systematic exit-code bug: the implementation prints validation errors
    to stderr but exits 0 in almost every error case (bad payload JSON,
    duplicate id, complete/fail on non-claimed jobs, etc.), failing 9 CLI
    checks. The spec's exit-code discipline (0/1/2/3/4) was not followed.
  - `fail` retry semantics broken (backoff/dead-letter paths), failing all
    retry checks.
  - No redundant storage: deleting a single state file loses jobs
    (failed `test_delete_any_single_file_preserves_jobs`).
  - Lost the delayed-job check and the parallel-claim concurrency check.

## Interpretation

Hardening dropped the one-shot score from 0.93 to 0.67, but the 0.30
difficulty gate is NOT met under this protocol. Two caveats for the
reviewer:

1. One-shot direct API evaluation is the model's best case: it only
   measures transcription of a complete spec. The contract's actual
   protocol — an OpenHands agentic single pass, where the model must
   explore, write files, run commands, and debug through tool use —
   introduces failure modes this protocol cannot capture, and typically
   scores lower.
2. Single samples are noisy (run 1: 0.93, run 2: 0.67 with the same
   model family); the truth lies in a distribution, not one number.

Recommendation: run the two contracted OpenHands evaluations
(`npm run generate` with two different frontier-model keys, then
`npm run score`) before judging the difficulty gate. If those also land
well above 0.30, the task needs broadening (more interacting stateful
workflows) rather than further spec tightening.
