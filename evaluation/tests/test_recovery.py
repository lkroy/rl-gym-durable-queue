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
    for i in range(5):
        cp = q.run("enqueue", "--payload", _payload(i),
                   "--id", "base-%d" % i)
        assert cp.returncode == 0, cp.stderr
    prev = 5
    rng = random.Random(20261009)
    for trial in range(40):
        p = _spawn(q, "enqueue", "--payload", _payload(trial),
                   "--id", "k-%d" % trial)
        time.sleep(rng.uniform(0.0005, 0.004))
        p.kill()  # SIGKILL
        p.wait()
        cp = q.run("stats")
        assert cp.returncode == 0, \
            "queue unusable after SIGKILL mid-enqueue (trial %d): %r" % (
                trial, cp.stderr)
        total = json.loads(cp.stdout)["total"]
        assert total in (prev, prev + 1), \
            "acknowledged jobs lost or duplicated: %d -> %d" % (prev, total)
        prev = total
    ids = {r["id"] for r in q.json("list")}
    assert {"base-%d" % i for i in range(5)} <= ids


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
    files = sorted(
        f for f in os.listdir(q.qdata)
        if os.path.isfile(os.path.join(q.qdata, f)))
    assert files, "expected state files under $QDATA_DIR"
    for victim in files:
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
