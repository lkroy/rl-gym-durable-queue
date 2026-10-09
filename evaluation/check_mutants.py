#!/usr/bin/env python3
"""Verify every mutant is caught: score < 1.0 AND each mapped check fails.

For each mutant in evaluation/mutants/mutants.yml, installs the mutant as
the solution binary in a temp dir and runs evaluation/score.py against it.
Exits 0 only if ALL mutants are caught.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

import yaml

EVAL = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(EVAL)


def main():
    with open(os.path.join(EVAL, "mutants", "mutants.yml")) as f:
        spec = yaml.safe_load(f)["mutants"]
    all_ok = True
    for name in sorted(spec):
        m = spec[name]
        tmp = tempfile.mkdtemp(prefix="mutant-")
        try:
            qbin = os.path.join(tmp, "q")
            shutil.copy(os.path.join(EVAL, "mutants", m["file"]), qbin)
            os.chmod(qbin, 0o755)
            env = dict(os.environ, Q_BIN=qbin)
            proc = subprocess.run(
                [sys.executable, os.path.join(EVAL, "score.py")],
                capture_output=True, text=True, env=env, cwd=ROOT,
                timeout=600)
            try:
                result = json.loads(proc.stdout)
            except Exception as exc:
                print("%s: scorer output unparseable (%s)\nstdout=%r\nstderr=%r"
                      % (name, exc, proc.stdout[-2000:], proc.stderr[-2000:]))
                all_ok = False
                continue
            score = result.get("score", 0.0)
            failed = set(result.get("failed", []))
            missing = [c for c in m["must_fail"] if c not in failed]
            caught = score < 1.0 and not missing
            print("%s: score=%.4f must_fail=%s missing=%s -> %s"
                  % (name, score, m["must_fail"], missing,
                     "CAUGHT" if caught else "NOT CAUGHT"))
            if not caught:
                all_ok = False
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print("ALL MUTANTS CAUGHT" if all_ok else "MUTANT CHECK FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
