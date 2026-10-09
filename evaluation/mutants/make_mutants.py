#!/usr/bin/env python3
"""Generate the 8 mutant copies of reference/q (one realistic bug each).

Run from the repo root: python3 evaluation/mutants/make_mutants.py
Idempotent: rewrites evaluation/mutants/m0* and mutants.yml.
"""
import os
import re

EVAL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(EVAL)
MDIR = os.path.join(EVAL, "mutants")

with open(os.path.join(ROOT, "reference", "q")) as f:
    REF = f.read()


def replace_function(src, func_name, new_src):
    start = src.index("def %s(" % func_name)
    nxt = src.index("\ndef ", start + 1)
    return src[:start] + new_src + src[nxt:]


def sub_once(src, old, new):
    assert src.count(old) == 1, "pattern not unique/found: %r" % old[:60]
    return src.replace(old, new, 1)


MUTANTS = {}


def mutant(name, bug, must_fail, transform):
    MUTANTS[name] = {"bug": bug, "must_fail": must_fail,
                     "src": transform(REF)}


# 1. claim ignores priority (FIFO only)
mutant("m01_priority",
       "claim orders by created_at only, ignoring priority",
       ["test_scheduling.py::test_priority_order"],
       lambda s: sub_once(
           s,
           "    cands.sort(key=lambda j: (-j[\"priority\"], j[\"created_at\"], j[\"id\"]))",
           "    cands.sort(key=lambda j: (j[\"created_at\"], j[\"id\"]))  # BUG: priority ignored"))

# 2. fail requeues without backoff
mutant("m02_backoff",
       "fail sets run_at=now (no exponential backoff)",
       ["test_retries.py::test_fail_backoff_requeue"],
       lambda s: sub_once(
           s,
           "        job[\"run_at\"] = t + 10 * 2 ** (job[\"attempts\"] - 1)",
           "        job[\"run_at\"] = t  # BUG: no backoff"))

# 3. dedupe ignored
mutant("m03_dedupe",
       "enqueue ignores --dedupe-key (always creates a new job)",
       ["test_dedupe.py::test_dedupe_same_key_returns_existing"],
       lambda s: replace_function(
           s, "_find_dedupe",
           "def _find_dedupe(jobs, key):\n"
           "    return None  # BUG: dedupe ignored\n\n"))

# 4. no torn-tail handling -> traceback on corrupt tail
mutant("m04_torn_tail",
       "WAL torn tail never truncated (crash/traceback on corrupt tail)",
       ["test_recovery.py::test_torn_tail_ignored"],
       lambda s: replace_function(
           s, "_truncate_torn_tail",
           "def _truncate_torn_tail(path):\n"
           "    return False  # BUG: torn tail not handled\n\n"))

# 5. expired leases never swept
mutant("m05_lease",
       "claim never sweeps expired leases",
       ["test_lease.py::test_lease_expiry_reclaim",
        "test_lease.py::test_complete_after_lease_expiry_fails"],
       lambda s: replace_function(
           s, "sweep_expired",
           "def sweep_expired(jobs, t):\n"
           "    return []  # BUG: expired leases never swept\n\n"))

# 6. complete() skips the claimed-state check
mutant("m06_complete",
       "complete() allows completing a non-claimed job",
       ["test_cli.py::test_complete_pending_conflict"],
       lambda s: sub_once(
           s,
           "    if job[\"status\"] != \"claimed\":\n"
           "        die(\"job not claimed\", 3)  # REQ-CLAIMED-COMPLETE",
           "    pass  # BUG: claimed-state check skipped"))

# 7. claim ignores run_at (delayed jobs claimable immediately)
mutant("m07_delay",
       "claim ignores run_at (delayed jobs become claimable at once)",
       ["test_scheduling.py::test_delayed_job_not_claimable"],
       lambda s: sub_once(
           s,
           "    cands = [j for j in jobs.values()\n"
           "             if j[\"status\"] == \"pending\" and j[\"run_at\"] <= t]",
           "    cands = [j for j in jobs.values()\n"
           "             if j[\"status\"] == \"pending\"]  # BUG: run_at ignored"))

# 8. compact doesn't truncate the WAL
mutant("m08_compact",
       "compact rewrites the snapshot but never truncates wal.log",
       ["test_recovery.py::test_compact_truncates_log"],
       lambda s: sub_once(
           s,
           "            truncate_wal(dirpath)\n",
           "            pass  # BUG: wal.log not truncated\n"))


def main():
    for name, m in sorted(MUTANTS.items()):
        path = os.path.join(MDIR, name)
        with open(path, "w") as f:
            f.write(m["src"])
        os.chmod(path, 0o755)
        # sanity: mutant must differ from reference and stay valid python
        assert m["src"] != REF, name
        compile(m["src"], path, "exec")
        print("wrote", path)
    yml = {"mutants": {
        name: {"file": name, "bug": m["bug"], "must_fail": m["must_fail"]}
        for name, m in sorted(MUTANTS.items())}}
    import yaml
    with open(os.path.join(MDIR, "mutants.yml"), "w") as f:
        yaml.safe_dump(yml, f, sort_keys=True)
    print("wrote mutants.yml")


if __name__ == "__main__":
    main()
