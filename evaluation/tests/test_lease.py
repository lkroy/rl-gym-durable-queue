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
    cp = q.run("complete", "l2")
    assert cp.returncode == 3
    assert "not claimed" in cp.stderr
