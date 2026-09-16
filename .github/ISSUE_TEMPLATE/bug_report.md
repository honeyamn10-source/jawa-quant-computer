---
name: Bug report
about: Report something that broke or behaved unexpectedly
title: ""
labels: bug
assignees: ""
---

## Summary

A clear, one-sentence description of the bug.

## Reproduction

Provide exact steps. If reproducible purely in demo mode, please confirm
`JQC_BROWSER_DRIVER=mock` and no provider configured:

```bash
python scripts/smoke.py
```

1. Step one
2. Step two
3. See the error

## Expected

What you expected to happen.

## Actual

What actually happened (paste error text / task JSON / events).

## Environment

- OS / version:
- Python version:
- `pip show jawa-quant-computer` version (or commit):
- Browser driver used (mock / playwright):
- Provider configured (mock / openai / ollama):

## Logs

Redact anything secret first. Attach `JQC_DATA_DIR/*.log` or the last SSE events.

> Security issue? Follow SECURITY.md — do not post exploit details publicly.