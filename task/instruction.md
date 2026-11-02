# Durable Job Queue — `q`

Build a single-executable command-line program named `q` that manages a
persistent job queue on disk. Python 3, standard library only.

Place the executable at the solution root (it will be invoked as `./q` or
via an absolute path). It MUST be executable (`chmod +x`).

## State directory

- The state directory comes from the `$QDATA_DIR` environment variable.
  If unset, default to `./.qdata` (relative to the current working directory).
- The program MUST create the state directory if it does not exist.

## Durability & crash-recovery contract

How state is stored under `$QDATA_DIR` is entirely up to you — file names,
formats, and data structures are your design choice. What is graded is that
these guarantees hold observably:

- Durability: once a command has exited 0, its effects MUST survive the
  process being killed (SIGKILL) at any later moment. Data MUST reach
  durable storage (fsync) before the command reports success.
- Crash atomicity: if a `q` process is killed (SIGKILL) in the middle of ANY
  command, the queue MUST NOT be left half-written or unreadable. The very
  next `q` invocation MUST exit 0 and see every previously acknowledged job
  intact; the interrupted operation itself MUST have taken effect at most
  once (it may have fully completed or not at all — never partially, never
  duplicated).
- Redundancy: the queue must keep every acknowledged job intact and remain
  fully operational even if any single file under the state directory is
  lost while no `q` process is running. Design your storage so that no
  single file is a single point of failure.
- Partial writes: a crash can interrupt a write at any byte, leaving a
  state file with a partially-written trailing record. The next command
  MUST recover from this automatically — discarding the partial data,
  keeping every acknowledged job intact, and exiting 0.
- `q compact` MUST preserve every job, whatever its status, and MUST reduce
  the total bytes stored under `$QDATA_DIR` once the queue has grown through
  many operations (it is the mechanism that reclaims space from the
  redundant storage above). A process killed (SIGKILL) in the middle of
  `q compact` MUST NOT lose any acknowledged job.
- Concurrency: multiple `q` processes running at the same time MUST NEVER
  deliver (claim) the same job twice, and concurrent mutations MUST NOT
  corrupt the queue. Serialize access with OS-level locking.

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
| ttl                | float or null     | null (no expiry)                   |
| claimed_at         | float or null     | null                             |
| lease_expires_at   | float or null     | null                             |
| last_error         | string or null    | null                             |
| result             | any JSON or null  | null                             |

`status` is one of `pending`, `claimed`, `done`, `dead`.

## Pre-steps (run at the start of every command)

Before executing any command, `q` MUST perform these steps in order, as
one atomic unit with the command itself:

1. **Materialize due schedule occurrences** (see `q schedule`): for each
   schedule, create one pending job per occurrence with time <= now and
   time > the schedule's `last_materialized`, then advance
   `last_materialized` to the latest materialized occurrence.
2. **Sweep expired leases**: any `claimed` job with
   `lease_expires_at <= now` returns to `pending` (clearing `claimed_at`
   / `lease_expires_at`), unless it is also past its TTL (see next step).
   Idempotency mappings whose lease expired are discarded.
3. **Sweep expired TTLs**: any job with a non-null `ttl` where
   `now - created_at > ttl` and status is `pending` becomes `dead` with
   `last_error` set to `"expired"`. A `claimed` job is exempt while its
   lease is valid; if its lease has expired it is `dead` (not requeued).

## Commands

All JSON printed to stdout MUST be parseable JSON. Validation failures MUST
print a message to stderr.

- `q enqueue --payload JSON [--priority INT] [--delay SEC] [--id ID]
  [--dedupe-key KEY] [--max-attempts N] [--ttl SEC]`
  - On success: print the job id followed by a newline to stdout, exit 0.
  - `--payload` MUST be valid JSON, otherwise exit 2.
  - `--id`, when given, MUST match `^[A-Za-z0-9_-]{1,64}$`, otherwise exit 2.
  - `--id` MUST NOT duplicate an existing job id, otherwise exit 2.
  - `--delay` MUST NOT be negative, otherwise exit 2. `run_at` is set to
    `created_at + delay` (default delay 0).
  - `--max-attempts` MUST be >= 1, otherwise exit 2.
  - `--ttl`, when given, MUST be > 0, otherwise exit 2. The job expires
    `ttl` seconds after `created_at` (see pre-step 3). A delayed job can
    expire before ever becoming claimable.
  - Dedupe: if `--dedupe-key` is given and a job with the same key exists
    with status `pending` or `claimed`, print THAT job's id, exit 0, and
    create nothing. A key whose previous job is `done` (or `dead`) does NOT
    block a new enqueue.

- `q enqueue-batch --jobs '<json-array>'`
  - Enqueue many jobs atomically: either ALL of them are created or NONE
    is. `--jobs` MUST be a JSON array, otherwise exit 2.
  - Each element is an object with `payload` (required, any JSON) and
    optional `priority`, `delay`, `id`, `dedupe_key`, `max_attempts`
    (same meanings and validation as `enqueue`). Validate EVERY element
    before creating anything: any invalid element (bad JSON types, bad
    `id` format, duplicate `id` within the batch or against existing
    jobs, negative `delay`, `max_attempts` < 1, missing `payload`)
    aborts the whole batch with exit 2 and creates NOTHING.
  - Dedupe is resolved per element as in `enqueue`: an element whose
    `dedupe_key` matches a `pending`/`claimed` job — including an earlier
    element of the same batch — resolves to that job's id instead of
    creating a duplicate. Dedupe hits do NOT abort the batch.
  - Crash atomicity applies to the batch as a whole: a process killed
    (SIGKILL) in the middle of `enqueue-batch` MUST leave either all of
    the batch's jobs or none of them — never a partial batch.
  - On success: print a JSON array of the job ids (in input order), exit 0.

- `q list [--status S]`
  - Print a JSON array of summaries, one per job:
    `{"id","status","priority","attempts","created_at","run_at"}`.
  - Sorted by `created_at` ascending, then `id` ascending.
  - `--status` filters to that status. Exit 0.

- `q show ID`
  - Print the full job object as JSON, exit 0.
  - Unknown id: stderr MUST contain `job not found`, exit 4.

- `q claim [--lease SEC] [--idempotency-key KEY]` (default 60)
  - `--lease` MUST be > 0, otherwise exit 2.
  - `--idempotency-key`, when given, MUST match `^[A-Za-z0-9_-]{1,64}$`,
    otherwise exit 2.
  - The pre-steps run first (materialization, lease sweep, TTL sweep).
  - If KEY is given and maps to a job that is currently `claimed` with an
    unexpired lease, return THAT job (full JSON), exit 0. Do NOT claim a
    new job and do NOT extend the lease. This gives exactly-once delivery
    across client retries and crashes.
  - Otherwise claim the best candidate as usual; if a candidate is
    claimed, record KEY as mapped to it (replacing any stale mapping).
    Mappings for jobs that become `done` or `dead` are discarded, so a
    later claim with the same KEY starts fresh.
  - The mapping MUST be durable (survive crashes) and MUST be safe under
    concurrency: two processes claiming at the same time with the same
    KEY MUST receive the same job, never two different jobs.
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

- `q schedule --payload JSON --cron EXPR [--id ID] [--priority INT]
  [--max-attempts N] [--end-at EPOCH]`
  - Creates a recurring schedule. `--payload` MUST be valid JSON,
    otherwise exit 2. `--id`, when given, MUST match
    `^[A-Za-z0-9_-]{1,64}$` and MUST NOT duplicate an existing schedule
    id, otherwise exit 2. `--max-attempts` MUST be >= 1, otherwise exit 2.
  - `--cron` is a 5-field expression `minute hour dom month dow`
    evaluated in UTC. Each field accepts `*`, `*/step`, `a-b`,
    `a-b/step`, `a,b,c`, or a single value. Ranges: minute 0-59, hour
    0-23, dom 1-31, month 1-12, dow 0-6 (0 and 7 both mean Sunday). Any
    malformed field or out-of-range value → exit 2. A date that never
    exists (e.g. Feb 30) simply never matches.
  - Matching rule: an occurrence exists at each minute where minute,
    hour and month match, and (dom matches OR dow matches) — with the
    standard refinement that if one of dom/dow is `*` (unrestricted),
    the other alone decides.
  - `--end-at`, when given, is an epoch timestamp: occurrences at or
    after it are never materialized.
  - On success: print the schedule id, exit 0.

- `q schedules`
  - Print a JSON array of schedule summaries, one per schedule:
    `{"id","cron","priority","max_attempts","end_at","last_materialized",
    "created_at"}` (`end_at`/`last_materialized` null when unset).
    Exit 0.

- `q unschedule ID`
  - Unknown schedule id: exit 4. Remove the schedule (jobs already
    materialized from it are NOT removed). Print the schedule id,
    exit 0.

- Materialized occurrences: each due occurrence becomes a regular job
  with `run_at` = occurrence time, `created_at` = materialization time,
  and the schedule's `priority`/`max_attempts`. Its id is
  `{schedule_id}-{YYYYMMDDHHMM}` (UTC), which makes materialization
  idempotent: re-running it after a crash MUST NOT create duplicates,
  and `last_materialized` MUST advance atomically with the created jobs
  so no occurrence is skipped. On the first materialization, only
  occurrences at or after the schedule's creation time are considered
  (no backfill from before the schedule existed).

- `q extend-lease ID --lease SEC`
  - Unknown id: exit 4.
  - The job MUST have status `claimed`, otherwise stderr MUST contain
    `not claimed` and exit 3.
  - `--lease` MUST be > 0, otherwise exit 2.
  - Set `lease_expires_at = now + lease`. Print the job id, exit 0.

- `q compact`
  - Reclaim space used by the redundant storage: rewrite the durable state
    in compacted form so that the total bytes stored under `$QDATA_DIR`
    shrink. Print `ok`, exit 0.

- Any unknown command: exit 2.

## Exit codes

- 0: success
- 1: no jobs available (claim found no candidate)
- 2: usage / validation error
- 3: state conflict (complete/fail on a job that is not claimed)
- 4: not found (unknown job id)
