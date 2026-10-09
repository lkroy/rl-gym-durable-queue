# Proof of work

## Reference solution

`reference-run.log` is the real output of `npm run check:reference`
(reference installed as the solution, full verifier suite run).
Result: **score 1.0, 34/34 checks passed**.

## Mutant verification

`mutant-check.log` is the real output of `npm run check:mutants`.
Result: **all 8 mutants caught** (each scores < 1.0 and fails its mapped
checks).

## Frontier-model difficulty evaluation (OpenHands)

**Status: pending — models: TBD (pending client API keys).**

No model scores are claimed here. The two-model single-pass evaluation has
NOT been run because it requires the client's OpenHands setup and frontier
model API credentials, which were not provided.

Exact commands to run it once credentials are available:

```bash
# Model A (single pass)
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

Difficulty gate: both models must score **below 0.30**. Record the model
names, the OpenHands logs (`evaluation/proof-of-work/openhands-run.log`),
scores and failure categories here when the runs complete.
