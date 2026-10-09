# Durable Job Queue — `q`

Build a single-executable command-line program named `q` that manages a
persistent job queue on disk. Python 3, standard library only.

Place the executable at the solution root (it will be invoked as `./q` or
via an absolute path). It MUST be executable (`chmod +x`).

## State directory

- The state directory comes from the `$QDATA_DIR` environment variable.
  If unset, default to `./.qdata` (relative to the current working directory).
- The program MUST create the state directory if it does not exist.

## On-disk contract (observable file states)

- `$QDATA_DIR/wal.log`: append-only write-ahead log. One JSON object per
  line, each of the form `{"op": "upsert", "job": <full job object>}`.
  Exactly one line is appended per job mutation.
- `$QDATA_DIR/snapshot.json`: a full snapshot of the form
  `{"jobs": {"<id>": <full job object>, ...}}`. This file MAY be absent.
- Startup: every command MUST load `snapshot.json` first (if present and
  parseable), then replay `wal.log` lines in order; when both contain the
  same job id, the LATER log line wins.
- Torn tail: a trailing partial line in `wal.log` — missing its terminating
  newline, or not valid JSON (as left behind by a crashed writer) — MUST be
  ignored and truncated from the file. The queue MUST remain fully
  operational afterwards (exit code 0 on the next command).
- A missing OR unreadable/corrupt `snapshot.json` MUST NOT lose data: the
  queue MUST be rebuilt from `wal.log` alone.
- `q compact` MUST rewrite `snapshot.json` from the current in-memory state
  and truncate `wal.log` to empty.
- Concurrency: multiple `q` processes running at the same time MUST NEVER
  deliver (claim) the same job twice. Mutations MUST be atomic: a process
  killed mid-command MUST NOT leave the queue in a half-written state.
- Durability: after a command exits 0, its effects MUST survive a process
  kill (data MUST be fsynced to disk, and snapshot rewrites MUST be atomic
  via temp-file + fsync + rename).

## Job object

Fields and defaults:

| field              | type              | default                          |
|--------------------|-------------------|----------------------------------|
| id                 | string            | auto-generated (16 hex chars)    |
| payload            | any JSON          | (required at enqueue)             |
| priority           | int               | 0                                |
| max_attempts       | int >= 1          | 3                                |
| attempts           | int               | 0                                |
| status             | string            | "pending"                        |
| created_at         | epoch float       | time of enqueue                   |
| run_at             | epoch float       | time of enqueue (+ delay)         |
| dedupe_key         | string or null    | null                             |
| claimed_at         | float or null     | null                             |
| lease_expires_at   | float or null     | null                             |
| last_error         | string or null    | null                             |
| result             | any JSON or null  | null                             |

`status` is one of `pending`, `claimed`, `done`, `dead`.

## Commands

All JSON printed to stdout MUST be parseable JSON. Validation failures MUST
print a message to stderr.

- `q enqueue --payload JSON [--priority INT] [--delay SEC] [--id ID]
  [--dedupe-key KEY] [--max-attempts N]`
  - On success: print the job id followed by a newline to stdout, exit 0.
  - `--payload` MUST be valid JSON, otherwise exit 2.
  - `--id`, when given, MUST match `^[A-Za-z0-9_-]{1,64}$`, otherwise exit 2.
  - `--id` MUST NOT duplicate an existing job id, otherwise exit 2.
  - `--delay` MUST NOT be negative, otherwise exit 2. `run_at` is set to
    `created_at + delay` (default delay 0).
  - `--max-attempts` MUST be >= 1, otherwise exit 2.
  - Dedupe: if `--dedupe-key` is given and a job with the same key exists
    with status `pending` or `claimed`, print THAT job's id, exit 0, and
    create nothing. A key whose previous job is `done` (or `dead`) does NOT
    block a new enqueue.

- `q list [--status S]`
  - Print a JSON array of summaries, one per job:
    `{"id","status","priority","attempts","created_at","run_at"}`.
  - Sorted by `created_at` ascending, then `id` ascending.
  - `--status` filters to that status. Exit 0.

- `q show ID`
  - Print the full job object as JSON, exit 0.
  - Unknown id: stderr MUST contain `job not found`, exit 4.

- `q claim [--lease SEC]` (default 60)
  - `--lease` MUST be > 0, otherwise exit 2.
  - First, sweep expired leases: any job with status `claimed` and
    `lease_expires_at <= now` returns to `pending`, with `claimed_at` and
    `lease_expires_at` cleared.
  - Candidates: status `pending` AND `run_at <= now`.
  - Order: `priority` descending, then `created_at` ascending, then `id`
    ascending. Claim the first candidate: set status `claimed`,
    `claimed_at = now`, `lease_expires_at = now + lease`.
  - Print the full job object as JSON, exit 0.
  - If no candidate: stderr MUST contain `no jobs available`, exit 1.

- `q complete ID [--result JSON]`
  - Unknown id: exit 4.
  - The job MUST have status `claimed`, otherwise stderr MUST contain
    `not claimed` and exit 3.
  - `--result` MUST be valid JSON when given, otherwise exit 2.
  - Set status `done`, store `result`, print the job id, exit 0.

- `q fail ID [--error MSG]`
  - Unknown id: exit 4.
  - The job MUST have status `claimed`, otherwise exit 3.
  - Increment `attempts`. If `attempts >= max_attempts`, status becomes
    `dead`. Otherwise status becomes `pending` with
    `run_at = now + 10 * 2**(attempts-1)` (10s, 20s, 40s, ...), and
    `claimed_at` / `lease_expires_at` are cleared. `last_error` is set to
    MSG (or null).
  - Print the job id, exit 0.

- `q stats`
  - Print `{"pending":n,"claimed":n,"done":n,"dead":n,"total":n}`, exit 0.

- `q compact`
  - Rewrite `snapshot.json` from current state and truncate `wal.log`.
    Print `ok`, exit 0.

- Any unknown command: exit 2.

## Exit codes

- 0: success
- 1: no jobs available (claim found no candidate)
- 2: usage / validation error
- 3: state conflict (complete/fail on a job that is not claimed)
- 4: not found (unknown job id)

## Per-command lifecycle

Every command conceptually performs: acquire an exclusive lock on the state
directory, load (snapshot + WAL replay + torn-tail truncation), sweep
expired leases, execute, append WAL line(s) and fsync, atomically rewrite
the snapshot (temp file + fsync + rename), release the lock.
