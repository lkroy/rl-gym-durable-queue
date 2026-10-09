"""Crash recovery: torn WAL tail, missing/corrupt snapshot, compact."""
import json
import os


def _wal(q):
    return os.path.join(q.qdata, "wal.log")


def _snap(q):
    return os.path.join(q.qdata, "snapshot.json")


def test_torn_tail_ignored(q):
    for i in range(3):
        q.run("enqueue", "--payload", "{}", "--id", "t%d" % i)
    with open(_wal(q), "ab") as f:
        f.write(b'{"op": "upsert", "job": {"id": "xx"')  # no newline: torn
    cp = q.run("list")
    assert cp.returncode == 0, cp.stderr
    assert len(json.loads(cp.stdout)) == 3
    assert q.json("stats")["total"] == 3  # queue stays fully operational
    with open(_wal(q), "rb") as f:
        data = f.read()
    assert data == b"" or data.endswith(b"\n")  # tail was truncated


def test_missing_snapshot_rebuilds_from_log(q):
    q.run("enqueue", "--payload", '{"a":1}', "--id", "m1")
    q.run("enqueue", "--payload", '{"b":2}', "--id", "m2")
    os.remove(_snap(q))
    rows = q.json("list")
    assert sorted(r["id"] for r in rows) == ["m1", "m2"]
    assert q.json("show", "m1")["payload"] == {"a": 1}


def test_corrupt_snapshot_rebuilds_from_log(q):
    q.run("enqueue", "--payload", "{}", "--id", "g1")
    with open(_snap(q), "w") as f:
        f.write("### not json ###")
    assert [r["id"] for r in q.json("list")] == ["g1"]


def test_compact_truncates_log(q):
    q.run("enqueue", "--payload", "{}", "--id", "k1")
    q.run("enqueue", "--payload", "{}", "--id", "k2")
    cp = q.run("compact")
    assert cp.returncode == 0
    assert cp.stdout.strip() == "ok"
    assert os.path.exists(_snap(q))
    assert os.path.getsize(_wal(q)) == 0
    rows = q.json("list")
    assert sorted(r["id"] for r in rows) == ["k1", "k2"]
    assert q.json("claim")["id"] == "k1"  # operational after compact


def test_log_replay_later_wins(q):
    # The on-disk contract: snapshot loads first, then wal.log replays in
    # order and the LATER line wins for the same job id.
    q.run("enqueue", "--payload", "{}", "--id", "rw1")
    assert q.json("show", "rw1")["status"] == "pending"
    job = q.json("show", "rw1")
    job["status"] = "claimed"
    job["claimed_at"] = job["created_at"]
    job["lease_expires_at"] = job["created_at"] + 3600
    with open(_wal(q), "a") as f:
        f.write(json.dumps({"op": "upsert", "job": job}) + "\n")
    assert q.json("show", "rw1")["status"] == "claimed"
