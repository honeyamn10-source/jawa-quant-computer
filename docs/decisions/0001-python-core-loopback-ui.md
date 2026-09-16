# ADR 0001: Python asyncio core with loopback web UI

- Status: Accepted
- Date: 2026-09-16

## Context

The project must be a self-contained "AI computer" the user runs locally. The
hard constraints in the build environment were: **no Node.js / npm**, Linux with
a working Python toolchain, and the requirement to push the finished repo to
GitHub. A native desktop shell (e.g. Tauri/React) was considered but would have
required Node for build tooling.

## Decision

- Core: **Python 3.11+** with **asyncio** and FastAPI.
- Interfaces: a **rich terminal REPL** and a **loopback web UI** (vanilla JS
  served by the same FastAPI app over SSE).
- A desktop shell is deferred until a maintainer can provision a Node toolchain
  (tracked in ROADMAP).

## Consequences

- One process, one language, one event loop → no IPC boundary.
- The web UI communicates only with `127.0.0.1`; the SSE stream is the only
  push channel.
- Desktop packaging is future work; the core API contract is web-first so a
  native shell can be bolted on later.