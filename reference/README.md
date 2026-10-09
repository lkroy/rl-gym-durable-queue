# Reference solution

`q` — a durable, crash-safe job queue CLI. Python 3, standard library only
(`fcntl.flock` for the cross-process exclusive lock).

Design (kept out of `task/instruction.md`, which stays behavior-only):

- Every command: `flock` a `.lock` file in `$QDATA_DIR`, load
  `snapshot.json` + replay `wal.log` (truncating any torn tail), sweep
  expired leases, execute, append one `{"op":"upsert","job":...}` line per
  changed job with `fsync`, rewrite the snapshot atomically
  (temp file + `fsync` + `os.rename`), unlock.
- Auto ids: `secrets.token_hex(8)` (16 hex chars), collision-checked.

Verified: `npm run check:reference` -> score exactly 1.0 (34/34 checks).
