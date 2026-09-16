<p align="center">
  <img src="docs/assets/logo.svg" alt="jawa-quant-computer logo" width="100%" />
</p>


<p align="center">
</p>


# Jawa Quant Computer

An autonomous AI computer: a local agent operating layer that browses the web,
manages files, runs commands, uses your documents and memory, schedules jobs,
and can call your favourite LLM — all from a terminal REPL or a loopback web UI.

> **Alpha.** The core vertical slice is implemented and smoke-tested. Everything
> runs locally on your machine; nothing leaves it unless you configure a model
> provider and approve the specific action.

<div align="center">

| CI · lint | Tests | Python | License |
| --- | --- | --- | --- |
| [![CI](https://github.com/honeyamn10-source/jawa-quant-computer/actions/workflows/ci.yml/badge.svg)](https://github.com/honeyamn10-source/jawa-quant-computer/actions/workflows/ci.yml) | ![tests: 55 passing](https://img.shields.io/badge/tests-55%20passing-2ea44f) | ![python 3.11–3.13](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-3776ab) | [![MIT](https://img.shields.io/badge/license-MIT-4db5bd)](LICENSE) |

**Demo-first · loopback-only · permission-gated every action**

</div>

## Highlights

- **In-process agent orchestrator** — planner (heuristic for demo mode, LLM/JSON for real
  models), DAG step executor, goal verifier, step retries, max runtime/steps guardrails.
- **Skills** — `browser` (Playwright or deterministic mock driver), `filesystem`,
  `shell`, `git`, `documents`, `memory`, `search`, `research`, `computer`,
  `scheduler` (once / interval / cron schedule math, timezone aware).
- **Scheduling** — one-time and recurring jobs persist to SQLite and fire on time,
  producing new tasks through the same pipeline.
- **Provider adapters** — OpenAI-compatible API, Ollama (native), and a deterministic
  `mock` provider so the whole system works offline with no keys.
- **Security model** — risk-classed actions (`low` / `medium` / `high`) with explicit
  allow / deny / ask approval rules, exact-secret redaction, and an encrypted secret
  vault (OS keyring with a 0600 file fallback).
- **Storage** — SQLite (WAL), row-level migration ledger, repos for tasks, steps,
  event log, approvals, providers, jobs, memories, activity.
- **Interfaces** — FastAPI server with SSE event stream, a vanilla-JS loopback web UI,
  and a rich terminal REPL (`jawa-quant-computer`).
- **Tests** — 50+ hermetic tests (unit, provider integration against in-process mock
  OpenAI/Ollama servers, API via TestClient, end-to-end acceptance flows, security).
  CI matrix across Python 3.11–3.13 and Linux / Windows / macOS.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"                             # includes web deps + browser

# demo mode — everything works, no keys, no network
jawa-quant-computer                                 # rich terminal REPL

# loopback web UI
uvicorn jqc.api.server:app --host 127.0.0.1 --port 8765
# open http://127.0.0.1:8765
```

For a **real browser model**, install Chromium and point `JQC_BROWSER_DRIVER=playwright`:

```bash
python -m playwright install --with-deps chromium
JQC_BROWSER_DRIVER=playwright jawa-quant-computer
```

For **real LLM** providers, register one from the UI or CLI. OpenAI-compatible and
Ollama endpoints are supported; API keys are stored encrypted in the OS keyring.

## The acceptance flows

The three flows that define the P0 slice are tested end to end in
`tests/test_e2e_flows.py` and verified live by `scripts/smoke.py`:

1. **Browser → file** — open `https://example.com`, capture the page title, save it
   into a text file.
2. **Folder → file → read-back** — create a folder, write `notes.txt` inside it,
   read it back.
3. **Scheduler** — schedule a one-time job a few minutes in the future; the scheduler
   fires it and the job creates its file.

```bash
python scripts/smoke.py        # demo mode, deterministic, no keys or network
```

## Configuration

Settings are read from environment variables (prefix `JQC_`) or a local `.env` file.
See `.env.example` for the full list. Key ones:

| Variable | Default | Meaning |
| --- | --- | --- |
| `JQC_DATA_DIR` | `./jqc-data` | SQLite, vault, logs |
| `JQC_WORKSPACE_DIR` | `./jqc-workspace` | Root the agent may freely read/write |
| `JQC_BROWSER_DRIVER` | auto | `mock`, `playwright`, or unset (auto-detect) |
| `JQC_DEMO_MODE` | `true` | Fall back to mock provider |
| `JQC_APPROVAL_MODE` | `prompt` | `prompt` / `auto` (alien mode) |
| `JQC_BROWSER_HEADLESS` | `true` | Run Chromium headless |
| `JQC_MAX_RUNTIME_SECONDS` | `600` | Per-task wall-clock budget |
| `JQC_MAX_STEPS_PER_TASK` | `20` | Per-task step budget |

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — modules, data flow, security model.
- [docs/decisions](docs/decisions) — architecture decision records.
- [SECURITY.md](SECURITY.md) — threat model, permissions, vault, redaction policy.
- [CONTRIBUTING.md](CONTRIBUTING.md) — workflow, test/CI commands.
- [CHANGELOG.md](CHANGELOG.md) — releases.
- [ROADMAP.md](ROADMAP.md) — near-term targets.

## Development

```bash
pip install -e ".[dev]"
ruff check src tests
pytest
```

## License

MIT — see [LICENSE](LICENSE).