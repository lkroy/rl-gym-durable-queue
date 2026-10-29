"""Atomic batch enqueue: `q enqueue-batch --jobs '<json-array>'`.

Either all of the batch's jobs are created or none is: full validation
before any creation, per-element dedupe (including against earlier
elements of the same batch), and all-or-nothing under SIGKILL.
"""
import json
import os
import random
import re
import subprocess
import time

BLOB = "x" * 20000  # 5 x 20KB payloads stay under the per-arg size limit


def _spawn(q, *args):
    env = dict(os.environ)
    env["QDATA_DIR"] = q.qdata
    return subprocess.Popen(
        [q.q_bin, *args], env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def test_batch_happy_path(q):
    items = [
        {"payload": {"n": 1}, "id": "b1", "priority": 5},
        {"payload": [1, 2, 3], "id": "b2"},
        {"payload": "text", "delay": 0, "max_attempts": 2},
    ]
    cp = q.run("enqueue-batch", "--jobs", json.dumps(items))
    assert cp.returncode == 0, cp.stderr
    ids = json.loads(cp.stdout)
    assert len(ids) == 3, "expected 3 ids, got %r" % (ids,)
    assert ids[0] == "b1" and ids[1] == "b2"
    listed = {r["id"] for r in q.json("list")}
    assert set(ids) <= listed
    assert q.json("show", "b1")["priority"] == 5


def test_batch_invalid_element_aborts_everything(q):
    items = [
        {"payload": {"n": 1}, "id": "w1"},
        {"payload": {"n": 2}, "id": "bad id!"},  # invalid: 2nd of 3
        {"payload": {"n": 3}, "id": "w3"},
    ]
    cp = q.run("enqueue-batch", "--jobs", json.dumps(items))
    assert cp.returncode == 2, "expected exit 2, got %d" % cp.returncode
    assert cp.stderr.strip(), "expected a stderr message"
    listed = {r["id"] for r in q.json("list")}
    assert not ({"w1", "w3"} & listed), \
        "partial batch was created: %r" % (listed,)
    assert q.json("stats")["total"] == 0


def test_batch_dedupe_within_batch(q):
    items = [
        {"payload": {"n": 1}, "id": "u1", "dedupe_key": "dk"},
        {"payload": {"n": 2}, "id": "u2", "dedupe_key": "dk"},
    ]
    cp = q.run("enqueue-batch", "--jobs", json.dumps(items))
    assert cp.returncode == 0, cp.stderr
    ids = json.loads(cp.stdout)
    assert ids[0] == ids[1] == "u1", \
        "dedupe within batch did not resolve: %r" % (ids,)
    assert q.json("stats")["total"] == 1
    # dedupe against a pre-existing job also resolves instead of duplicating
    cp = q.run("enqueue-batch", "--jobs",
               json.dumps([{"payload": {"n": 9}, "dedupe_key": "dk"}]))
    assert cp.returncode == 0, cp.stderr
    assert json.loads(cp.stdout) == ["u1"]
    assert q.json("stats")["total"] == 1


def test_batch_kill_mid_batch_all_or_nothing(q):
    rng = random.Random(918273)
    trials = 8
    per_batch = 5
    for trial in range(trials):
        items = [{"id": "kb%d-%d" % (trial, k),
                  "payload": {"blob": BLOB, "t": trial, "k": k}}
                 for k in range(per_batch)]
        p = _spawn(q, "enqueue-batch", "--jobs", json.dumps(items))
        time.sleep(rng.uniform(0.002, 0.030))
        if p.poll() is None:
            p.kill()  # SIGKILL
        p.wait()
        cp = q.run("stats")
        assert cp.returncode == 0, \
            "queue unusable after SIGKILL mid-batch (trial %d): %r" % (
                trial, cp.stderr)
    by_trial = {}
    for r in q.json("list"):
        m = re.match(r"^kb(\d+)-", r["id"])
        if m:
            t = int(m.group(1))
            by_trial[t] = by_trial.get(t, 0) + 1
    for trial in range(trials):
        n = by_trial.get(trial, 0)
        assert n in (0, per_batch), \
            "partial batch %d: %d of %d jobs present" % (
                trial, n, per_batch)
