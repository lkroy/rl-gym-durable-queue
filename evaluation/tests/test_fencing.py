"""Fencing tokens: stale-holding-worker protection on complete/fail/extend-lease."""
import time


def test_fence_starts_zero_bumps_on_claim(q):
    q.run("enqueue", "--payload", "{}", "--id", "f1")
    assert q.json("show", "f1")["fence"] == 0
    job = q.json("claim")
    assert job["id"] == "f1"
    assert job["fence"] == 1
    assert q.json("show", "f1")["fence"] == 1


def test_complete_stale_fence_rejected(q):
    q.run("enqueue", "--payload", "{}", "--id", "f2")
    first = q.json("claim", "--lease", "1")
    assert first["fence"] == 1
    time.sleep(1.6)  # lease expires; sweep returns job to pending
    second = q.json("claim")
    assert second["id"] == "f2"
    assert second["fence"] == 2
    # the old holder's fence is stale now
    cp = q.run("complete", "f2", "--fence", "1")
    assert cp.returncode == 3
    assert "stale fence" in cp.stderr
    assert q.json("show", "f2")["status"] == "claimed"
    # the current holder completes fine
    cp = q.run("complete", "f2", "--fence", "2")
    assert cp.returncode == 0, cp.stderr


def test_extend_lease_stale_fence_rejected(q):
    q.run("enqueue", "--payload", "{}", "--id", "f3")
    first = q.json("claim", "--lease", "1")
    assert first["fence"] == 1
    time.sleep(1.6)
    second = q.json("claim")
    assert second["fence"] == 2
    cp = q.run("extend-lease", "f3", "--fence", "1", "--lease", "60")
    assert cp.returncode == 3
    assert "stale fence" in cp.stderr
    cp = q.run("extend-lease", "f3", "--fence", "2", "--lease", "60")
    assert cp.returncode == 0, cp.stderr
    # extend-lease does NOT change the fence
    assert q.json("show", "f3")["fence"] == 2


def test_complete_missing_fence_rejected(q):
    q.run("enqueue", "--payload", "{}", "--id", "f4")
    q.json("claim")
    cp = q.run("complete", "f4")
    assert cp.returncode == 2
    cp = q.run("complete", "f4", "--fence", "-1")
    assert cp.returncode == 2
    cp = q.run("complete", "f4", "--fence", "abc")
    assert cp.returncode == 2
    assert q.json("show", "f4")["status"] == "claimed"


def test_fail_stale_fence_rejected(q):
    q.run("enqueue", "--payload", "{}", "--id", "f5", "--max-attempts", "3")
    first = q.json("claim", "--lease", "1")
    assert first["fence"] == 1
    time.sleep(1.6)
    second = q.json("claim")
    assert second["fence"] == 2
    cp = q.run("fail", "f5", "--fence", "1", "--error", "x")
    assert cp.returncode == 3
    assert "stale fence" in cp.stderr
    job = q.json("show", "f5")
    assert job["status"] == "claimed"
    assert job["attempts"] == 0
    cp = q.run("fail", "f5", "--fence", "2", "--error", "x")
    assert cp.returncode == 0, cp.stderr


def test_idempotent_reclaim_keeps_fence(q):
    q.run("enqueue", "--payload", "{}", "--id", "f6")
    first = q.json("claim", "--idempotency-key", "FK")
    assert first["fence"] == 1
    second = q.json("claim", "--idempotency-key", "FK")
    assert second["id"] == first["id"]
    assert second["fence"] == 1


def test_fence_bumps_on_fail_requeue(q):
    # fail does not reset the fence; the bump happens on the next claim
    q.run("enqueue", "--payload", "{}", "--id", "g1", "--max-attempts", "2")
    job = q.json("claim")
    assert job["fence"] == 1
    cp = q.run("fail", "g1", "--fence", "1", "--error", "x")
    assert cp.returncode == 0, cp.stderr
    job = q.json("show", "g1")
    assert job["status"] == "pending"
    assert job["fence"] == 1
