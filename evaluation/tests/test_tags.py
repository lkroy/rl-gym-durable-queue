"""Job tags: hard partition between tagged and untagged claims."""
import json


def test_untagged_claim_skips_tagged_jobs(q):
    q.run("enqueue", "--payload", "{}", "--id", "t1", "--tag", "alpha")
    q.run("enqueue", "--payload", "{}", "--id", "u1")
    job = q.json("claim")
    assert job["id"] == "u1"
    assert job["tag"] is None
    cp = q.run("claim")
    assert cp.returncode == 1
    assert "no jobs available" in cp.stderr
    assert q.json("show", "t1")["status"] == "pending"
    assert q.json("show", "t1")["tag"] == "alpha"


def test_tagged_claim_skips_untagged_jobs(q):
    q.run("enqueue", "--payload", "{}", "--id", "u2")
    q.run("enqueue", "--payload", "{}", "--id", "t2", "--tag", "beta")
    job = q.json("claim", "--tag", "beta")
    assert job["id"] == "t2"
    assert job["tag"] == "beta"
    cp = q.run("claim", "--tag", "beta")
    assert cp.returncode == 1
    assert q.json("show", "u2")["status"] == "pending"


def test_invalid_tag_rejected(q):
    for bad in ["", "has space", "too-long-" + ("x" * 40), "bad!"]:
        cp = q.run("enqueue", "--payload", "{}", "--tag", bad)
        assert cp.returncode == 2, bad
    q.run("enqueue", "--payload", "{}", "--id", "ok")
    cp = q.run("claim", "--tag", "bad tag!")
    assert cp.returncode == 2
    # Batch bad tag aborts
    cp = q.run("enqueue-batch", "--jobs",
               json.dumps([{"payload": {}, "tag": "no spaces ok?"}]))
    assert cp.returncode == 2


def test_claim_count_with_tags_only_matching(q):
    q.run("enqueue", "--payload", "{}", "--id", "a1", "--tag", "g")
    q.run("enqueue", "--payload", "{}", "--id", "b1")
    q.run("enqueue", "--payload", "{}", "--id", "a2", "--tag", "g")
    q.run("enqueue", "--payload", "{}", "--id", "b2")
    cp = q.run("claim", "--count", "5", "--tag", "g")
    assert cp.returncode == 0, cp.stderr
    jobs = json.loads(cp.stdout)
    assert [j["id"] for j in jobs] == ["a1", "a2"]
    assert all(j["tag"] == "g" for j in jobs)
    assert q.json("show", "b1")["status"] == "pending"
    assert q.json("show", "b2")["status"] == "pending"


def test_priority_order_within_same_tag(q):
    q.run("enqueue", "--payload", "{}", "--id", "lo",
          "--tag", "p", "--priority", "1")
    q.run("enqueue", "--payload", "{}", "--id", "hi",
          "--tag", "p", "--priority", "9")
    q.run("enqueue", "--payload", "{}", "--id", "mid",
          "--tag", "p", "--priority", "5")
    # Untagged high priority must not leak into tagged claim
    q.run("enqueue", "--payload", "{}", "--id", "other", "--priority", "100")
    job = q.json("claim", "--tag", "p")
    assert job["id"] == "hi"
    job = q.json("claim", "--tag", "p")
    assert job["id"] == "mid"
    job = q.json("claim", "--tag", "p")
    assert job["id"] == "lo"


def test_complete_tagged_leaves_untagged_claimable(q):
    """Completing a tagged job must not affect an untagged pending job."""
    q.run("enqueue", "--payload", "{}", "--id", "tagged", "--tag", "alpha")
    q.run("enqueue", "--payload", '{"u":1}', "--id", "untagged")
    before = q.json("show", "untagged")
    job = q.json("claim", "--tag", "alpha")
    assert job["id"] == "tagged"
    assert q.run("complete", "tagged", "--fence",
                 str(job["fence"])).returncode == 0
    after = q.json("show", "untagged")
    assert after["status"] == "pending"
    assert after["payload"] == before["payload"]
    assert after["tag"] is None
    claimed = q.json("claim")
    assert claimed["id"] == "untagged"
    assert claimed["tag"] is None
