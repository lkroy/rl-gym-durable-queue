"""Shared fixtures for the q black-box test suite.

The binary under test comes from $Q_BIN (set by evaluation/score.py);
default is the reference implementation for local development.
Each test gets a fresh, isolated $QDATA_DIR.
"""
import json
import os
import subprocess

import pytest

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Q:
    def __init__(self, q_bin, qdata):
        self.q_bin = q_bin
        self.qdata = qdata

    def run(self, *args):
        env = dict(os.environ)
        env["QDATA_DIR"] = self.qdata
        return subprocess.run([self.q_bin, *args], capture_output=True,
                              text=True, env=env, timeout=60)

    def json(self, *args):
        cp = self.run(*args)
        assert cp.returncode == 0, (
            "q %s failed: rc=%d stderr=%r" % (" ".join(args),
                                             cp.returncode, cp.stderr))
        return json.loads(cp.stdout)


@pytest.fixture
def q_bin():
    return os.environ.get("Q_BIN", os.path.join(REPO_ROOT, "reference", "q"))


@pytest.fixture
def q(q_bin, tmp_path):
    # NOTE: the qdata dir is intentionally NOT pre-created: every test
    # exercises the "create $QDATA_DIR if missing" requirement.
    d = tmp_path / "qdata"
    return Q(q_bin, str(d))
