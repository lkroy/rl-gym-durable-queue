"""Batch claim: `q claim --count N`."""
import json
import os
import subprocess


def test_claim_count_three_priority_order(q):
    q.run("enqueue", "--payload", "{}", "--id", "b1", "--priority", "1")
    q.run("enqueue", "--payload", "{}", "--id", "b2", "--priority", "5")
    q.run("enqueue", "--payload", "{}", "--id", "b3", "--priority", "3")
    cp = q.run("claim", "--count", "3")
    assert cp.returncode == 0, cp.stderr
    jobs = json.loads(cp.stdout)
    assert isinstance(jobs, list)
    assert [j["id"] for j in jobs] == ["b2", "b3", "b1"]
    assert [j["fence"] for j in jobs] == [1, 1, 1]
    assert all(j["status"] == "claimed" for j in jobs)


def test_claim_count_more_than_available(q):
    q.run("enqueue", "--payload", "{}", "--id", "c1")
    q.run("enqueue", "--payload", "{}", "--id", "c2")
    cp = q.run("claim", "--count", "10")
    assert cp.returncode == 0, cp.stderr
    jobs = json.loads(cp.stdout)
    assert [j["id"] for j in jobs] == ["c1", "c2"]


def test_claim_count_empty(q):
    cp = q.run("claim", "--count", "3")
    assert cp.returncode == 1
    assert "no jobs available" in cp.stderr


def test_claim_count_invalid(q):
    q.run("enqueue", "--payload", "{}", "--id", "d1")
    for bad in ["0", "-2", "abc", "2.5"]:
        cp = q.run("claim", "--count", bad)
        assert cp.returncode == 2, bad


def test_claim_count_with_idempotency_key_rejected(q):
    q.run("enqueue", "--payload", "{}", "--id", "e1")
    cp = q.run("claim", "--count", "2", "--idempotency-key", "K")
    assert cp.returncode == 2


def test_parallel_claim_count_no_double_delivery(q):
    for i in range(6):
        q.run("enqueue", "--payload", "{}", "--id", "p%d" % i)
    env = dict(os.environ, QDATA_DIR=q.qdata)
    procs = [subprocess.Popen([q.q_bin, "claim", "--count", "4"],
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE,
                              text=True, env=env)
             for _ in range(3)]
    ids = []
    for p in procs:
        out, err = p.communicate(timeout=60)
        assert p.returncode in (0, 1), (p.returncode, err)
        if p.returncode == 0:
            ids.extend(j["id"] for j in json.loads(out))
    assert len(ids) == 6, ids
    assert len(set(ids)) == 6, "double delivery: %s" % ids
