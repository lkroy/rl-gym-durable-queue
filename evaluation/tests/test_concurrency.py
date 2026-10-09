"""Concurrent claimers must never receive the same job twice."""
import json
import os
import subprocess


def test_parallel_claim_no_double_delivery(q):
    for i in range(5):
        q.run("enqueue", "--payload", "{}", "--id", "c%d" % i)
    env = dict(os.environ, QDATA_DIR=q.qdata)
    procs = [subprocess.Popen([q.q_bin, "claim"], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, env=env)
             for _ in range(8)]
    claimed_ids = []
    empty_exits = 0
    for p in procs:
        out, _ = p.communicate(timeout=60)
        if p.returncode == 0:
            claimed_ids.append(json.loads(out)["id"])
        elif p.returncode == 1:
            empty_exits += 1
        else:
            raise AssertionError("unexpected claim rc=%d" % p.returncode)
    assert len(claimed_ids) == 5
    assert len(set(claimed_ids)) == 5  # no double delivery
    assert empty_exits == 3
