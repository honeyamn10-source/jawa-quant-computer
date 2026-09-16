# ADR 0004: SQLite (WAL) with a sequential migration ledger

- Status: Accepted
- Date: 2026-09-16

## Context

Tasks, steps, events, providers, jobs, approvals, memories, permissions and
activity must survive restarts and be queryable by the "computer" itself. A
full RDBMS is overkill for a single-user local process; ad-hoc JSON files don't
support the concurrency the scheduler needs.

## Decision

- **SQLite** in WAL mode as the single storage engine (`jqc/storage/db.py`).
- A **migration ledger** driven by `PRAGMA user_version`: ordered lists of SQL
  statements applied transactionally, each bumping the version. Starting a new
  feature means appending a migration, never editing old ones.
- Repositories expose row-to-dict helpers (`rows_to_dicts`) so JSON columns are
  decoded at the edge and application code works with plain dicts.

## Consequences

- Concurrent readers + single writer works with the scheduler thread and API
  thread without extra locking rules.
- Future schema changes are reviewable as diffs in `MIGRATIONS`.
- WAL files are short-lived; the `.gitignore` excludes DB artifacts so they
  don't leak into a public repo.