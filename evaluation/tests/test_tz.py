"""Timezone-aware schedules: --tz handling and local-wall-clock job ids."""
import datetime
import time
from zoneinfo import ZoneInfo


def _wait_for_next_minute():
    now = time.time()
    target = (int(now) // 60 + 1) * 60 + 2
    time.sleep(max(0, target - time.time()))


def test_schedule_invalid_tz_rejected(q):
    cp = q.run("schedule", "--payload", "{}", "--cron", "* * * * *",
               "--id", "tz1", "--tz", "Not/AZone")
    assert cp.returncode == 2
    assert q.json("schedules") == []


def test_schedules_default_tz_utc(q):
    cp = q.run("schedule", "--payload", "{}", "--cron", "* * * * *",
               "--id", "tz2")
    assert cp.returncode == 0, cp.stderr
    rows = q.json("schedules")
    assert len(rows) == 1
    assert rows[0]["tz"] == "UTC"


def test_schedules_summary_shows_tz(q):
    cp = q.run("schedule", "--payload", "{}", "--cron", "* * * * *",
               "--id", "tz3", "--tz", "America/New_York")
    assert cp.returncode == 0, cp.stderr
    rows = q.json("schedules")
    assert len(rows) == 1
    assert rows[0]["tz"] == "America/New_York"


def test_tz_new_york_materializes_local_wallclock(q):
    cp = q.run("schedule", "--payload", "{}", "--cron", "* * * * *",
               "--id", "t3", "--tz", "America/New_York")
    assert cp.returncode == 0, cp.stderr
    _wait_for_next_minute()
    ids = [r["id"] for r in q.json("list")]
    mat = [jid for jid in ids if jid.startswith("t3-")]
    assert len(mat) >= 1, ids
    now_ny = datetime.datetime.now(ZoneInfo("America/New_York"))
    expected = {now_ny.strftime("%Y%m%d%H%M"),
                (now_ny - datetime.timedelta(minutes=1)).strftime(
                    "%Y%m%d%H%M")}
    suffixes = {jid[len("t3-"):] for jid in mat}
    assert suffixes & expected, (suffixes, expected)


def test_utc_schedule_id_uses_utc_wallclock(q):
    cp = q.run("schedule", "--payload", "{}", "--cron", "* * * * *",
               "--id", "t4")
    assert cp.returncode == 0, cp.stderr
    _wait_for_next_minute()
    ids = [r["id"] for r in q.json("list")]
    mat = [jid for jid in ids if jid.startswith("t4-")]
    assert len(mat) >= 1, ids
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    expected = {now_utc.strftime("%Y%m%d%H%M"),
                (now_utc - datetime.timedelta(minutes=1)).strftime(
                    "%Y%m%d%H%M")}
    suffixes = {jid[len("t4-"):] for jid in mat}
    assert suffixes & expected, (suffixes, expected)
