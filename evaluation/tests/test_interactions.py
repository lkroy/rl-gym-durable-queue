"""Cross-feature interactions (heavy weight): pause/drain/tags/deps/TTL."""
import json
import os
import subprocess
import time


def _wait_for_next_minute():
    now = time.time()
    target = (int(now) // 60 + 1) * 60 + 2
    time.sleep(max(0, target - time.time()))


def test_pause_schedule_materialize_then_resume_claim(q):
    """1. pause + schedule materialize still happens; after resume claimable."""
    q.run("pause")
    cp = q.run("schedule", "--payload", '{"s":1}', "--cron", "* * * * *",
               "--id", "ps1")
    assert cp.returncode == 0, cp.stderr
    _wait_for_next_minute()
    # Pre-steps still run while paused: materialize occurs.
    rows = q.json("list")
    mat = [r for r in rows if r["id"].startswith("ps1-")]
    assert len(mat) >= 1, rows
    # Claim blocked while paused
    cp = q.run("claim")
    assert cp.returncode == 1
    assert "queue paused" in cp.stderr
    q.run("resume")
    job = q.json("claim")
    assert job["id"].startswith("ps1-")
    assert job["tag"] is None
    assert job["depends_on"] == []


def test_pause_idempotency_inflight_vs_new(q):
    """2. idem key returns in-flight while paused; other key -> queue paused."""
    q.run("enqueue", "--payload", "{}", "--id", "i1")
    q.run("enqueue", "--payload", "{}", "--id", "i2")
    first = q.json("claim", "--idempotency-key", "KPAUSE", "--lease", "30")
    assert first["id"] == "i1"
    fence = first["fence"]
    q.run("pause")
    # Same key: returns in-flight job, does NOT extend lease, same fence
    again = q.json("claim", "--idempotency-key", "KPAUSE")
    assert again["id"] == "i1"
    assert again["fence"] == fence
    assert again["lease_expires_at"] == first["lease_expires_at"]
    # Different key while paused: queue paused (no new claim)
    cp = q.run("claim", "--idempotency-key", "KOTHER")
    assert cp.returncode == 1
    assert "queue paused" in cp.stderr
    assert q.json("show", "i2")["status"] == "pending"
    # Bare claim while paused also rejected
    cp = q.run("claim")
    assert cp.returncode == 1
    assert "queue paused" in cp.stderr


def test_claim_count_skips_blocked_deps_fills_ready(q):
    """3. claim --count skips unmet deps and fills from ready lower-prio."""
    q.run("enqueue", "--payload", "{}", "--id", "dep")
    q.run("enqueue", "--payload", "{}", "--id", "blocked",
          "--priority", "100", "--depends-on", "dep")
    q.run("enqueue", "--payload", "{}", "--id", "ready-hi", "--priority", "5")
    q.run("enqueue", "--payload", "{}", "--id", "ready-lo", "--priority", "1")
    # Leave dep pending so blocked stays unmet. Claim 2 ready jobs.
    cp = q.run("claim", "--count", "2")
    assert cp.returncode == 0, cp.stderr
    jobs = json.loads(cp.stdout)
    assert [j["id"] for j in jobs] == ["ready-hi", "ready-lo"]
    assert q.json("show", "blocked")["status"] == "pending"
    assert q.json("show", "dep")["status"] == "pending"


def test_waiter_ttl_expires_as_expired_while_dep_pending(q):
    """4. waiter TTL expires as expired while dep still pending."""
    q.run("enqueue", "--payload", "{}", "--id", "slowdep")
    q.run("enqueue", "--payload", "{}", "--id", "waiter",
          "--depends-on", "slowdep", "--ttl", "1")
    time.sleep(1.2)
    waiter = q.json("show", "waiter")
    assert waiter["status"] == "dead", waiter
    assert waiter["last_error"] == "expired", waiter
    assert q.json("show", "slowdep")["status"] == "pending"


def test_cascade_does_not_cancel_claimed_dependents(q):
    """5. cancel cascade skips claimed dependents; claimed stays claimed.

    Complete root, claim mid (claimed). side depends on mid+gate. Cascade
    cancel gate cancels gate and side only; mid stays claimed.
    """
    q.run("enqueue", "--payload", "{}", "--id", "root")
    q.run("enqueue", "--payload", "{}", "--id", "mid", "--depends-on", "root")
    q.run("enqueue", "--payload", "{}", "--id", "leaf", "--depends-on", "mid")
    q.run("enqueue", "--payload", "{}", "--id", "gate")
    root = q.json("claim")
    assert root["id"] == "root"
    q.run("complete", "root", "--fence", str(root["fence"]))
    mid = q.json("claim")
    assert mid["id"] == "mid"
    q.run("enqueue", "--payload", "{}", "--id", "side",
          "--depends-on", "mid,gate")
    cp = q.run("cancel", "gate", "--cascade")
    assert cp.returncode == 0, cp.stderr
    cancelled = set(json.loads(cp.stdout))
    assert cancelled == {"gate", "side"}
    assert "mid" not in cancelled
    assert q.json("show", "mid")["status"] == "claimed"
    assert q.json("show", "leaf")["status"] == "pending"


def test_drain_blocks_batch_existing_completable(q):
    """6. drain blocks enqueue-batch; existing jobs still completable."""
    q.run("enqueue", "--payload", "{}", "--id", "exist")
    job = q.json("claim")
    assert job["id"] == "exist"
    q.run("drain")
    cp = q.run("enqueue-batch", "--jobs",
               json.dumps([{"payload": {}, "id": "new1"}]))
    assert cp.returncode == 3
    assert "draining" in cp.stderr
    assert q.json("stats")["total"] == 1
    cp = q.run("complete", "exist", "--fence", str(job["fence"]))
    assert cp.returncode == 0
    assert q.json("show", "exist")["status"] == "done"


def test_fail_requeue_dep_keeps_dependent_blocked(q):
    """7. fail-requeue of dependency keeps dependent blocked until done again."""
    q.run("enqueue", "--payload", "{}", "--id", "d", "--max-attempts", "5")
    q.run("enqueue", "--payload", "{}", "--id", "child", "--depends-on", "d")
    job = q.json("claim")
    assert job["id"] == "d"
    q.run("fail", "d", "--fence", str(job["fence"]), "--error", "temp")
    # d is pending with backoff delay; child still blocked
    assert q.json("show", "d")["status"] == "pending"
    cp = q.run("claim")
    assert cp.returncode == 1
    assert "no jobs available" in cp.stderr
    # Wait out backoff and complete d, then child becomes claimable
    time.sleep(10.2)
    again = q.json("claim")
    assert again["id"] == "d"
    q.run("complete", "d", "--fence", str(again["fence"]))
    child = q.json("claim")
    assert child["id"] == "child"


def test_tagged_depends_on_untagged_dep(q):
    """8. tagged job depends on untagged dep; untagged claim then tagged."""
    q.run("enqueue", "--payload", "{}", "--id", "udep")
    q.run("enqueue", "--payload", "{}", "--id", "tdep",
          "--tag", "worker", "--depends-on", "udep")
    # Tagged claim sees nothing yet (dep unmet); untagged claims dep
    cp = q.run("claim", "--tag", "worker")
    assert cp.returncode == 1
    dep = q.json("claim")
    assert dep["id"] == "udep"
    assert dep["tag"] is None
    q.run("complete", "udep", "--fence", str(dep["fence"]))
    tagged = q.json("claim", "--tag", "worker")
    assert tagged["id"] == "tdep"
    assert tagged["tag"] == "worker"


def test_compact_preserves_meta_and_fields(q):
    """9. compact preserves pause/drain meta and depends_on/tag fields."""
    q.run("enqueue", "--payload", "{}", "--id", "cdep")
    q.run("enqueue", "--payload", "{}", "--id", "ctag",
          "--tag", "keep", "--depends-on", "cdep", "--priority", "3")
    q.run("pause")
    q.run("drain")
    # Grow WAL a bit
    for i in range(5):
        q.run("stats")
    cp = q.run("compact")
    assert cp.returncode == 0
    assert cp.stdout.strip() == "ok"
    # Meta preserved: claim -> queue paused; enqueue -> draining
    cp = q.run("claim")
    assert cp.returncode == 1
    assert "queue paused" in cp.stderr
    cp = q.run("enqueue", "--payload", "{}", "--id", "blocked-new")
    assert cp.returncode == 3
    assert "draining" in cp.stderr
    job = q.json("show", "ctag")
    assert job["tag"] == "keep"
    assert job["depends_on"] == ["cdep"]
    q.run("resume")
    # After resume both cleared
    dep = q.json("claim")
    assert dep["id"] == "cdep"
    q.run("complete", "cdep", "--fence", str(dep["fence"]))
    tagged = q.json("claim", "--tag", "keep")
    assert tagged["id"] == "ctag"


def test_parallel_claim_mixed_tags_no_double_delivery(q):
    """10. parallel claim with mixed tags never double-delivers within a tag."""
    for i in range(4):
        q.run("enqueue", "--payload", "{}", "--id", "u%d" % i)
        q.run("enqueue", "--payload", "{}", "--id", "t%d" % i, "--tag", "T")
    env = dict(os.environ, QDATA_DIR=q.qdata)
    procs = []
    for _ in range(6):
        procs.append(subprocess.Popen(
            [q.q_bin, "claim"], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=env))
        procs.append(subprocess.Popen(
            [q.q_bin, "claim", "--tag", "T"], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=env))
    untagged, tagged = [], []
    for p in procs:
        out, err = p.communicate(timeout=60)
        assert p.returncode in (0, 1), (p.returncode, err)
        if p.returncode != 0:
            continue
        job = json.loads(out)
        if job.get("tag") is None:
            untagged.append(job["id"])
        else:
            tagged.append(job["id"])
    assert len(untagged) == 4, untagged
    assert len(set(untagged)) == 4, "double delivery untagged: %s" % untagged
    assert len(tagged) == 4, tagged
    assert len(set(tagged)) == 4, "double delivery tagged: %s" % tagged
    assert set(untagged).isdisjoint(set(tagged))
