## What

Short description of the change and why.

## Verification

- [ ] `ruff check src tests`
- [ ] `pytest` (full hermetic suite)
- [ ] `python scripts/smoke.py`
- [ ] `python -m compileall -q src`

## Checklist

- [ ] New skill actions declare a risk class on their `ToolDef`.
- [ ] No secrets/keys in the diff (`.env`, `.env.*` are gitignored).
- [ ] Schema changes are added to `MIGRATIONS` (existing migrations untouched).
- [ ] DateTime handling is ISO-8601 UTC / IANA timezone aware.
- [ ] Acceptance flows (browser→file, folder→file→read-back, scheduler) still pass.

Closes #issue