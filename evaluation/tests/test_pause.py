"""Pause / resume: claim blocked, flag durable across process restarts."""


def test_claim_rejected_while_paused(q):
    q.run("enqueue", "--payload", "{}", "--id", "p1")
    cp = q.run("pause")
    assert cp.returncode == 0
    assert cp.stdout.strip() == "paused"
    cp = q.run("claim")
    assert cp.returncode == 1
    assert "queue paused" in cp.stderr
    assert q.json("show", "p1")["status"] == "pending"


def test_pause_survives_new_process(q):
    q.run("enqueue", "--payload", "{}", "--id", "p2")
    assert q.run("pause").returncode == 0
    # Fresh process (new q invocation via fixture helper) must still see pause.
    cp = q.run("claim")
    assert cp.returncode == 1
    assert "queue paused" in cp.stderr
    # Idempotent pause
    cp = q.run("pause")
    assert cp.returncode == 0
    assert cp.stdout.strip() == "paused"


def test_enqueue_while_paused_then_resume_claim(q):
    assert q.run("pause").stdout.strip() == "paused"
    cp = q.run("enqueue", "--payload", '{"x":1}', "--id", "p3")
    assert cp.returncode == 0
    assert cp.stdout.strip() == "p3"
    assert q.json("show", "p3")["status"] == "pending"
    cp = q.run("claim")
    assert cp.returncode == 1
    assert "queue paused" in cp.stderr
    cp = q.run("resume")
    assert cp.returncode == 0
    assert cp.stdout.strip() == "resumed"
    job = q.json("claim")
    assert job["id"] == "p3"


def test_resume_then_claim_succeeds(q):
    q.run("enqueue", "--payload", "{}", "--id", "p4")
    q.run("pause")
    q.run("resume")
    # Idempotent resume
    assert q.run("resume").stdout.strip() == "resumed"
    job = q.json("claim")
    assert job["id"] == "p4"
    assert job["status"] == "claimed"
