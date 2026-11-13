"""Cancel and cascade cancel; interaction with dependency failure."""
import json


def test_cancel_pending_to_dead_cancelled(q):
    q.run("enqueue", "--payload", "{}", "--id", "c1")
    cp = q.run("cancel", "c1")
    assert cp.returncode == 0
    assert cp.stdout.strip() == "c1"
    job = q.json("show", "c1")
    assert job["status"] == "dead"
    assert job["last_error"] == "cancelled"


def test_cancel_claimed_not_pending(q):
    q.run("enqueue", "--payload", "{}", "--id", "c2")
    q.json("claim")
    cp = q.run("cancel", "c2")
    assert cp.returncode == 3
    assert "not pending" in cp.stderr
    assert q.json("show", "c2")["status"] == "claimed"
    cp = q.run("cancel", "missing")
    assert cp.returncode == 4


def test_cascade_cancels_transitive_pending(q):
    q.run("enqueue", "--payload", "{}", "--id", "r")
    q.run("enqueue", "--payload", "{}", "--id", "m", "--depends-on", "r")
    q.run("enqueue", "--payload", "{}", "--id", "l", "--depends-on", "m")
    q.run("enqueue", "--payload", "{}", "--id", "other")
    cp = q.run("cancel", "r", "--cascade")
    assert cp.returncode == 0, cp.stderr
    cancelled = json.loads(cp.stdout)
    assert cancelled == sorted(cancelled)
    assert cancelled == ["l", "m", "r"]
    for jid in ("r", "m", "l"):
        job = q.json("show", jid)
        assert job["status"] == "dead"
        assert job["last_error"] == "cancelled"
    assert q.json("show", "other")["status"] == "pending"


def test_without_cascade_dependent_becomes_dependency_failed(q):
    q.run("enqueue", "--payload", "{}", "--id", "root")
    q.run("enqueue", "--payload", "{}", "--id", "child",
          "--depends-on", "root")
    cp = q.run("cancel", "root")
    assert cp.returncode == 0
    assert cp.stdout.strip() == "root"
    # child still pending until next pre-step
    # (cancel itself does not cascade without --cascade; the next command
    # runs the dep-failure sweep)
    child = q.json("show", "child")
    assert child["status"] == "dead"
    assert child["last_error"] == "dependency failed"
    assert q.json("show", "root")["last_error"] == "cancelled"
