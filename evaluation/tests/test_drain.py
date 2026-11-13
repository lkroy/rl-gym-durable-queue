"""Durable drain mode: blocks enqueue/schedule; claim still works."""
import json


def test_drain_blocks_enqueue(q):
    cp = q.run("drain")
    assert cp.returncode == 0
    assert cp.stdout.strip() == "draining"
    # Idempotent
    assert q.run("drain").stdout.strip() == "draining"
    cp = q.run("enqueue", "--payload", "{}", "--id", "d1")
    assert cp.returncode == 3
    assert "draining" in cp.stderr
    assert q.json("stats")["total"] == 0


def test_drain_blocks_schedule(q):
    q.run("drain")
    cp = q.run("schedule", "--payload", "{}", "--cron", "* * * * *",
               "--id", "sd1")
    assert cp.returncode == 3
    assert "draining" in cp.stderr
    assert q.json("schedules") == []


def test_claim_works_while_draining(q):
    q.run("enqueue", "--payload", "{}", "--id", "c1")
    q.run("drain")
    job = q.json("claim")
    assert job["id"] == "c1"
    assert job["status"] == "claimed"
    cp = q.run("complete", "c1", "--fence", str(job["fence"]))
    assert cp.returncode == 0


def test_resume_clears_drain(q):
    q.run("drain")
    cp = q.run("enqueue", "--payload", "{}", "--id", "r1")
    assert cp.returncode == 3
    cp = q.run("resume")
    assert cp.returncode == 0
    assert cp.stdout.strip() == "resumed"
    cp = q.run("enqueue", "--payload", "{}", "--id", "r1")
    assert cp.returncode == 0
    assert cp.stdout.strip() == "r1"


def test_drain_survives_new_process(q):
    q.run("drain")
    # Fresh process must still see draining.
    cp = q.run("enqueue", "--payload", "{}", "--id", "p1")
    assert cp.returncode == 3
    assert "draining" in cp.stderr


def test_pause_and_drain_claim_uses_pause(q):
    q.run("enqueue", "--payload", "{}", "--id", "pd1")
    q.run("drain")
    q.run("pause")
    cp = q.run("claim")
    assert cp.returncode == 1
    assert "queue paused" in cp.stderr
    assert q.json("show", "pd1")["status"] == "pending"


def test_drain_preserves_enqueued_jobs(q):
    """Drain must not remove or alter already-enqueued jobs; they stay claimable."""
    q.run("enqueue", "--payload", '{"n":1}', "--id", "keep1",
          "--priority", "7")
    q.run("enqueue", "--payload", '{"n":2}', "--id", "keep2",
          "--priority", "3")
    before = {jid: q.json("show", jid) for jid in ("keep1", "keep2")}
    assert q.run("drain").returncode == 0
    for jid, snap in before.items():
        after = q.json("show", jid)
        assert after["status"] == "pending"
        assert after["payload"] == snap["payload"]
        assert after["priority"] == snap["priority"]
        assert after["tag"] == snap["tag"]
        assert after["depends_on"] == snap["depends_on"]
    assert q.json("stats")["pending"] == 2
    assert q.json("stats")["total"] == 2
    first = q.json("claim")
    assert first["id"] == "keep1"
    q.run("complete", "keep1", "--fence", str(first["fence"]))
    second = q.json("claim")
    assert second["id"] == "keep2"
