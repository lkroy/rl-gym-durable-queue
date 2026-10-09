#!/usr/bin/env bash
# Runs the model via OpenHands to generate a solution into $SOLUTION_DIR/q.
#
# This script NEVER fabricates model output. It requires a real, configured
# OpenHands installation with model API credentials. Without them it prints
# setup instructions and exits non-zero.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOLUTION_DIR="${SOLUTION_DIR:-$ROOT}"

if ! command -v openhands >/dev/null 2>&1; then
  cat >&2 <<'EOF'
generate: OpenHands CLI not found.

To run a real model evaluation you need:
  1. Install OpenHands:  pip install openhands-ai
     (see https://github.com/All-Hands-AI/OpenHands)
  2. Configure model credentials, e.g.:
       export LLM_MODEL="anthropic/claude-sonnet-4-20250514"   # model A
       export LLM_API_KEY="<your key>"
     Repeat with a second, different frontier model for model B.
  3. Re-run:  npm run generate
     then score each run with:  Q_BIN="$SOLUTION_DIR/q" npm run score

Record the model names, full OpenHands logs, scores and failure categories
under evaluation/proof-of-work/. Both models must score below 0.30 on a
single-pass run for the difficulty gate to hold.
EOF
  exit 1
fi

if [[ -z "${LLM_API_KEY:-}" ]]; then
  echo "generate: LLM_API_KEY is not set; refusing to run without credentials." >&2
  exit 1
fi

TASK_PROMPT="$ROOT/task/instruction.md"
mkdir -p "$SOLUTION_DIR"
cp "$ROOT/task/public/q" "$SOLUTION_DIR/q"

# Single-pass agent run: the model may edit only $SOLUTION_DIR/q.
openhands run \
  --task "$(cat "$TASK_PROMPT')" \
  --working-dir "$SOLUTION_DIR" \
  2>&1 | tee "$ROOT/evaluation/proof-of-work/openhands-run.log"

chmod +x "$SOLUTION_DIR/q"
echo "generate: solution written to $SOLUTION_DIR/q"
