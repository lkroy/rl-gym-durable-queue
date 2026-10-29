"""Crash recovery, stated without prescribing any storage design.

Fault model (all deterministic in their assertions):
- SIGKILL at random points mid-command: the next command must exit 0, every
  previously acknowledged job stays intact, the in-flight op took effect at
  most once (never partially, never duplicated).
- Deleting any single file under $QDATA_DIR while idle: no acknowledged
  job may be lost.
- SIGKILL mid-compact: no job lost, queue stays operational.
- compact must actually reclaim disk space once state has grown.
"""
import json
import os
import random
import shutil
import subprocess
import time

BLOB = "x" * 100000  # large enough to widen the disk-write window,
# small enough to stay under the OS per-argument length limit


def _dir_bytes(qdata):
    total = 0
    for root, _dirs, files in os.walk(qdata):
        for f in files:
            total += os.path.getsize(os.path.join(root, f))
    return total


def _spawn(q, *args):
    env = dict(os.environ)
    env["QDATA_DIR"] = q.qdata
    return subprocess.Popen(
        [q.q_bin, *args], env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _payload(i):
    return json.dumps({"blob": BLOB, "i": i})


def test_kill_mid_enqueue_never_corrupts(q):
    # 25 base jobs with large payloads so every later write phase is long.
    for i in range(25):
        cp = q.run("enqueue", "--payload", _payload(i),
                   "--id", "base-%d" % i)
        assert cp.returncode == 0, cp.stderr
    prev = 25
    for trial in range(25):
        # Staggered burst: 4 enqueues launched 5ms apart widen the window in
        # which a SIGKILL lands mid-write; kill every survivor afterwards.
        procs = []
        for k in range(4):
            procs.append(_spawn(q, "enqueue",
                                "--payload", _payload(1000 + trial * 4 + k),
                                "--id", "k%d-%d" % (trial, k)))
            time.sleep(0.005)
        time.sleep(0.003)
        for p in procs:
            if p.poll() is None:  # skip processes that already exited
                p.kill()  # SIGKILL
        for p in procs:
            p.wait()
        cp = q.run("stats")
        assert cp.returncode == 0, \
            "queue unusable after SIGKILL mid-enqueue (trial %d): %r" % (
                trial, cp.stderr)
        total = json.loads(cp.stdout)["total"]
        assert prev <= total <= prev + 4, \
            "acknowledged jobs lost or duplicated: %d -> %d" % (prev, total)
        prev = total
    ids = {r["id"] for r in q.json("list")}
    assert {"base-%d" % i for i in range(25)} <= ids


def test_torn_append_recovers(q):
    # A crash can cut a write at any byte. For EVERY regular file under
    # $QDATA_DIR (layout-agnostic via os.walk): copy the state dir, append a
    # partial trailing record with no terminating newline to that file's
    # copy, and require the next command to exit 0 with every acknowledged
    # job intact.
    for i in range(5):
        cp = q.run("enqueue", "--payload", json.dumps({"n": i}),
                   "--id", "t-%d" % i)
        assert cp.returncode == 0, cp.stderr
    want = {"t-%d" % i for i in range(5)}
    targets = []
    for root, _dirs, files in os.walk(q.qdata):
        for f in files:
            p = os.path.join(root, f)
            if os.path.isfile(p) and not os.path.islink(p):
                targets.append(os.path.relpath(p, q.qdata))
    assert targets, "expected state files under $QDATA_DIR"
    for rel in targets:
        alt = q.qdata + "-torn"
        shutil.rmtree(alt, ignore_errors=True)
        shutil.copytree(q.qdata, alt)
        with open(os.path.join(alt, rel), "ab") as fh:
            fh.write(b'\n{"partial_write": true')  # torn: no newline
        env = dict(os.environ, QDATA_DIR=alt)
        cp = subprocess.run([q.q_bin, "list"], capture_output=True,
                            text=True, env=env, timeout=60)
        assert cp.returncode == 0, \
            "q list failed after torn append to %s: %r" % (rel, cp.stderr)
        rows = json.loads(cp.stdout)
        assert {r["id"] for r in rows} == want, \
            "acknowledged jobs lost after torn append to %s" % rel
        shutil.rmtree(alt, ignore_errors=True)


def test_kill_mid_compact_never_loses_jobs(q):
    for i in range(10):
        cp = q.run("enqueue", "--payload", _payload(i),
                   "--id", "c-%d" % i)
        assert cp.returncode == 0, cp.stderr
    want = {"c-%d" % i for i in range(10)}
    rng = random.Random(7700311)
    for trial in range(15):
        p = _spawn(q, "compact")
        time.sleep(rng.uniform(0.0005, 0.003))
        p.kill()  # SIGKILL
        p.wait()
        rows = q.json("list")
        assert {r["id"] for r in rows} == want, \
            "jobs lost after SIGKILL mid-compact (trial %d)" % trial
    cp = q.run("compact")
    assert cp.returncode == 0 and cp.stdout.strip() == "ok"


def test_delete_any_single_file_preserves_jobs(q):
    for i in range(3):
        cp = q.run("enqueue", "--payload", json.dumps({"n": i}),
                   "--id", "d-%d" % i)
        assert cp.returncode == 0, cp.stderr
    victims = []
    for root, _dirs, files in os.walk(q.qdata):
        for f in files:
            p = os.path.join(root, f)
            if os.path.isfile(p) and not os.path.islink(p):
                victims.append(os.path.relpath(p, q.qdata))
    victims = sorted(victims)
    assert victims, "expected state files under $QDATA_DIR"
    for victim in victims:
        alt = q.qdata + "-copy"
        shutil.rmtree(alt, ignore_errors=True)
        shutil.copytree(q.qdata, alt)
        os.remove(os.path.join(alt, victim))
        env = dict(os.environ)
        env["QDATA_DIR"] = alt
        cp = subprocess.run([q.q_bin, "list"], capture_output=True,
                            text=True, env=env, timeout=60)
        assert cp.returncode == 0, \
            "queue unusable after deleting %s: %r" % (victim, cp.stderr)
        rows = json.loads(cp.stdout)
        assert {r["id"] for r in rows} == {"d-0", "d-1", "d-2"}, \
            "acknowledged jobs lost after deleting %s" % victim
        shutil.rmtree(alt, ignore_errors=True)


def test_compact_reclaims_disk_space(q):
    for i in range(40):
        cp = q.run("enqueue", "--payload", _payload(i),
                   "--id", "s-%d" % i)
        assert cp.returncode == 0, cp.stderr
    # churn: claim/complete/fail so the redundant storage grows
    for _ in range(10):
        job = q.json("claim")
        cp = q.run("complete", job["id"])
        assert cp.returncode == 0, cp.stderr
    for _ in range(5):
        job = q.json("claim")
        cp = q.run("fail", job["id"], "--error", "boom")
        assert cp.returncode == 0, cp.stderr
    before = _dir_bytes(q.qdata)
    cp = q.run("compact")
    assert cp.returncode == 0, cp.stderr
    assert cp.stdout.strip() == "ok"
    after = _dir_bytes(q.qdata)
    assert after < before, \
        "compact did not reclaim disk space: %d -> %d" % (before, after)
    rows = q.json("list")
    assert len(rows) == 40
    by_id = {r["id"]: r for r in rows}
    assert by_id["s-0"]["status"] == "done"
    assert by_id["s-10"]["status"] == "pending"  # failed once -> backoff
    assert q.json("stats")["total"] == 40  # still fully operational
