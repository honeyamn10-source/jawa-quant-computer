# ADR 0002: Deterministic mock provider as the default runtime

- Status: Accepted
- Date: 2026-09-16

## Context

Real LLM providers need API keys, spend money, and make CI and demos
non-deterministic. The acceptance flows must be automatically verifiable with
no external services.

## Decision

The **MockProvider** is the default model. `ModelRouter` picks the default
provider; demo mode is the fallback if none is configured:
- Mock chat returns canned, deterministic replies designed to round-trip tool
  evidence (e.g. a page title the planner substituted back into a file).
- Real providers (OpenAI-compatible, Ollama) are supported behind the same
  `ModelProvider` interface and can be promoted to default via
  `POST /api/providers/{id}/default`.

## Consequences

- CI and `scripts/smoke.py` run everywhere with no keys and no network.
- Browser flows test the `MockDriver` by default; the real Playwright driver is
  a separate CI job so the actual mechanics are still continuously verified.
- The limit: demo plans are heuristic and don't exercise LLM creativity, which
  is acceptable for the P0 slice.