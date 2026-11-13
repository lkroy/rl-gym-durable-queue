#!/usr/bin/env python3
"""Generate the mutant copies of reference/q (one realistic bug each).

Run from the repo root: python3 evaluation/mutants/make_mutants.py
Idempotent: rewrites evaluation/mutants/m* and mutants.yml.
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

# 4. single copy of state (no write-ahead log): deleting the one file loses all
mutant("m04_single_copy",
       "state kept in a single file only (no redundant copy); "
       "deleting that file loses every acknowledged job",
       ["test_recovery.py::test_delete_any_single_file_preserves_jobs"],
       lambda s: sub_once(
           sub_once(
               s,
               'def load_state(dirpath):\n'
               '    jobs = _load_snapshot(os.path.join(dirpath, "snapshot.json"))\n'
               '    jobs.update(_load_wal(os.path.join(dirpath, "wal.log")))\n'
               '    return jobs',
               'def load_state(dirpath):\n'
               '    # BUG: single copy of state; nothing to rebuild from\n'
               '    return _load_snapshot(os.path.join(dirpath, "snapshot.json"))'),
           '            append_ops(dirpath, ops)\n',
           '            # BUG: snapshot is the only durable copy (WAL skipped)\n'))

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
           "             if (j[\"status\"] == \"pending\" and j[\"run_at\"] <= t\n"
           "                 and _deps_satisfied(jobs, j, t))]",
           "    cands = [j for j in jobs.values()\n"
           "             if j[\"status\"] == \"pending\"]  # BUG: run_at ignored"))

# 8. compact drops every non-pending job instead of preserving all jobs
mutant("m08_compact",
       "compact keeps only pending jobs (done/dead/claimed silently dropped)",
       ["test_recovery.py::test_compact_reclaims_disk_space"],
       lambda s: sub_once(
           s,
           '        if ctx.get("compact"):\n'
           '            write_snapshot(dirpath, jobs, idem, schedules, meta)\n'
           '            truncate_wal(dirpath)',
           '        if ctx.get("compact"):\n'
           '            # BUG: compact archives away non-pending jobs\n'
           '            write_snapshot(dirpath, {jid: j\n'
           '                                     for jid, j in jobs.items()\n'
           '                                     if j["status"] == "pending"},\n'
           '                             idem, {}, meta)\n'
           '            truncate_wal(dirpath)'))


# 9. no inter-process locking: concurrent claims can double-deliver
mutant("m09_nolock",
       "lock file opened but never locked; concurrent mutations race",
       ["test_concurrency.py::test_parallel_claim_no_double_delivery"],
       lambda s: replace_function(
           s, "_acquire_lock",
           "def _acquire_lock(dirpath):\n"
           "    os.makedirs(dirpath, exist_ok=True)\n"
           "    # BUG: lock file opened but never locked\n"
           "    return open(os.path.join(dirpath, \".lock\"), \"a\")\n\n"))

# 10. torn WAL tails never repaired: a partial write crashes the next command
mutant("m10_no_torn_repair",
       "_truncate_torn_tail neutered; a torn trailing record is replayed "
       "and crashes the next command instead of being discarded",
       ["test_recovery.py::test_torn_append_recovers"],
       lambda s: replace_function(
           s, "_truncate_torn_tail",
           "def _truncate_torn_tail(path):\n"
           "    return False  # BUG: torn tails never repaired\n\n"))

# 11. dead-lettering disabled: fail() always requeues, never marks dead
mutant("m11_no_dead_letter",
       "fail() never sets status dead; jobs retry forever",
       ["test_retries.py::test_fail_dead_after_max_attempts"],
       lambda s: sub_once(
           s,
           "    if job[\"attempts\"] >= job[\"max_attempts\"]:\n"
           "        job[\"status\"] = \"dead\"\n"
           "    else:",
           "    if False:  # BUG: dead-lettering disabled\n"
           "        job[\"status\"] = \"dead\"\n"
           "    else:"))


# 12. cron validation disabled: malformed expressions are accepted
mutant("m12_cron",
       "cron field validation disabled; malformed expressions accepted",
       ["test_schedules.py::test_schedule_malformed_cron_rejected"],
       lambda s: replace_function(
           s, "_parse_cron_field",
           "def _parse_cron_field(text, lo, hi, name):\n"
           "    return set(range(lo, hi + 1)), False  # BUG: no validation\n\n"))


# 13. TTL sweep disabled: expired jobs never die
mutant("m13_ttl",
       "TTL sweep disabled; jobs past their TTL never expire",
       ["test_ttl.py::test_ttl_pending_job_expires"],
       lambda s: replace_function(
           s, "sweep_ttl",
           "def sweep_ttl(jobs, t):\n"
           "    return []  # BUG: TTLs never expire\n\n"))


# 14. extend-lease validates but never updates the lease
mutant("m14_extend",
       "extend-lease validates but never updates lease_expires_at",
       ["test_lease.py::test_extend_lease_prolongs_claim"],
       lambda s: sub_once(
           s,
           "    if args.lease <= 0:\n"
           "        die(\"lease must be > 0\", 2)\n"
           "    job[\"lease_expires_at\"] = t + args.lease\n"
           "    dirty.add(job[\"id\"])\n"
           "    # Keep any idempotency mapping coherent with the new lease so a retry",
           "    if args.lease <= 0:\n"
           "        die(\"lease must be > 0\", 2)\n"
           "    pass  # BUG: lease never extended\n"
           "    dirty.add(job[\"id\"])\n"
           "    # Keep any idempotency mapping coherent with the new lease so a retry"))


# 15. claim never increments the fence token: stale-fence protection can never fire
mutant("m15_fence",
       "claim never increments the fence token (stays 0); stale-fence "
       "protection can never fire",
       ["test_fencing.py::test_fence_starts_zero_bumps_on_claim",
        "test_fencing.py::test_complete_stale_fence_rejected"],
       lambda s: sub_once(
           s,
           "        job[\"fence\"] = job.get(\"fence\", 0) + 1",
           "        pass  # BUG: fence never incremented"))


# 16. schedule ignores --tz: cron always evaluated in UTC
mutant("m16_tz",
       "schedule ignores --tz; cron is always evaluated in UTC",
       ["test_tz.py::test_tz_new_york_materializes_local_wallclock"],
       lambda s: sub_once(
           s,
           "        tz = _get_zone(sched.get(\"tz\", \"UTC\"))",
           "        tz = _get_zone(\"UTC\")  # BUG: --tz ignored"))


# 17. batch claim ignores priority: only the multi-claim path is wrong
mutant("m17_batch_claim",
       "claim --count N orders by created_at only, ignoring priority "
       "(single-claim path unaffected)",
       ["test_claim_batch.py::test_claim_count_three_priority_order"],
       lambda s: sub_once(
           s,
           "    cands.sort(key=lambda j: (-j[\"priority\"], j[\"created_at\"], j[\"id\"]))",
           "    if count == 1:\n"
           "        cands.sort(key=lambda j: (-j[\"priority\"], j[\"created_at\"], j[\"id\"]))\n"
           "    else:\n"
           "        cands.sort(key=lambda j: (j[\"created_at\"], j[\"id\"]))  # BUG: batch claim ignores priority"))


# 18. claim ignores depends_on (claims blocked jobs)
mutant("m18_deps",
       "claim ignores depends_on (claims blocked jobs)",
       ["test_deps.py::test_blocked_until_dependency_done"],
       lambda s: sub_once(
           s,
           "    cands = [j for j in jobs.values()\n"
           "             if (j[\"status\"] == \"pending\" and j[\"run_at\"] <= t\n"
           "                 and _deps_satisfied(jobs, j, t))]",
           "    cands = [j for j in jobs.values()\n"
           "             if j[\"status\"] == \"pending\" and j[\"run_at\"] <= t]  # BUG: depends_on ignored"))


# 19. pause flag not persisted (only in-memory / not loaded)
mutant("m19_pause",
       "pause flag not persisted (only in-memory / not loaded)",
       ["test_pause.py::test_pause_survives_new_process"],
       lambda s: replace_function(
           s, "load_meta",
           "def load_meta(dirpath):\n"
           "    return {\"paused\": False}  # BUG: pause never loaded from disk\n\n"))


# 20. --cascade only cancels direct dependents, not transitive
mutant("m20_cascade",
       "--cascade only cancels direct dependents, not transitive",
       ["test_cancel.py::test_cascade_cancels_transitive_pending"],
       lambda s: replace_function(
           s, "_transitive_pending_dependents",
           "def _transitive_pending_dependents(jobs, root_id):\n"
           "    # BUG: only direct dependents, not transitive\n"
           "    out = []\n"
           "    for job in jobs.values():\n"
           "        if job[\"status\"] != \"pending\":\n"
           "            continue\n"
           "        if root_id in (job.get(\"depends_on\") or []):\n"
           "            out.append(job[\"id\"])\n"
           "    return out\n\n"))


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
