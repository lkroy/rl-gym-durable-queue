"""Job dependencies: blocking, priority skip, cycles, cascade on dead deps."""
import json
import time


def test_blocked_until_dependency_done(q):
    q.run("enqueue", "--payload", "{}", "--id", "a")
    q.run("enqueue", "--payload", "{}", "--id", "b", "--depends-on", "a")
    job = q.json("show", "b")
    assert job["depends_on"] == ["a"]
    cp = q.run("claim")
    assert cp.returncode == 0
    claimed = json.loads(cp.stdout)
    assert claimed["id"] == "a", "only a should be claimable"
    cp = q.run("claim")
    assert cp.returncode == 1, "b must stay blocked while a is claimed"
    assert "no jobs available" in cp.stderr
    q.run("complete", "a", "--fence", str(claimed["fence"]))
    claimed_b = q.json("claim")
    assert claimed_b["id"] == "b"
    assert claimed_b["depends_on"] == ["a"]


def test_priority_skipped_over_unmet_deps(q):
    # High-priority b depends on a; low-priority c is ready. Claim must
    # take c, not get stuck behind b.
    q.run("enqueue", "--payload", "{}", "--id", "a")
    q.run("enqueue", "--payload", "{}", "--id", "b",
          "--priority", "100", "--depends-on", "a")
    q.run("enqueue", "--payload", "{}", "--id", "c", "--priority", "1")
    # Claim a first so only b (blocked) and c (ready) remain... actually
    # leave a pending too: best ready candidate among a and c is a
    # (priority 0 vs 1 → c wins on priority). b is highest priority but
    # unmet deps, so must be skipped.
    claimed = q.json("claim")
    assert claimed["id"] == "c", claimed


def test_cycle_rejected(q):
    items = [
        {"payload": {}, "id": "c1", "depends_on": ["c2"]},
        {"payload": {}, "id": "c2", "depends_on": ["c1"]},
    ]
    cp = q.run("enqueue-batch", "--jobs", json.dumps(items))
    assert cp.returncode == 2
    assert "cycle" in cp.stderr
    assert q.json("stats")["total"] == 0  # batch created nothing
    # Also reject a self-dependency as a trivial cycle/self case
    cp = q.run("enqueue", "--payload", "{}", "--id", "s", "--depends-on", "s")
    assert cp.returncode == 2


def test_unknown_dep_rejected(q):
    cp = q.run("enqueue", "--payload", "{}", "--id", "u1",
               "--depends-on", "nope")
    assert cp.returncode == 2
    cp = q.run("enqueue", "--payload", "{}", "--id", "u2",
               "--depends-on", "u2")  # self
    assert cp.returncode == 2
    cp = q.run("enqueue", "--payload", "{}", "--id", "u3",
               "--depends-on", "a,,b")
    assert cp.returncode == 2


def test_dep_dead_cascades_dependent(q):
    q.run("enqueue", "--payload", "{}", "--id", "d1", "--max-attempts", "1")
    q.run("enqueue", "--payload", "{}", "--id", "d2", "--depends-on", "d1")
    job = q.json("claim")
    assert job["id"] == "d1"
    q.run("fail", "d1", "--fence", str(job["fence"]), "--error", "boom")
    # fail made d1 dead; next command cascades d2
    d2 = q.json("show", "d2")
    assert d2["status"] == "dead"
    assert d2["last_error"] == "dependency failed"


def test_batch_depends_on_earlier_element(q):
    items = [
        {"payload": {"n": 1}, "id": "ba"},
        {"payload": {"n": 2}, "id": "bb", "depends_on": ["ba"]},
    ]
    cp = q.run("enqueue-batch", "--jobs", json.dumps(items))
    assert cp.returncode == 0, cp.stderr
    ids = json.loads(cp.stdout)
    assert ids == ["ba", "bb"]
    assert q.json("show", "bb")["depends_on"] == ["ba"]
    claimed = q.json("claim")
    assert claimed["id"] == "ba"
    cp = q.run("claim")
    assert cp.returncode == 1


def test_ttl_expiry_of_dep_kills_dependent(q):
    q.run("enqueue", "--payload", "{}", "--id", "tdep", "--ttl", "1")
    q.run("enqueue", "--payload", "{}", "--id", "tchild",
          "--depends-on", "tdep")
    time.sleep(1.2)
    child = q.json("show", "tchild")
    assert child["status"] == "dead", child
    assert child["last_error"] == "dependency failed"
    parent = q.json("show", "tdep")
    assert parent["status"] == "dead"
    assert parent["last_error"] == "expired"
