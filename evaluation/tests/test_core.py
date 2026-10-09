"""Core enqueue/show/list/claim/complete/stats workflows."""
import json
import re

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def test_enqueue_prints_id(q):
    cp = q.run("enqueue", "--payload", '{"a": 1}')
    assert cp.returncode == 0
    jid = cp.stdout.strip()
    assert ID_RE.match(jid), "bad id: %r" % jid
    assert len(jid) == 16  # auto id: 16 hex chars


def test_show_roundtrips_payload(q):
    payload = {"task": "email", "to": ["a@x.com"], "n": 3}
    jid = q.run("enqueue", "--payload", json.dumps(payload)).stdout.strip()
    job = q.json("show", jid)
    assert job["payload"] == payload
    assert job["status"] == "pending"
    assert job["attempts"] == 0
    assert job["max_attempts"] == 3
    assert job["priority"] == 0
    assert job["dedupe_key"] is None
    assert job["claimed_at"] is None
    assert job["lease_expires_at"] is None
    assert job["last_error"] is None
    assert job["result"] is None
    assert isinstance(job["created_at"], float)
    assert isinstance(job["run_at"], float)


def test_list_sorted_and_filter(q):
    q.run("enqueue", "--payload", "{}", "--id", "w1")
    q.run("enqueue", "--payload", "{}", "--id", "w2")
    rows = q.json("list")
    assert len(rows) == 2
    keys = [(r["created_at"], r["id"]) for r in rows]
    assert keys == sorted(keys), "list not sorted by created_at asc, id asc"
    for r in rows:
        assert set(r) == {"id", "status", "priority", "attempts",
                          "created_at", "run_at"}
    q.json("claim")  # claims w1 (created first)
    assert [r["id"] for r in q.json("list", "--status", "pending")] == ["w2"]
    assert [r["id"] for r in q.json("list", "--status", "claimed")] == ["w1"]


def test_claim_complete_flow(q):
    q.run("enqueue", "--payload", '{"x":1}', "--id", "flow1")
    job = q.json("claim")
    assert job["id"] == "flow1"
    assert job["status"] == "claimed"
    assert job["claimed_at"] is not None
    assert job["lease_expires_at"] > job["claimed_at"]
    cp = q.run("complete", "flow1", "--result", '{"ok": true}')
    assert cp.returncode == 0
    assert cp.stdout.strip() == "flow1"
    job = q.json("show", "flow1")
    assert job["status"] == "done"
    assert job["result"] == {"ok": True}


def test_stats_counts(q):
    q.run("enqueue", "--payload", "1", "--id", "s1")
    q.run("enqueue", "--payload", "2", "--id", "s2")
    q.json("claim")  # claims s1
    q.run("complete", "s1")
    assert q.json("stats") == {"pending": 1, "claimed": 0, "done": 1,
                               "dead": 0, "total": 2}


def test_state_persisted_to_disk(q):
    import os
    cp = q.run("enqueue", "--payload", '{"a":1}', "--id", "persist1")
    assert cp.returncode == 0, cp.stderr
    files = [f for f in os.listdir(q.qdata)
             if os.path.isfile(os.path.join(q.qdata, f))]
    assert files, "expected state files under $QDATA_DIR after enqueue"
    total = sum(os.path.getsize(os.path.join(q.qdata, f)) for f in files)
    assert total > 0, "state files are empty"
    # a fresh process sees the same job (durability across processes)
    assert q.json("show", "persist1")["payload"] == {"a": 1}
