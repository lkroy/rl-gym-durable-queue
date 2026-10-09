"""Claim ordering: priority, FIFO tiebreak, delayed jobs."""


def test_priority_order(q):
    q.run("enqueue", "--payload", "{}", "--id", "lo", "--priority", "0")
    q.run("enqueue", "--payload", "{}", "--id", "hi", "--priority", "10")
    q.run("enqueue", "--payload", "{}", "--id", "mid", "--priority", "5")
    assert q.json("claim")["id"] == "hi"
    assert q.json("claim")["id"] == "mid"
    assert q.json("claim")["id"] == "lo"


def test_fifo_tiebreak(q):
    q.run("enqueue", "--payload", "{}", "--id", "a")
    q.run("enqueue", "--payload", "{}", "--id", "b")
    assert q.json("claim")["id"] == "a"


def test_delayed_job_not_claimable(q):
    q.run("enqueue", "--payload", "{}", "--id", "later", "--delay", "3600")
    q.run("enqueue", "--payload", "{}", "--id", "now")
    assert q.json("claim")["id"] == "now"
    cp = q.run("claim")
    assert cp.returncode == 1
    assert "no jobs available" in cp.stderr
