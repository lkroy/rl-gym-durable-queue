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


def test_cascade_does_not_affect_unrelated_pending(q):
    """Cascade cancel of a root must not cancel/change an unrelated job."""
    q.run("enqueue", "--payload", '{"k":1}', "--id", "root",
          "--priority", "5")
    q.run("enqueue", "--payload", "{}", "--id", "dep", "--depends-on", "root")
    q.run("enqueue", "--payload", '{"k":2}', "--id", "unrelated",
          "--priority", "3")
    before = q.json("show", "unrelated")
    cp = q.run("cancel", "root", "--cascade")
    assert cp.returncode == 0, cp.stderr
    cancelled = json.loads(cp.stdout)
    assert "unrelated" not in cancelled
    assert set(cancelled) == {"root", "dep"}
    after = q.json("show", "unrelated")
    assert after["status"] == "pending"
    assert after["payload"] == before["payload"]
    assert after["priority"] == before["priority"]
    assert after["depends_on"] == []
    job = q.json("claim")
    assert job["id"] == "unrelated"


def test_cancel_branch_does_not_kill_sibling(q):
    """Cancelling one branch must not kill a sibling that does not depend on it."""
    q.run("enqueue", "--payload", "{}", "--id", "shared")
    q.run("enqueue", "--payload", "{}", "--id", "left",
          "--depends-on", "shared")
    q.run("enqueue", "--payload", "{}", "--id", "right",
          "--depends-on", "shared")
    q.run("enqueue", "--payload", "{}", "--id", "left_leaf",
          "--depends-on", "left")
    cp = q.run("cancel", "left", "--cascade")
    assert cp.returncode == 0, cp.stderr
    cancelled = json.loads(cp.stdout)
    assert set(cancelled) == {"left", "left_leaf"}
    assert "right" not in cancelled
    assert "shared" not in cancelled
    assert q.json("show", "right")["status"] == "pending"
    assert q.json("show", "shared")["status"] == "pending"
    # Complete shared; sibling right must become claimable.
    shared = q.json("claim")
    assert shared["id"] == "shared"
    q.run("complete", "shared", "--fence", str(shared["fence"]))
    right = q.json("claim")
    assert right["id"] == "right"
