# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-09-16

### Added
- Core agent service: heuristic + LLM/JSON planner, DAG step executor, goal
  verifier, step retries, per-task runtime (600s) and step (20) budgets,
  cancellation, and approval-gated execution.
- Skills: `browser` (Playwright + offline deterministic mock driver),
  `filesystem`, `shell` (bounded, capture, `$WS` env), `git`, `documents`,
  `memory`, `search`, `research`, `computer`, `scheduler`.
- Scheduler: timezone-aware `once` / `interval` / `cron` math, persistent jobs,
  SchedulerService with per-job fire lock, run-now/cancel APIs.
- Provider adapters: OpenAI-compatible `/v1/chat/completions`, Ollama-native
  `/api/chat`, and the deterministic `mock` default provider; connection test,
  model listing, default-promotion, encrypted API-key storage.
- Storage: SQLite WAL with a `PRAGMA user_version` migration ledger;
  repositories for tasks, steps, events, approvals, providers, jobs, memories,
  conversations and activity.
- Security: risk-classed permissions (low/medium/high) with fnmatch rules
  (allow/deny/ask), persisted approvals with timeout, Fernet secret vault
  (OS keyring + 0600 fallback), exact-value and `key: value` redaction across
  logs/events/UI.
- Interfaces: FastAPI app (chat, tasks, approvals, jobs, providers, memory,
  permissions, skills, files, computer, activity, SSE events), vanilla-JS
  loopback web UI, and a `rich` terminal REPL (`jawa-quant-computer`).
- Tests: 55 hermetic tests — unit, provider integration against in-process mock
  OpenAI/Ollama servers, API via TestClient (incl. live SSE probe), and the
  three end-to-end acceptance flows.
- CI: ruff lint; pytest matrix (3.11/3.12/3.13 × linux/windows/macos); build +
  import check; real-Playwright smoke on `main`. Release workflow with
  version-bump dispatch and trusted PyPI publish.

### Fixed
- `Tasks.update` / `SchedulerRepo.update` used swapped `updated_at`/`id`
  parameters, silently keeping task statuses `queued`.
- `redact_text` failed to capture multi-token secret values.
- Live secret tracking skipped when the vault had a single entry.
- SQLite migrations raced before `user_version` was pinned.
- `compute_next` crashed on datetime `_last_run` values.