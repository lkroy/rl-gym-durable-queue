"""Concurrent claimers must never receive the same job twice."""
import json
import os
import subprocess


def test_parallel_claim_no_double_delivery(q):
    # Widen the race window deterministically: a large filler state makes
    # every claim's load phase tens of ms long, so parallel claims overlap
    # heavily. Without OS-level locking this reliably double-delivers.
    big = "x" * 100000
    for i in range(20):
        q.run("enqueue", "--payload", json.dumps({"b": big}),
              "--id", "fill-%d" % i, "--delay", "3600")
    env = dict(os.environ, QDATA_DIR=q.qdata)
    for rnd in range(3):
        ids = ["r%d-%d" % (rnd, i) for i in range(5)]
        for jid in ids:
            q.run("enqueue", "--payload", "{}", "--id", jid)
        procs = [subprocess.Popen(
                     [q.q_bin, "claim"],
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                     text=True, env=env)
                 for _ in range(12)]
        claimed, empty = [], 0
        for p in procs:
            out, _ = p.communicate(timeout=60)
            if p.returncode == 0:
                claimed.append(json.loads(out)["id"])
            elif p.returncode == 1:
                empty += 1
            else:
                raise AssertionError("unexpected claim rc=%d" % p.returncode)
        assert len(claimed) == 5, claimed
        assert len(set(claimed)) == 5, "double delivery: %s" % claimed
        assert empty == 7, empty


def test_parallel_enqueue_no_lost_or_duplicate_jobs(q):
    env = dict(os.environ, QDATA_DIR=q.qdata)
    procs = [subprocess.Popen(
                 [q.q_bin, "enqueue", "--payload", "{}",
                  "--id", "p%d" % i],
                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                 text=True, env=env)
             for i in range(8)]
    for p in procs:
        _, err = p.communicate(timeout=60)
        assert p.returncode == 0, err
    ids = [j["id"] for j in q.json("list")]
    assert len(ids) == 8, ids
    assert len(set(ids)) == 8  # nothing lost, nothing duplicated


def test_parallel_mixed_ops_keep_queue_consistent(q):
    for i in range(10):
        q.run("enqueue", "--payload", "{}", "--id", "m%d" % i)
    env = dict(os.environ, QDATA_DIR=q.qdata)

    def worker():
        # claim a job and complete it; stop when none are available
        for _ in range(5):
            c = subprocess.run([q.q_bin, "claim"], capture_output=True,
                               text=True, env=env, timeout=60)
            assert c.returncode in (0, 1), c.stderr
            if c.returncode == 1:
                break
            jid = json.loads(c.stdout)["id"]
            d = subprocess.run([q.q_bin, "complete", jid],
                               capture_output=True, text=True,
                               env=env, timeout=60)
            assert d.returncode == 0, \
                "complete failed for claimed job %s: %s" % (jid, d.stderr)

    # drive the workers via threads to keep this black-box simple
    import threading
    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    stats = q.json("stats")
    assert stats["done"] == 10, stats
    assert stats["pending"] == 0 and stats["claimed"] == 0, stats
    assert stats["total"] == 10, stats
