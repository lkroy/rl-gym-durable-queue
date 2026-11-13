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
