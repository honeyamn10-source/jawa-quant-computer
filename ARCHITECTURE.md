# Architecture

Jawa Quant Computer is a local, single-process agent platform. Its design
priorities are **hermetic, resumable, safe, and inspectable**: the agent has a
hard wall-clock and step budget, every decision and side effect is persisted,
and every action goes through a risk-classed authorization layer.

```
                          +--------------------------------------------------+
                          |                    Interfaces                     |
                          |  ui/web (vanilla JS)   cli.py (rich REPL)         |
                          +--------------------------+-----------------------+
                                                     |
                          +--------------------------v-----------------------+
                          |                  FastAPI server (api/server.py)   |
                          |   chat / tasks / approvals / jobs / memory / SSE  |
                          +--------------------------+-----------------------+
                                                     |
                          +--------------------------v-----------------------+
                          |                 AgentService (orchestrator)      |
                          |  planner -> DAG executor -> verifier -> reporter  |
                          +-----+------------+------------+------------+-----+
                                |            |            |            |
                          +-----v--+   +-----v--+   +-----v--+   +-----v--+
                          | Planner|   |Permissions|  |ModelRouter| | Scheduler |
                          | heuristic| | risk rules,| | mock/     | | once,     |
                          | + LLM  |   | approvals | | openai/   | | interval, |
                          +--------+   +-----+-----+ | ollama    | | cron      |
                                              |      +-----+-----+ +-----+-----+
                                              |            |             |
     +--------------------+        +----------v--+   +---- v-----+   +---v----+
     | Secret vault       |        | SkillRegistry|  |  Skills   |   | Worker |
     | Fernet + OS keyring|        |  (all tools) |  | fs, shell,|   | spawns |
     +--------------------+        +--------------+  | browser, |   | tasks  |
                                                     | git, ... |   +--------+
                                                     +-----+----+
                                              +-----------v------------+
                                              |  Storage: SQLite (WAL) |
                                              |  tasks, steps, events, |
                                              |  providers, jobs, ...  |
                                              +------------------------+
```

## Layering

- **`jqc.config`** — pydantic-settings `Settings` (env prefix `JQC_`, `.env` support).
- **`jqc.core`** — Pydantic schemas (tasks, steps, events, requests), errors,
  event types.
- **`jqc.storage`** — `Database` (SQLite WAL, migration ledger with
  `PRAGMA user_version`) and repository classes (`Tasks`, `Steps`, `EventLog`,
  `Providers`, `SchedulerRepo`, `Permissions`, `Approvals`, `Conversations`,
  `Memories`, `Activity`). JSON payloads are stored in `*_json` columns and
  decoded with `rows_to_dicts`.
- **`jqc.security`** — `PermissionManager` (fnmatch-style rules with
  low/medium/high risk classes and allow/deny/ask policies; no rule = risk-based
  default), `ApprovalService`, and `SecretStore` (Fernet vault keyed by the OS
  keyring, writing a `0600` file as fallback) plus exact-string and
  key:value redaction for all logging/UI output.
- **`jqc.models`** — provider abstraction (`ModelProvider`), adapters for
  OpenAI-compatible `/v1/chat/completions`, Ollama-native `/api/chat`, and the
  deterministic `MockProvider`; `ModelRouter` handles default/health fallback.
- **`jqc.skills`** — skills expose `ToolDef`s (name, description, JSON schema,
  risk). The browser skill has two drivers: `PlaywrightDriver` (real Chromium)
  and `MockDriver` (canned responses, offline default).
- **`jqc.orchestrator`** — the `AgentService` (execute one task via a DAG—
  currently linear / one-parent-one-child—with verification), `Planner`
  (heuristic first for deterministic demo plans, LLM JSON otherwise), `Verifier`.
- **`jqc.scheduler`** — timezone-aware schedule math (`once`, `interval`,
  `cron`) plus a `SchedulerService` that polls the `scheduled_jobs` table and
  enqueues due jobs as new tasks through the agent.
- **`jqc.api`** — FastAPI application factory (`create_app`), SSE stream,
  static UI mount of `ui/web`, and the CORS/Auth-agnostic loopback surface.
- **`jqc/cli.py`** — rich terminal REPL layered over the same services.

## Execution flow

1. `POST /api/chat` (or CLI) → `AgentService.submit`.
2. `Planner.plan` produces a `Plan` (steps `tool`/`action`/`params`/`deps`).
   Demo mode prefers the heuristic planner for deterministic plans; a real
   provider falls back to an LLM-generated JSON plan.
3. Steps are topologically ordered and executed in order. Each step:
   - resolves its resource (`filesystem` path, browser URL, shell command…),
   - asks `PermissionManager.check`; `ask`-policy steps open an approval
     request and block until decided,
   - runs the skill within global runtime/step budgets,
   - is verified (`Verifier`) and its evidence propagates to downstream steps
     via `{{step_id.field}}` template substitution,
   - emits a structured event (bus → SSE clients, ring-buffer history, DB).
4. Every task emits `event_log` rows and an activity record; results are stored
   on the task row.

## Scheduling

Jobs live in `scheduled_jobs`. `SchedulerService` polls for jobs whose
`next_run_at <= now` (and a per-job lock to avoid double fire), computes the
next occurrence (`once` = done, `interval`/`cron` = compute and store), then
submits a task with the job prompt. Retry policies are stored per job and
applied on task failure.

## Security model

Actions are risk-classed:

| Risk | Examples | Default disposition |
| --- | --- | --- |
| `low` | read, list, open, status | allowed, no approval |
| `medium` | write, run, send | allowed after prompt-mode confirmation only if configured |
| `high` | delete, git push, shell with dangerous patterns, download+execute | approval always |

Rules can override defaults per tool/action pattern (`allow` / `deny` / `ask`).
No wildcard catch-all is ever implicit. Secrets (live values and
`key: value`/`Bearer <token>` patterns) are redacted from all logs, events, and
UI output, and the vault stores keys encrypted with Fernet.

## Interfaces

- **Server** — `src/jqc/api/server.py` (`app = create_app()`, `run()`).
  Endpoints: `chat`, `tasks` (+`cancel`), `approvals` (+`decide`), `jobs` (+`run-now`,
  `cancel`), `providers` (+`test`, `default`), `memory`, `permissions`, `skills`,
  `files`, `computer`, `activity`, `events/stream` (SSE), `acting`.
- **UI** — static files in `ui/web` (`index.html`, `app.js`, `style.css`) mounted at `/`.
- **CLI** — `jqc.cli:main` REPL with slash-commands for approvals, memory,
  providers, scheduler, permissions, logs.

## Conventions

- Asyncio throughout; the synchronous Playwright browser driver runs in a worker thread.
- Blogged events: typed `Event` records (task/step/approval lifecycle).
- No implicit wildcard privileges; every new skill must declare `ToolDef` risk.
- DateTime fields are ISO-8601 UTC; triggers may name an IANA timezone.