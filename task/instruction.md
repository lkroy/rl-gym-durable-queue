# Durable Job Queue — `q`

## Goal

Build a single-executable command-line program named `q` that workers use as
a durable, crash-safe job queue: enqueue work, claim it under a lease,
complete or fail it, and keep every acknowledged job intact across process
deaths, concurrent workers, and operator control (pause / drain / cancel).

Python 3, standard library only. Place the executable at the solution root
(invoked as `./q` or via an absolute path). It MUST be executable
(`chmod +x`).

## User outcomes

Operators and workers must be able to:

- **Enqueue and batch-enqueue** work with priorities, delays, dedupe keys,
  TTLs, tags, and dependency edges.
- **Claim** ready work (single or multi), **complete** it with a result, or
  **fail** it with exponential backoff / dead-lettering.
- **Survive crashes**: once a command exits 0, its effects remain visible
  after SIGKILL of any later process; an interrupted command never leaves
  the queue unreadable or half-applied.
- **Avoid double delivery**: concurrent claimants never receive the same
  job twice; fencing tokens reject stale workers after reclaim.
- **Pause / drain / resume** the queue for operational control without
  losing in-flight or already-enqueued work.
- **Schedule** recurring jobs (cron, timezone-aware) that materialize as
  ordinary jobs when due.
- **Cancel** pending work (optionally cascading through dependents) and
  partition work with **tags**.

## Competing requirements (tension)

These goals pull in opposite directions; a correct `q` satisfies all of
them observably:

- **Reclaim disk** (`q compact` must shrink bytes under `$QDATA_DIR`) vs
  **never lose jobs** (compact mid-SIGKILL still keeps every acknowledged
  job; single-file loss while idle still leaves the queue intact).
- **Pause blocks new claims** vs **in-flight idempotent retries still
  work**: while paused, a new claim fails with `queue paused`, but
  `claim --idempotency-key KEY` that maps to a currently claimed,
  unexpired job MUST return that same job (same fence, lease not
  extended).
- **Erase / cancel** pending work (and optional cascade) without harming
  unrelated jobs, claimed dependents, or siblings that do not depend on
  the cancelled root.
- **Durable redundancy** (survive loss of any one state file while idle)
  vs **compact** storage after growth.

## Rules

How state is stored under `$QDATA_DIR` is entirely up to you — names,
formats, and structures are your design. What is graded is that these
**outcomes** hold:

### State directory

- The state directory comes from the `$QDATA_DIR` environment variable.
  If unset, default to `./.qdata` (relative to the current working
  directory).
- The program MUST create the state directory if it does not exist.

### Durability, crash safety, concurrency, redundancy

- **Durability**: once a command has exited 0, its effects MUST survive
  the process being killed (SIGKILL) at any later moment. Effects are
  not considered successful until they will outlive that kill.
- **Crash atomicity**: if a `q` process is killed (SIGKILL) in the middle
  of ANY command, the queue MUST NOT be left half-written or unreadable.
  The very next `q` invocation MUST exit 0 and see every previously
  acknowledged job intact; the interrupted operation itself MUST have
  taken effect at most once (fully completed or not at all — never
  partially, never duplicated).
- **Redundancy**: the queue must keep every acknowledged job intact and
  remain fully operational even if any single file under the state
  directory is lost while no `q` process is running. No single file may
  be a single point of failure for acknowledged work.
- **Torn writes**: a crash can interrupt a write at any byte, leaving a
  state file with a partially-written trailing record. The next command
  MUST recover automatically — discarding the partial data, keeping every
  acknowledged job intact, and exiting 0.
- **Compact**: `q compact` MUST preserve every job, whatever its status,
  and MUST reduce the total bytes stored under `$QDATA_DIR` once the
  queue has grown through many operations. A process killed (SIGKILL) in
  the middle of `q compact` MUST NOT lose any acknowledged job.
- **Concurrency**: multiple `q` processes running at the same time MUST
  NEVER deliver (claim) the same job twice, and concurrent mutations MUST
  NOT corrupt the queue.

## Background obligations

Before a command's own effects become visible, the following background
work MUST already have been applied as part of that same successful
command (one observable unit with the command). These obligations still
apply when the queue is paused and when it is draining.

- **Due schedules materialize**: for each schedule, every occurrence with
  time <= now and time > that schedule's `last_materialized` becomes one
  pending job; `last_materialized` advances to the latest materialized
  occurrence. Materialization is idempotent across crashes (no duplicate
  jobs for the same occurrence; no skipped occurrence once acknowledged).
- **Expired leases reclaim**: any `claimed` job with
  `lease_expires_at <= now` returns to `pending` (clearing `claimed_at` /
  `lease_expires_at`), unless it is also past its TTL (see next).
  Idempotency mappings whose lease expired are discarded.
- **TTLs expire**: any job with a non-null `ttl` where
  `now - created_at > ttl` and status is `pending` becomes `dead` with
  `last_error` exactly `"expired"`. A `claimed` job is exempt while its
  lease is valid; if its lease has expired it is `dead` (not requeued).
- **Dependency-failure cascades**: any `pending` job whose ANY dependency
  has status `dead` becomes `dead` with `last_error` exactly
  `"dependency failed"`. Repeat until fixpoint through the depends_on
  graph.

**Ordering rule (TTL before dep-cascade):** a waiter with its own TTL that
expires becomes `dead` with `last_error` `"expired"` even if its
dependency is still `pending`. TTL expiry is applied before the
dependency-failure cascade, so that waiter is not marked
`"dependency failed"`.

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
| fence              | int               | 0 (see Fencing tokens)             |
| depends_on         | list of job ids   | []                               |
| tag                | string or null    | null                             |
| last_error         | string or null    | null                             |
| result             | any JSON or null  | null                             |

`status` is one of `pending`, `claimed`, `done`, `dead`.

Every job always carries `depends_on` (a list of job ids it waits on;
default `[]`) and `tag` (string or null; default `null`).
Schedule-materialized jobs always get `depends_on: []` and `tag: null`.
`show` and `claim` output always include `depends_on` and `tag`.

## Fencing tokens

Every job carries a `fence`: a non-negative integer, starting at 0. It is
incremented by exactly 1 on EVERY transition of the job into `claimed`
— the first claim, a reclaim after lease expiry, a claim after a
`fail`-requeue. It is never decremented, and `extend-lease` does NOT
change it. A repeat `claim` served from an existing idempotency-key
mapping returns the same job with the same fence (it is the same claim,
not a new transition).

The fence is printed as part of the job object in `claim` output. Any
command that mutates a claimed job — `complete`, `fail`,
`extend-lease` — REQUIRES `--fence F`, the fence value the caller saw
when it claimed the job:

- `--fence` missing, or not a non-negative integer → exit 2.
- Unknown job id → exit 4 (checked before the fence).
- Job not `claimed` → stderr MUST contain `not claimed`, exit 3.
- Fence does not equal the job's current fence → stderr MUST contain
  `stale fence`, exit 3. The job is left untouched.

The guarantee this buys: a worker that claimed a job, lost its lease
(crash, slowness), and then tries to `complete` / `fail` /
`extend-lease` AFTER another worker has reclaimed the job MUST be
rejected — its fence is stale, and the new holder's work is protected.

## Pause / resume / drain

Queue meta is `{paused: bool, draining: bool}` (both default false).
Both flags MUST be durable (survive process restart and crash) along with
the rest of acknowledged queue state.

- `q pause` — set paused=true, print `paused`, exit 0. Idempotent.
- `q drain` — set draining=true, print `draining`, exit 0. Idempotent.
- `q resume` — clear BOTH paused and draining, print `resumed`, exit 0.
  Idempotent.
- While paused: a **new** `q claim` MUST exit 1 and stderr MUST contain
  `queue paused` (even if claimable candidates exist). Do NOT claim a
  new job. **Exception (CRITICAL):** if `claim --idempotency-key KEY`
  and KEY maps to a job that is currently `claimed` with an unexpired
  lease, return THAT job (same fence), exit 0. Do NOT extend the lease.
  This is a retry of in-flight work, not a new claim. Any other key (or
  no key) while paused → `queue paused`.
- Pause does **not** prevent `complete` or `fail` of an already-claimed
  job (with a valid fence).
- Drain does **not** remove or alter already-enqueued jobs; they remain
  claimable (subject to the usual candidate rules and pause).
- While draining: `enqueue`, `enqueue-batch`, and `schedule` MUST exit 3
  and stderr MUST contain `draining` (create nothing). claim / complete /
  fail / cancel / list / show / stats / compact / unschedule / pause /
  extend-lease still work while draining.
- If both paused and draining: claim uses the pause rule (`queue paused`,
  exit 1, with the idempotency-key exception above) — pause wins over
  drain for claim.
- Enqueue, complete, fail, schedule, cancel, list, show, stats, compact
  (and the other non-claim mutations) still work while paused (but
  enqueue/enqueue-batch/schedule are blocked while draining).

## CLI contract

All JSON printed to stdout MUST be parseable JSON. Validation failures MUST
print a message to stderr.

- `q enqueue --payload JSON [--priority INT] [--delay SEC] [--id ID]
  [--dedupe-key KEY] [--max-attempts N] [--ttl SEC]
  [--depends-on ID[,ID...]] [--tag TAG]`
  - On success: print the job id followed by a newline to stdout, exit 0.
  - While draining: exit 3, stderr MUST contain `draining`, create nothing.
  - `--payload` MUST be valid JSON, otherwise exit 2.
  - `--id`, when given, MUST match `^[A-Za-z0-9_-]{1,64}$`, otherwise exit 2.
  - `--id` MUST NOT duplicate an existing job id, otherwise exit 2.
  - `--delay` MUST NOT be negative, otherwise exit 2. `run_at` is set to
    `created_at + delay` (default delay 0).
  - `--max-attempts` MUST be >= 1, otherwise exit 2.
  - `--ttl`, when given, MUST be > 0, otherwise exit 2. The job expires
    `ttl` seconds after `created_at` (see Background obligations). A
    delayed job can expire before ever becoming claimable.
  - `--tag TAG`, when given, MUST match `^[A-Za-z0-9_-]{1,32}$`, otherwise
    exit 2. Stored as the job's `tag` (default `null` when omitted).
  - `--depends-on` is a comma-separated list of job ids this job waits
    on (stored as `depends_on`). Validation failures exit 2:
    - unknown dependency id
    - self-dependency (an id equal to this job's id)
    - a cycle in the depends_on graph (including existing jobs); stderr
      MUST contain `cycle`
    - an empty token in the list (e.g. `a,,b` or a trailing/leading comma)
  - Dedupe: if `--dedupe-key` is given and a job with the same key exists
    with status `pending` or `claimed`, print THAT job's id, exit 0, and
    create nothing. Deduping is **global** (not per-tag). A key whose
    previous job is `done` (or `dead`) does NOT block a new enqueue.

- `q enqueue-batch --jobs '<json-array>'`
  - Enqueue many jobs atomically: either ALL of them are created or NONE
    is. `--jobs` MUST be a JSON array, otherwise exit 2.
  - While draining: exit 3, stderr MUST contain `draining`, create nothing.
  - Each element is an object with `payload` (required, any JSON) and
    optional `priority`, `delay`, `id`, `dedupe_key`, `max_attempts`,
    `depends_on` (a JSON array of job ids; same meaning as enqueue's
    `--depends-on`), `tag` (string matching `^[A-Za-z0-9_-]{1,32}$`, or
    omit/`null`). Validate EVERY element before creating anything:
    any invalid element (bad JSON types, bad `id` format, duplicate `id`
    within the batch or against existing jobs, negative `delay`,
    `max_attempts` < 1, missing `payload`, bad `depends_on`, bad `tag`)
    aborts the whole batch with exit 2 and creates NOTHING.
  - `depends_on` may reference existing jobs OR other elements' ids in
    the same batch; after dedupe resolution use the resolved id. Validate
    cycles including the batch-as-a-whole before creating anything; if
    invalid, create NOTHING (exit 2, stderr contains `cycle` when the
    failure is a cycle).
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

- `q claim [--lease SEC] [--idempotency-key KEY] [--count N] [--tag TAG]`
  (defaults: lease 60, count 1)
  - `--lease` MUST be > 0, otherwise exit 2.
  - `--count` MUST be an integer >= 1, otherwise exit 2. With `--count N`,
    up to N candidates are claimed atomically, in claim order; each one
    gets `claimed_at = now`, `lease_expires_at = now + lease`, and its
    fence incremented. The whole multi-claim is one atomic unit:
    concurrent `claim` invocations MUST NEVER deliver the same job twice,
    whatever `--count` each used.
  - `--tag TAG`, when given, MUST match `^[A-Za-z0-9_-]{1,32}$`, otherwise
    exit 2.
  - `--idempotency-key`, when given, MUST match `^[A-Za-z0-9_-]{1,64}$`,
    otherwise exit 2. It is only valid with the default `--count 1`;
    combining it with `--count` > 1 is exit 2.
  - Background obligations run as part of the command (materialize due
    schedules, reclaim expired leases, expire TTLs, cascade dependency
    failures) before the claim decision is visible.
  - If KEY is given and maps to a job that is currently `claimed` with an
    unexpired lease, return THAT job (full JSON, same fence), exit 0. Do
    NOT claim a new job and do NOT extend the lease. This gives
    exactly-once delivery across client retries and crashes, **and it
    applies even while the queue is paused** (see Pause / resume / drain).
  - Otherwise, if the queue is paused: stderr MUST contain `queue paused`,
    exit 1. Do NOT claim a new job (even when candidates exist). Pause
    wins over drain for claim.
  - Otherwise claim the best candidate(s) as usual; if a candidate is
    claimed, record KEY as mapped to it (replacing any stale mapping).
    Mappings for jobs that become `done` or `dead` are discarded, so a
    later claim with the same KEY starts fresh.
  - The mapping MUST be durable (survive crashes) and MUST be safe under
    concurrency: two processes claiming at the same time with the same
    KEY MUST receive the same job, never two different jobs.
  - Candidates: status `pending` AND `run_at <= now` AND every id in
    `depends_on` refers to a job whose status is `done` AND the tag
    filter matches:
    - Without `--tag`: ONLY jobs whose `tag` is `null`.
    - With `--tag TAG`: ONLY jobs whose `tag` equals TAG (exact).
    This is a hard partition: an untagged claim never sees tagged jobs
    and a tagged claim never sees untagged jobs. depends_on / priority /
    run_at / pause / drain still apply on top of the tag filter.
  - Completing a tagged job MUST NOT affect an untagged pending job (it
    remains claimable via untagged claim). Completing an untagged job
    likewise MUST NOT affect tagged pending jobs.
  - A higher-priority job blocked on unmet dependencies MUST NOT prevent
    claiming a lower-priority job whose dependencies are satisfied.
    With `--count N`, skip unmet deps and fill up to N from ready jobs
    after filters. If zero ready after filters → exit 1
    `no jobs available` (or the queue-paused rule first).
  - Order: `priority` descending, then `created_at` ascending, then `id`
    ascending. Claim the first candidate(s): set status `claimed`,
    `claimed_at = now`, `lease_expires_at = now + lease`, bump the fence.
  - Print the full job object as JSON (for `--count N`, a JSON array of
    the claimed job objects in claim order), exit 0. The job object
    includes `depends_on` and `tag`.
  - If no candidate: stderr MUST contain `no jobs available`, exit 1.

- `q complete ID --fence F [--result JSON]`
  - `--fence` is REQUIRED (see Fencing tokens): missing or not a
    non-negative integer → exit 2.
  - Unknown id: exit 4.
  - The job MUST have status `claimed`, otherwise stderr MUST contain
    `not claimed` and exit 3.
  - The fence MUST equal the job's current fence, otherwise stderr MUST
    contain `stale fence` and exit 3.
  - `--result` MUST be valid JSON when given, otherwise exit 2.
  - Set status `done`, store `result`, print the job id, exit 0.

- `q fail ID --fence F [--error MSG]`
  - `--fence` is REQUIRED (see Fencing tokens): missing or not a
    non-negative integer → exit 2.
  - Unknown id: exit 4.
  - The job MUST have status `claimed`, otherwise exit 3.
  - The fence MUST equal the job's current fence, otherwise stderr MUST
    contain `stale fence` and exit 3.
  - Increment `attempts`. If `attempts >= max_attempts`, status becomes
    `dead`. Otherwise status becomes `pending` with
    `run_at = now + 10 * 2**(attempts-1)` (10s, 20s, 40s, ...), and
    `claimed_at` / `lease_expires_at` are cleared. `last_error` is set to
    MSG (or null). (The fence is NOT reset: it bumps again on the next
    claim.)
  - Print the job id, exit 0.

- `q stats`
  - Print `{"pending":n,"claimed":n,"done":n,"dead":n,"total":n}`, exit 0.

- `q schedule --payload JSON --cron EXPR [--id ID] [--priority INT]
  [--max-attempts N] [--end-at EPOCH] [--tz NAME]`
  - While draining: exit 3, stderr MUST contain `draining`, create nothing.
  - Creates a recurring schedule. `--payload` MUST be valid JSON,
    otherwise exit 2. `--id`, when given, MUST match
    `^[A-Za-z0-9_-]{1,64}$` and MUST NOT duplicate an existing schedule
    id, otherwise exit 2. `--max-attempts` MUST be >= 1, otherwise exit 2.
  - `--tz` names the timezone the cron expression is evaluated in: an
    IANA timezone name (e.g. `America/New_York`), default `UTC`. An
    unknown timezone name → exit 2.
  - `--cron` is a 5-field expression `minute hour dom month dow`
    evaluated against the local wall-clock in `--tz`. Each field accepts
    `*`, `*/step`, `a-b`, `a-b/step`, `a,b,c`, or a single value.
    Ranges: minute 0-59, hour 0-23, dom 1-31, month 1-12, dow 0-6 (0 and
    7 both mean Sunday). Any malformed field or out-of-range value →
    exit 2. A date that never exists (e.g. Feb 30) simply never matches.
  - Matching rule: an occurrence exists at each minute where minute,
    hour and month match, and (dom matches OR dow matches) — with the
    standard refinement that if one of dom/dow is `*` (unrestricted),
    the other alone decides.
  - Daylight-saving transitions in `--tz`:
    - Local times that do not exist (spring-forward gap, e.g. 02:30 on
      the day clocks jump forward) are SKIPPED: no job is materialized
      for them.
    - Ambiguous local times (fall-back overlap, e.g. 01:30 occurring
      twice) materialize EXACTLY ONE job, at the first occurrence.
  - `--end-at`, when given, is an epoch timestamp: occurrences at or
    after it are never materialized.
  - On success: print the schedule id, exit 0.

- `q schedules`
  - Print a JSON array of schedule summaries, one per schedule:
    `{"id","cron","tz","priority","max_attempts","end_at",
    "last_materialized","created_at"}` (`end_at`/`last_materialized`
    null when unset). Exit 0.

- `q unschedule ID`
  - Unknown schedule id: exit 4. Remove the schedule (jobs already
    materialized from it are NOT removed). Print the schedule id,
    exit 0.

- Materialized occurrences: each due occurrence becomes a regular job
  with `run_at` = occurrence time (epoch seconds; for an ambiguous local
  time, the first occurrence), `created_at` = materialization time,
  and the schedule's `priority`/`max_attempts`. Its id is
  `{schedule_id}-{YYYYMMDDHHMM}` using the occurrence's LOCAL wall-clock
  in the schedule's timezone, which makes materialization idempotent:
  re-running it after a crash MUST NOT create duplicates, and
  `last_materialized` MUST advance together with the created jobs so no
  occurrence is skipped. On the first materialization, only occurrences
  at or after the schedule's creation time are considered (no backfill
  from before the schedule existed).

- `q extend-lease ID --fence F --lease SEC`
  - `--fence` is REQUIRED (see Fencing tokens): missing or not a
    non-negative integer → exit 2.
  - Unknown id: exit 4.
  - The job MUST have status `claimed`, otherwise stderr MUST contain
    `not claimed` and exit 3.
  - The fence MUST equal the job's current fence, otherwise stderr MUST
    contain `stale fence` and exit 3. (A worker whose lease expired and
    whose job was reclaimed by someone else cannot extend the new
    holder's lease.)
  - `--lease` MUST be > 0, otherwise exit 2.
  - Set `lease_expires_at = now + lease`. The fence is NOT changed.
    Print the job id, exit 0.

- `q compact`
  - Reclaim space used by durable redundancy: rewrite state so that the
    total bytes stored under `$QDATA_DIR` shrink, while preserving every
    job. Print `ok`, exit 0.

- `q pause` / `q drain` / `q resume`
  - See Pause / resume / drain above.

- `q cancel ID [--cascade]`
  - Unknown id → exit 4.
  - Target MUST have status `pending`, otherwise stderr MUST contain
    `not pending`, exit 3.
  - Sets status `dead`, `last_error` = `"cancelled"`, discards any
    idempotency mappings for the cancelled job(s), exit 0.
  - Without `--cascade`: print the id string followed by a newline.
  - With `--cascade`: also cancel (to `dead` / `"cancelled"`) every
    still-`pending` job that transitively depends on ID (directly or
    indirectly). Claimed dependents are NOT cancelled (they stay
    `claimed`). Print a JSON array of cancelled ids sorted by id
    ascending (include the root).
  - Cascade cancel of a root MUST NOT cancel or change an unrelated
    pending job (one that does not depend on the root, directly or
    indirectly). Cancelling one branch MUST NOT kill a sibling that does
    not depend on that branch.
  - Interaction with dependency failure: after a non-cascade cancel,
    dependents that were not cancelled remain `pending` until a later
    command's background obligations mark them `dead` with `last_error`
    `"dependency failed"`.

- Any unknown command: exit 2.

## Exit codes

- 0: success
- 1: no jobs available (claim found no candidate), or queue paused
- 2: usage / validation error
- 3: state conflict (complete/fail/extend-lease on a job that is not
  claimed, or presented with a stale fence token; cancel on a
  non-pending job; enqueue / enqueue-batch / schedule while draining)
- 4: not found (unknown job id)
