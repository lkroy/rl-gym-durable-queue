#!/usr/bin/env bash
# Run two different frontier models once each via OpenHands and score them.
# Both must score < 0.30 for the difficulty gate.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="${HOME}/.local/bin:${PATH}"

MODEL_A="${MODEL_A:-anthropic/claude-sonnet-4-20250514}"
MODEL_B="${MODEL_B:-openai/gpt-4.1}"
KEY_A="${LLM_API_KEY:-${ANTHROPIC_API_KEY:-}}"
KEY_B="${LLM_API_KEY_B:-${OPENAI_API_KEY:-${LLM_API_KEY:-}}}"

if [[ -z "$KEY_A" || -z "$KEY_B" ]]; then
  echo "Need LLM_API_KEY (model A) and LLM_API_KEY_B or OPENAI_API_KEY (model B)." >&2
  exit 1
fi

run_one() {
  local label="$1" model="$2" key="$3"
  local sdir="/tmp/solution-${label}"
  rm -rf "$sdir"
  mkdir -p "$sdir"
  echo "=== Generating with $model ($label) ==="
  SOLUTION_DIR="$sdir" \
    LLM_MODEL="$model" \
    LLM_API_KEY="$key" \
    OPENHANDS_LOG_NAME="openhands-${label}.log" \
    bash "$ROOT/scripts/generate.sh"
  echo "=== Scoring $label ==="
  Q_BIN="$sdir/q" python3 "$ROOT/evaluation/score.py" \
    | tee "$ROOT/evaluation/proof-of-work/score-${label}.json"
}

run_one "model-a" "$MODEL_A" "$KEY_A"
run_one "model-b" "$MODEL_B" "$KEY_B"

python3 - <<'PY'
import json, pathlib
root = pathlib.Path("/workspace/evaluation/proof-of-work")
for label in ("model-a", "model-b"):
    p = root / f"score-{label}.json"
    data = json.loads(p.read_text())
    score = data.get("score", 1.0)
    print(f"{label}: score={score}")
    if score >= 0.30:
        raise SystemExit(f"difficulty gate failed: {label} scored {score} (>= 0.30)")
print("DIFFICULTY GATE PASSED: both models < 0.30")
PY
