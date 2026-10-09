#!/usr/bin/env bash
# Installs reference/q as the solution and asserts it scores exactly 1.0.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export SOLUTION_DIR="${SOLUTION_DIR:-$ROOT/.solution-ref}"
mkdir -p "$SOLUTION_DIR"
cp "$ROOT/reference/q" "$SOLUTION_DIR/q"
chmod +x "$SOLUTION_DIR/q"

bash "$ROOT/app-setup/build.sh"

Q_BIN="$SOLUTION_DIR/q" python3 "$ROOT/evaluation/score.py" \
  | tee "$ROOT/evaluation/proof-of-work/reference-run.log"

python3 - "$ROOT/evaluation/proof-of-work/reference-run.log" <<'EOF'
import json, sys
log = open(sys.argv[1]).read()
start = log.find("{")
doc = json.loads(log[start:])
assert doc["score"] == 1.0, "reference score is %r, expected 1.0" % doc["score"]
print("check:reference OK: score == 1.0 (%d/%d checks)" % (doc["passed"], doc["total"]))
EOF
