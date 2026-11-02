# DST handling — white-box verification (2026-11-02)

The DST rules in the spec (`q schedule --tz`) are not black-box testable
without time control, so they were verified by calling the reference's
`_materialize` directly (loaded via `importlib.machinery.SourceFileLoader`
from `reference/q`) with fixed schedule dicts and controlled `t`.

Method: cron is matched against the local wall-clock obtained by iterating
UTC minute boundaries and converting with `zoneinfo` (`_utc_dt(m).astimezone(tz)`).
- Spring-forward gaps: a local wall time that does not exist is never
  produced by UTC→local conversion, so no job is materialized for it.
- Fall-back overlaps: the same wall clock is produced twice (two UTC
  minutes); `seen_wall` keeps only the first, so exactly one job is
  materialized with `run_at` = the first occurrence's epoch. The job id
  `{sid}-{local YYYYMMDDHHMM}` is identical for both, so crash-retry
  idempotency also holds.

## Case 1: gap is skipped
- tz = America/New_York, cron = `30 2 * * *`
- created_at = 2026-03-07T00:00Z, t = 2026-03-09T00:00Z
- 2026-03-08 is the spring-forward day (02:00 EST → 03:00 EDT)
- Result: 1 job total (the 2026-03-07 02:30 occurrence), **0 jobs** with id
  suffix `-202603080230`. PASS.

## Case 2: overlap materializes exactly one job at the first occurrence
- tz = America/New_York, cron = `30 1 * * *`
- created_at = 2026-10-31T00:00Z, t = 2026-11-02T00:00Z
- 2026-11-01 is the fall-back day (01:30 occurs twice: 05:30Z and 06:30Z)
- Result: exactly **1** job with id suffix `-202611010130`,
  `run_at` = 2026-11-01T05:30:00Z (the first occurrence). PASS.

## Case 3: UTC schedules unchanged
- tz = UTC, cron = `* * * * *`: every materialized job id equals
  `s-` + UTC `%Y%m%d%H%M` of its `run_at`. PASS (existing UTC schedule
  tests keep passing unchanged).
