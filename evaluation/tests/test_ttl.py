"""TTL expiry: pending jobs die, claimed jobs are exempt while leased."""
import time


def test_ttl_pending_job_expires(q):
    q.run("enqueue", "--payload", "{}", "--id", "t1", "--ttl", "1")
    time.sleep(1.2)
    job = q.json("show", "t1")
    assert job["status"] == "dead", job
    assert job["last_error"] == "expired", job


def test_ttl_claimed_job_exempt_while_lease_valid(q):
    q.run("enqueue", "--payload", "{}", "--id", "t2", "--ttl", "1")
    q.json("claim", "--lease", "60")
    time.sleep(1.2)
    job = q.json("show", "t2")
    assert job["status"] == "claimed", job


def test_ttl_claimed_job_dead_after_lease_expiry(q):
    q.run("enqueue", "--payload", "{}", "--id", "t3", "--ttl", "1")
    q.json("claim", "--lease", "1")
    time.sleep(1.6)
    job = q.json("show", "t3")
    assert job["status"] == "dead", job
    assert job["last_error"] == "expired", job


def test_ttl_delayed_job_expires_before_claimable(q):
    q.run("enqueue", "--payload", "{}", "--id", "t4",
          "--delay", "10", "--ttl", "1")
    time.sleep(1.2)
    job = q.json("show", "t4")
    assert job["status"] == "dead", job


def test_ttl_nonpositive_rejected(q):
    for bad in ["0", "-1", "-0.5"]:
        cp = q.run("enqueue", "--payload", "{}", "--ttl", bad)
        assert cp.returncode == 2, bad
