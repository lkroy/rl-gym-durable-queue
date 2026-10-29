"""Idempotent claim: `q claim --idempotency-key KEY`.

The key->job mapping must be durable and concurrency-safe: two claims with
the same key return the same job without claiming twice; the mapping is
discarded on lease expiry and when the job goes done/dead; an invalid key
format is a usage error.
"""
import json
import os
import subprocess
import time


def test_idempotency_key_returns_same_job(q):
    q.run("enqueue", "--payload", "{}", "--id", "i1")
    q.run("enqueue", "--payload", "{}", "--id", "i2")
    first = q.json("claim", "--idempotency-key", "K1")
    second = q.json("claim", "--idempotency-key", "K1")
    assert first["id"] == "i1"
    assert second["id"] == "i1", "same key claimed a different job"
    # only one job was actually claimed
    assert q.json("stats")["claimed"] == 1


def test_idempotency_key_discarded_after_lease_expiry(q):
    q.run("enqueue", "--payload", "{}", "--id", "e1")
    q.run("enqueue", "--payload", "{}", "--id", "e2")
    first = q.json("claim", "--lease", "1", "--idempotency-key", "K2")
    assert first["id"] == "e1"
    time.sleep(1.2)  # margin over the 1s lease
    # e1's lease expired: swept back to pending, mapping K2 discarded.
    # Claim e1 plainly so the next keyed claim must pick a different job.
    again = q.json("claim")
    assert again["id"] == "e1"
    third = q.json("claim", "--idempotency-key", "K2")
    assert third["id"] == "e2", \
        "expired mapping was not discarded (got %s)" % third["id"]


def test_idempotency_key_discarded_after_complete(q):
    q.run("enqueue", "--payload", "{}", "--id", "d1")
    q.run("enqueue", "--payload", "{}", "--id", "d2")
    first = q.json("claim", "--idempotency-key", "K3")
    assert first["id"] == "d1"
    cp = q.run("complete", "d1")
    assert cp.returncode == 0, cp.stderr
    # d1 is done: the mapping is discarded, so the key starts fresh...
    second = q.json("claim", "--idempotency-key", "K3")
    assert second["id"] == "d2"
    # ...and the fresh mapping is itself idempotent.
    third = q.json("claim", "--idempotency-key", "K3")
    assert third["id"] == "d2"
    assert q.json("stats")["claimed"] == 1


def test_idempotency_keys_are_independent(q):
    q.run("enqueue", "--payload", "{}", "--id", "n1")
    q.run("enqueue", "--payload", "{}", "--id", "n2")
    a = q.json("claim", "--idempotency-key", "KA")
    b = q.json("claim", "--idempotency-key", "KB")
    assert {a["id"], b["id"]} == {"n1", "n2"}


def test_idempotency_key_invalid_format(q):
    q.run("enqueue", "--payload", "{}", "--id", "v1")
    cp = q.run("claim", "--idempotency-key", "bad key!")
    assert cp.returncode == 2, "expected exit 2, got %d" % cp.returncode
    assert cp.stderr.strip(), "expected a stderr message"


def test_idempotency_key_concurrent_same_job(q):
    q.run("enqueue", "--payload", "{}", "--id", "only")
    env = dict(os.environ, QDATA_DIR=q.qdata)
    procs = [subprocess.Popen([q.q_bin, "claim", "--idempotency-key", "KC"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, env=env)
             for _ in range(4)]
    ids = []
    for p in procs:
        out, err = p.communicate(timeout=60)
        assert p.returncode == 0, \
            "concurrent keyed claim failed: rc=%d stderr=%r" % (
                p.returncode, err)
        ids.append(json.loads(out)["id"])
    assert ids == ["only"] * 4, \
        "concurrent claims with the same key diverged: %r" % ids
    assert q.json("stats")["claimed"] == 1
