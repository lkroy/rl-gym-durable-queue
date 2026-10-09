# Model evaluation record — gemini-2.5-flash, run 1 (baseline)

Date: 2026-10-09
Model: `gemini-2.5-flash` (temperature 0.5, maxOutputTokens 65536)
Task spec version: pre-hardening `task/instruction.md`
  (the version that prescribed the on-disk format and per-command lifecycle)

## Protocol (documented deviation from the contract)

The contract asks for OpenHands as the agent harness. OpenHands could not
run in this environment: it requires a Docker daemon for its agent sandbox
and none is available here. Instead of fabricating OpenHands logs, the
evaluation was done as a **direct single-pass API call**, which is fully
documented here:

- The model received exactly what an OpenHands agent would receive:
  the full `task/instruction.md` plus the starter stub from `task/public/q`.
- Exactly ONE API call was made (one attempt, no iteration, no fixes,
  no tool use). This is strictly harsher than an OpenHands single pass,
  where the agent may take many actions (read, write, run, debug) inside
  one run. A low score here would therefore be strong evidence of
  difficulty; a high score means the task, as specified, is directly
  implementable by a frontier model.
- The model's output (one ```python code block) was extracted verbatim,
  saved as an executable `q`, and scored with the real hidden verifier:
  `Q_BIN=/tmp/gemini-eval/q python3 evaluation/score.py`.

No scores were invented; the score below comes from the actual verifier run.

## Result

- Score: **0.93** (32/34 checks)
- Failed checks:
  - `test_core.py::test_wal_and_snapshot_format` — the model used its own
    on-disk layout instead of the prescribed one.
  - `test_recovery.py::test_missing_snapshot_rebuilds_from_log` —
    consequence of the above.
- All 32 behavioral checks passed (core, scheduling, retries, dedupe,
  lease, CLI, and the remaining recovery checks).

## Interpretation

The task as specified was too easy for a frontier model: the instruction
read like a complete implementation recipe (exact file formats plus a
step-by-step per-command lifecycle), so one-shot transcription sufficed.
Per the contract's difficulty gate (< 0.30), the task was hardened in
response: `task/instruction.md` now states durability and crash-recovery
as observable guarantees and fault scenarios WITHOUT prescribing storage
formats or the command lifecycle, and the verifier now probes crash
atomicity with real SIGKILL fault injection, single-file deletion, and
kill-during-compact scenarios. See run 2 below for the re-evaluation
against the hardened task.
