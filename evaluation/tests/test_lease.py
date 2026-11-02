"""Lease expiry: sweep returns expired claims to pending."""
import time


def test_lease_expiry_reclaim(q):
    q.run("enqueue", "--payload", "{}", "--id", "l1")
    assert q.json("claim", "--lease", "1")["id"] == "l1"
    time.sleep(1.6)
    job = q.json("claim")
    assert job["id"] == "l1"
    assert job["status"] == "claimed"


def test_complete_after_lease_expiry_fails(q):
    q.run("enqueue", "--payload", "{}", "--id", "l2")
    q.json("claim", "--lease", "1")
    time.sleep(1.6)
    cp = q.run("complete", "l2", "--fence", "0")
    assert cp.returncode == 3
    assert "not claimed" in cp.stderr


def test_extend_lease_prolongs_claim(q):
    q.run("enqueue", "--payload", "{}", "--id", "x1")
    job = q.json("claim", "--lease", "1")
    cp = q.run("extend-lease", "x1", "--fence", str(job["fence"]),
               "--lease", "60")
    assert cp.returncode == 0, cp.stderr
    assert cp.stdout.strip() == "x1"
    time.sleep(1.2)
    job = q.json("show", "x1")
    assert job["status"] == "claimed", job


def test_extend_lease_pending_conflict(q):
    q.run("enqueue", "--payload", "{}", "--id", "x2")
    cp = q.run("extend-lease", "x2", "--fence", "0", "--lease", "60")
    assert cp.returncode == 3
    assert "not claimed" in cp.stderr


def test_extend_lease_unknown_id(q):
    cp = q.run("extend-lease", "nope", "--fence", "0", "--lease", "60")
    assert cp.returncode == 4


def test_extend_lease_bad_lease(q):
    q.run("enqueue", "--payload", "{}", "--id", "x3")
    job = q.json("claim", "--lease", "60")
    for bad in ["0", "-5"]:
        cp = q.run("extend-lease", "x3", "--fence", str(job["fence"]),
                   "--lease", bad)
        assert cp.returncode == 2, bad
