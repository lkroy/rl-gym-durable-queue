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
  - First, sweep expired leases: any job with status `claimed` and
    `lease_expires_at <= now` returns to `pending`, with `claimed_at` and
    `lease_expires_at` cleared. Idempotency mappings whose lease has
    expired are discarded in the same sweep.
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
