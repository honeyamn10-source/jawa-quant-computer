# Roadmap

Targets are ordered by expected value per effort. Items below are not promises,
just the current plan. Check ARCHITECTURE.md / ADRs for foundational context.

## Now (post-P0)

- [ ] **Desktop shell**: provision Node toolchain and wrap the server in a Tauri
      (or Electron) app so the loopback UI becomes a native window.
- [ ] **Ollama first-class docs**: an air-gapped "no internet at all" runbook
      (Ollama + playwright + zero hosted services).
- [ ] **Approvals in the UI**: richer approval cards with diff-style action review.

## Soon

- [ ] **LLM planning hardening**: JSON-schema-validated tool plans end to end, plan
      repair on parse failure, plan diff display before execution.
- [ ] **Multiple users / sessions**: per-session workspaces and permissions so a
      hosted deployment becomes possible safely.
- [ ] **Agent "explain myself" layer**: step-level commentary emitted to SSE so the
      UI reads like a transcript, not a log.
- [ ] **Deeper website interaction**: form filling, downloads, cookie consent
      handling, `browser.click/type` coverage in acceptance flows.

## Later

- [ ] **Vision agents / screenshots**: browser screenshots, image-input providers,
      and Claude/GPT-class multimodal round-trips.
- [ ] **Plugins**: skill packages loadable via a declarative manifest (like the
      existing `ToolDef` system) without touching core code.
- [ ] **Distributed scheduler leader**: cron-with-leases so a single shared DB can
      coordinate runs on more than one host.
- [ ] **Immutable audit trail**: hashed event chain (Merkle-style) so the
      "computer" can prove what it did.

## Done in 0.1.0

- Python asyncio core + loopback web UI (ADR-0001)
- Deterministic mock provider default (ADR-0002)
- Workspace-scoped filesystem + risk-classed permissions (ADR-0003)
- SQLite WAL + migration ledger (ADR-0004)
- Browser→file, folder→file→read-back, scheduler acceptance flows
- 55-test hermetic suite; CI matrix; release workflow