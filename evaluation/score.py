#!/usr/bin/env python3
"""Score a `q` solution binary against the hidden verifier suite.

Usage: Q_BIN=/path/to/q python3 evaluation/score.py
(Q_BIN defaults to ./q, the solution built by app-setup/build.sh.)

Runs pytest once, maps each check to its scoring category via scoring.yml,
and prints {"score": <0..1>, "categories": {...}, "failed": [...], ...}.
Per category: (checks passed / checks in category) * weight.
"""
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

import yaml

EVAL = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(EVAL)


def main():
    with open(os.path.join(EVAL, "scoring.yml")) as f:
        scoring = yaml.safe_load(f)
    weights = scoring["weights"]
    files = scoring["files"]
    total_w = sum(weights.values())
    assert abs(total_w - 1.0) < 1e-9, \
        "scoring.yml weights sum to %r, must be exactly 1.0" % total_w

    q_bin = os.environ.get("Q_BIN", os.path.join(ROOT, "q"))
    if not (os.path.isfile(q_bin) and os.access(q_bin, os.X_OK)):
        print(json.dumps({"error": "Q_BIN not found or not executable: %s"
                                   % q_bin, "score": 0.0}))
        return 2

    junit = os.path.join(EVAL, ".junit.xml")
    if os.path.exists(junit):
        os.remove(junit)
    env = dict(os.environ, Q_BIN=q_bin)
    subprocess.run(
        [sys.executable, "-m", "pytest", os.path.join(EVAL, "tests"),
         "-q", "--junitxml=%s" % junit, "-p", "no:cacheprovider"],
        capture_output=True, text=True, env=env, cwd=ROOT, timeout=600)

    tree = ET.parse(junit)
    # classname for plain test functions is the module name, e.g. "test_core".
    per_file = {}
    failed = []
    total = 0
    for tc in tree.getroot().iter("testcase"):
        classname = tc.get("classname") or ""
        name = tc.get("name") or ""
        module = classname.split(".")[-1]
        fname = module + ".py" if not module.endswith(".py") else module
        bad = tc.find("failure") is not None or tc.find("error") is not None \
            or tc.find("skipped") is not None
        per_file.setdefault(fname, {"passed": 0, "total": 0})
        per_file[fname]["total"] += 1
        total += 1
        if bad:
            failed.append("%s::%s" % (fname, name))
        else:
            per_file[fname]["passed"] += 1

    file_to_cat = {v: k for k, v in files.items()}
    categories = {}
    score = 0.0
    for fname, stats in per_file.items():
        cat = file_to_cat.get(fname)
        if cat is None:
            continue
        frac = stats["passed"] / stats["total"] if stats["total"] else 0.0
        categories[cat] = round(frac, 4)
        score += frac * weights[cat]
    for cat in weights:
        categories.setdefault(cat, 0.0)

    out = {
        "score": round(score, 4),
        "categories": categories,
        "failed": sorted(failed),
        "passed": total - len(failed),
        "total": total,
        "q_bin": q_bin,
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
