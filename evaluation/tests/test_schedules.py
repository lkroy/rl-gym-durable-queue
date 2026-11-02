"""Recurring schedules: cron parsing, materialization, unschedule."""
import json
import os
import subprocess
import time


def _wait_for_next_minute():
    now = time.time()
    target = (int(now) // 60 + 1) * 60 + 2
    time.sleep(max(0, target - time.time()))


def test_schedule_every_minute_materializes(q):
    cp = q.run("schedule", "--payload", "{}", "--cron", "* * * * *",
               "--id", "s1")
    assert cp.returncode == 0, cp.stderr
    assert cp.stdout.strip() == "s1"
    _wait_for_next_minute()
    rows = q.json("list")
    mat = [r for r in rows if r["id"].startswith("s1-")]
    assert len(mat) >= 1, rows
    # id encodes the UTC occurrence minute
    assert all(len(jid) == len("s1-") + 12 for jid in
               [r["id"] for r in mat])
    # a second command must not create duplicates
    rows2 = q.json("list")
    ids2 = [r["id"] for r in rows2]
    assert len(ids2) == len(set(ids2)), "duplicate job ids"


def test_unschedule_stops_but_keeps_jobs(q):
    q.run("schedule", "--payload", "{}", "--cron", "* * * * *", "--id", "s3")
    _wait_for_next_minute()
    before = {r["id"] for r in q.json("list") if r["id"].startswith("s3-")}
    assert len(before) >= 1
    cp = q.run("unschedule", "s3")
    assert cp.returncode == 0, cp.stderr
    assert cp.stdout.strip() == "s3"
    assert q.json("schedules") == []
    _wait_for_next_minute()
    after = {r["id"] for r in q.json("list") if r["id"].startswith("s3-")}
    assert after == before, "new occurrences after unschedule or jobs lost"
    cp = q.run("unschedule", "s3")
    assert cp.returncode == 4


def test_schedule_malformed_cron_rejected(q):
    for bad in ["61 * * * *", "not-a-cron", "* * *", "*/0 * * * *"]:
        cp = q.run("schedule", "--payload", "{}", "--cron", bad)
        assert cp.returncode == 2, bad
    assert q.json("schedules") == []
    assert q.json("list") == []


def test_schedule_end_at_past_materializes_nothing(q):
    past = time.time() - 10
    cp = q.run("schedule", "--payload", "{}", "--cron", "* * * * *",
               "--id", "s4", "--end-at", str(past))
    assert cp.returncode == 0, cp.stderr
    _wait_for_next_minute()
    rows = q.json("list")
    assert not [r for r in rows if r["id"].startswith("s4-")], rows
    scheds = q.json("schedules")
    assert len(scheds) == 1 and scheds[0]["id"] == "s4"


def test_schedule_kill_during_materialization(q):
    q.run("schedule", "--payload", "{}", "--cron", "* * * * *", "--id", "k1")
    _wait_for_next_minute()
    env = dict(os.environ, QDATA_DIR=q.qdata)
    procs = []
    for _ in range(10):
        procs.append(subprocess.Popen(
            [q.q_bin, "list"], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=env))
        time.sleep(0.005)
    time.sleep(0.003)
    for p in procs:
        if p.poll() is None:
            p.kill()
        p.wait(timeout=60)
    cp = q.run("stats")
    assert cp.returncode == 0, cp.stderr
    rows = q.json("list")
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), "duplicate ids after kills"
