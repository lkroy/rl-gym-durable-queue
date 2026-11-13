#!/usr/bin/env python3
"""Verify every mutant is caught by its mapped must_fail checks.

Default mode (fast, deterministic): for each mutant in
evaluation/mutants/mutants.yml, run only that mutant's mapped pytest
node IDs with Q_BIN=<mutant>. A mutant is CAUGHT when every must_fail
check fails. Those checks are score-bearing in scoring.yml, so a failed
must_fail check implies overall score < 1.0.

Set MUTANT_FULL=1 to also run evaluation/score.py per mutant and require
score < 1.0 with the must_fail IDs present in the scorer's failed list
(slow: ~minutes per mutant because of schedule minute-boundary waits).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import yaml

EVAL = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(EVAL)


def _log(msg):
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _run_must_fail(qbin, checks):
    """Return (failed_set, missing_from_run)."""
    fd, junit = tempfile.mkstemp(prefix="mutant-junit-", suffix=".xml")
    os.close(fd)
    try:
        env = dict(os.environ, Q_BIN=qbin)
        node_ids = [os.path.join(EVAL, "tests", c) for c in checks]
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", *node_ids,
             "-q", "--junitxml=%s" % junit, "-p", "no:cacheprovider"],
            capture_output=True, text=True, env=env, cwd=ROOT, timeout=300)
        if not os.path.isfile(junit) or os.path.getsize(junit) == 0:
            _log("  pytest produced no junit (rc=%s stderr=%r)"
                 % (proc.returncode, (proc.stderr or "")[-500:]))
            return set(), list(checks)
        failed = set()
        seen = set()
        tree = ET.parse(junit)
        for tc in tree.getroot().iter("testcase"):
            classname = tc.get("classname") or ""
            name = tc.get("name") or ""
            module = classname.split(".")[-1]
            fname = module + ".py" if not module.endswith(".py") else module
            node = "%s::%s" % (fname, name)
            seen.add(node)
            bad = (tc.find("failure") is not None
                   or tc.find("error") is not None
                   or tc.find("skipped") is not None)
            if bad:
                failed.add(node)
        missing_run = [c for c in checks if c not in seen]
        return failed, missing_run
    finally:
        try:
            os.remove(junit)
        except OSError:
            pass


def _run_full_score(qbin):
    env = dict(os.environ, Q_BIN=qbin)
    proc = subprocess.run(
        [sys.executable, os.path.join(EVAL, "score.py")],
        capture_output=True, text=True, env=env, cwd=ROOT, timeout=900)
    import json
    return json.loads(proc.stdout)


def main():
    with open(os.path.join(EVAL, "mutants", "mutants.yml")) as f:
        spec = yaml.safe_load(f)["mutants"]
    full = os.environ.get("MUTANT_FULL", "").strip() in ("1", "true", "yes")
    all_ok = True
    for name in sorted(spec):
        m = spec[name]
        tmp = tempfile.mkdtemp(prefix="mutant-")
        try:
            qbin = os.path.join(tmp, "q")
            shutil.copy(os.path.join(EVAL, "mutants", m["file"]), qbin)
            os.chmod(qbin, 0o755)
            checks = list(m["must_fail"])
            failed, missing_run = _run_must_fail(qbin, checks)
            missing = [c for c in checks if c not in failed]
            if missing_run:
                _log("%s: checks not executed: %s -> NOT CAUGHT"
                     % (name, missing_run))
                all_ok = False
                continue
            if full:
                try:
                    result = _run_full_score(qbin)
                except Exception as exc:
                    _log("%s: full score failed (%s) -> NOT CAUGHT" % (name, exc))
                    all_ok = False
                    continue
                score = result.get("score", 0.0)
                scored_failed = set(result.get("failed", []))
                missing_full = [c for c in checks if c not in scored_failed]
                caught = score < 1.0 and not missing_full
                _log("%s: score=%.4f must_fail=%s missing=%s -> %s"
                     % (name, score, checks, missing_full,
                        "CAUGHT" if caught else "NOT CAUGHT"))
            else:
                # Targeted mode: every mapped check must fail against the mutant.
                caught = not missing
                _log("%s: must_fail=%s missing=%s -> %s"
                     % (name, checks, missing,
                        "CAUGHT" if caught else "NOT CAUGHT"))
            if not caught:
                all_ok = False
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    _log("ALL MUTANTS CAUGHT" if all_ok else "MUTANT CHECK FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
