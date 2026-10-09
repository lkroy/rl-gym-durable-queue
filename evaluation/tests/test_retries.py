"""Fail/retry semantics: backoff, dead-lettering, state conflicts."""
import time


def test_fail_backoff_requeue(q):
    q.run("enqueue", "--payload", "{}", "--id", "r1", "--max-attempts", "2")
    q.json("claim")
    before = time.time()
    cp = q.run("fail", "r1", "--error", "boom")
    assert cp.returncode == 0
    assert cp.stdout.strip() == "r1"
    job = q.json("show", "r1")
    assert job["status"] == "pending"
    assert job["attempts"] == 1
    assert job["last_error"] == "boom"
    assert job["claimed_at"] is None
    assert job["lease_expires_at"] is None
    delta = job["run_at"] - before
    assert 5 < delta < 60, "backoff out of range: %r" % delta
    cp = q.run("claim")
    assert cp.returncode == 1  # requeued with backoff: not yet runnable


def test_fail_dead_after_max_attempts(q):
    q.run("enqueue", "--payload", "{}", "--id", "d1", "--max-attempts", "1")
    q.json("claim")
    cp = q.run("fail", "d1", "--error", "fatal")
    assert cp.returncode == 0
    job = q.json("show", "d1")
    assert job["status"] == "dead"
    assert job["attempts"] == 1
    cp = q.run("claim")
    assert cp.returncode == 1  # dead jobs are never claimable


def test_fail_pending_conflict(q):
    q.run("enqueue", "--payload", "{}", "--id", "p1")
    cp = q.run("fail", "p1")
    assert cp.returncode == 3
    assert "not claimed" in cp.stderr
