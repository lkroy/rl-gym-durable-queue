"""Deduplication by --dedupe-key."""


def test_dedupe_same_key_returns_existing(q):
    id1 = q.run("enqueue", "--payload", '{"n":1}',
                "--dedupe-key", "k1").stdout.strip()
    cp = q.run("enqueue", "--payload", '{"n":2}', "--dedupe-key", "k1")
    assert cp.returncode == 0
    assert cp.stdout.strip() == id1
    assert len(q.json("list")) == 1  # nothing new created


def test_dedupe_key_reusable_after_done(q):
    id1 = q.run("enqueue", "--payload", "{}", "--dedupe-key", "k2").stdout.strip()
    q.json("claim")
    q.run("complete", id1)
    cp = q.run("enqueue", "--payload", "{}", "--dedupe-key", "k2")
    assert cp.returncode == 0
    id2 = cp.stdout.strip()
    assert id2 != id1
    assert len(q.json("list")) == 2
