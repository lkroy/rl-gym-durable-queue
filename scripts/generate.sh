#!/usr/bin/env bash
# Runs the model via OpenHands to generate a solution into $SOLUTION_DIR/q.
#
# This script NEVER fabricates model output. It requires a real OpenHands
# installation with model API credentials. Without them it prints setup
# instructions and exits non-zero.
#
# Uses the OpenHands headless runner with RUNTIME=local so a Docker daemon
# is not required (process sandbox on the host).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOLUTION_DIR="${SOLUTION_DIR:-$ROOT}"
LOG_NAME="${OPENHANDS_LOG_NAME:-openhands-run.log}"
LOG_PATH="$ROOT/evaluation/proof-of-work/$LOG_NAME"

LLM_MODEL="${LLM_MODEL:-}"
LLM_API_KEY="${LLM_API_KEY:-${ANTHROPIC_API_KEY:-${OPENAI_API_KEY:-${GEMINI_API_KEY:-}}}}"

have_openhands=0
if command -v openhands >/dev/null 2>&1; then
  have_openhands=1
elif python3 -c "import openhands.core.main" >/dev/null 2>&1; then
  have_openhands=1
fi

if [[ "$have_openhands" -ne 1 ]]; then
  cat >&2 <<'EOF'
generate: OpenHands not found.

To run a real model evaluation you need:
  1. Install OpenHands:  pip install 'openhands-ai>=0.62'
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

if [[ -z "$LLM_API_KEY" ]]; then
  echo "generate: LLM_API_KEY (or ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY) is not set; refusing to run without credentials." >&2
  exit 1
fi

if [[ -z "$LLM_MODEL" ]]; then
  echo "generate: LLM_MODEL is not set (example: anthropic/claude-sonnet-4-20250514)." >&2
  exit 1
fi

TASK_PROMPT="$ROOT/task/instruction.md"
mkdir -p "$SOLUTION_DIR" "$(dirname "$LOG_PATH")"
cp "$ROOT/task/public/q" "$SOLUTION_DIR/q"
chmod +x "$SOLUTION_DIR/q"

# Write a minimal OpenHands config for a single-pass local runtime run.
CFG="$SOLUTION_DIR/.openhands-config.toml"
cat >"$CFG" <<EOF
[core]
runtime = "local"
workspace_base = "$SOLUTION_DIR"
max_iterations = ${MAX_ITERATIONS:-40}

[llm]
model = "$LLM_MODEL"
api_key = "$LLM_API_KEY"
temperature = ${LLM_TEMPERATURE:-0.2}
EOF

export RUNTIME="${RUNTIME:-local}"
export LLM_API_KEY
export LLM_MODEL
export SANDBOX_VOLUMES="${SANDBOX_VOLUMES:-$SOLUTION_DIR:/workspace:rw}"

TASK_TEXT="$(cat "$TASK_PROMPT")

Working directory: $SOLUTION_DIR
Implement the program as an executable file named q at the solution root
($SOLUTION_DIR/q). You may overwrite the starter stub. Python 3 standard
library only. Do not modify files outside this directory.
"

set +e
if command -v openhands >/dev/null 2>&1 && openhands --help 2>&1 | grep -q -- '--headless'; then
  openhands --headless \
    --override-with-envs \
    -t "$TASK_TEXT" \
    2>&1 | tee "$LOG_PATH"
  rc=${PIPESTATUS[0]}
else
  python3 -m openhands.core.main \
    --config-file "$CFG" \
    -t "$TASK_TEXT" \
    -d "$SOLUTION_DIR" \
    -i "${MAX_ITERATIONS:-40}" \
    2>&1 | tee "$LOG_PATH"
  rc=${PIPESTATUS[0]}
fi
set -e

chmod +x "$SOLUTION_DIR/q" 2>/dev/null || true
echo "generate: OpenHands finished rc=$rc; solution at $SOLUTION_DIR/q; log $LOG_PATH"
exit "$rc"
