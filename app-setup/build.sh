#!/usr/bin/env bash
# Prepares the model solution so the verifier can interact with it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOLUTION_DIR="${SOLUTION_DIR:-$ROOT}"
Q="$SOLUTION_DIR/q"

if [[ ! -x "$Q" ]]; then
  echo "build: $Q not found or not executable" >&2
  exit 1
fi

TMPD="$(mktemp -d)"
export QDATA_DIR="$TMPD/qdata"
if ! "$Q" stats >/dev/null; then
  echo "build: smoke test '$Q stats' failed" >&2
  rm -rf "$TMPD"
  exit 1
fi
rm -rf "$TMPD"
echo "build: OK ($Q)"
