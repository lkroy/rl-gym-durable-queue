"""CLI validation and exit-code contract."""


def test_bad_payload_json(q):
    assert q.run("enqueue", "--payload", "{not json").returncode == 2


def test_bad_id(q):
    assert q.run("enqueue", "--payload", "{}", "--id", "bad id!").returncode == 2


def test_negative_delay(q):
    assert q.run("enqueue", "--payload", "{}", "--delay", "-5").returncode == 2


def test_zero_max_attempts(q):
    assert q.run("enqueue", "--payload", "{}",
                 "--max-attempts", "0").returncode == 2


def test_duplicate_id(q):
    q.run("enqueue", "--payload", "{}", "--id", "dup")
    assert q.run("enqueue", "--payload", "{}",
                 "--id", "dup").returncode == 2


def test_zero_lease(q):
    q.run("enqueue", "--payload", "{}", "--id", "z1")
    assert q.run("claim", "--lease", "0").returncode == 2


def test_complete_pending_conflict(q):
    q.run("enqueue", "--payload", "{}", "--id", "pc1")
    cp = q.run("complete", "pc1")
    assert cp.returncode == 3
    assert "not claimed" in cp.stderr


def test_show_unknown(q):
    cp = q.run("show", "nope")
    assert cp.returncode == 4
    assert "job not found" in cp.stderr


def test_claim_empty(q):
    cp = q.run("claim")
    assert cp.returncode == 1
    assert "no jobs available" in cp.stderr


def test_unknown_command(q):
    assert q.run("frobnicate").returncode == 2


def test_stats_empty(q):
    assert q.json("stats") == {"pending": 0, "claimed": 0, "done": 0,
                               "dead": 0, "total": 0}


def test_default_qdata_dir(q_bin, tmp_path):
    # With $QDATA_DIR unset, the default ./.qdata (relative to cwd) is used
    # and created automatically.
    import os
    import subprocess
    env = {k: v for k, v in os.environ.items() if k != "QDATA_DIR"}
    cp = subprocess.run([q_bin, "stats"], capture_output=True, text=True,
                        env=env, cwd=str(tmp_path), timeout=60)
    assert cp.returncode == 0, cp.stderr
    assert os.path.isdir(str(tmp_path / ".qdata"))
