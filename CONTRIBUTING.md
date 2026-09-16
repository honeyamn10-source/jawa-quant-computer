# Contributing

Thanks for considering a contribution to Jawa Quant Computer.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Verification gate

Anything you change must keep the project green:

```bash
ruff check src tests      # lint + format checks
pytest                    # full hermetic suite (no keys / network required)
python scripts/smoke.py   # end-to-end acceptance flows in demo mode
python -m compileall -q src
```

The CI matrix reproduces these on Python 3.11–3.13 across Linux, Windows and
macOS, plus a real-Playwright smoke job on `main`.

## Conventions

- Asyncio everywhere; keep blocking I/O out of the event loop where practical.
- Every new skill action must declare a risk on its `ToolDef`. No implicit
  wildcard privileges.
- DateTime fields are ISO-8601 UTC; schedule triggers may use IANA timezones.
- Avoid comments unless they explain a non-obvious *why*.
- JSON columns are stored as `*_json`; use `rows_to_dicts` when reading.
- Schema changes go in `MIGRATIONS` — never edit an applied migration.
- Keep the acceptance flows (browser→file, folder→file→read-back, scheduler)
  passing; they are the product’s core contract.

## Branching & PRs

- Branch from `main`, keep PRs focused (one concern each).
- Reference the issue you close (e.g. `Closes #12`).
- CI runs on every PR; a red pipeline blocks merge.

## Scope notes

- The web UI is deliberately vanilla JS (no build step). Larger UI work that
  needs a bundler must first get Node provisioned (see ROADMAP).
- Secrets and test keys should never appear in commits — `.env.example` and
  `.env.*` are excluded.