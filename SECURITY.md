# Security

This document describes the threat model, the permission model, and what the
system does (and does not) protect.

## Scope

Jawa Quant Computer is a **single-user, local** execution environment. Its
assumptions are:

- The data directory (`JQC_DATA_DIR`) and workspace (`JQC_WORKSPACE_DIR`) belong
  to the user running the process.
- Model API keys are the user's own; no multi-tenancy, no remote agent.
- The web UI binds to loopback only (`127.0.0.1`).

## Threat model

| Threat | Mitigation |
| --- | --- |
| Prompt-injection via a fetched **web page** | Browser `snippet`/`open` return text only; pages are rendered in a headless Chromium context with no cookies by default; downloaded/executable content is classified `high` and requires approval. |
| Malicious or accidental **file destruction** | Filesystem writes are workspace-scoped (`_resolve` rejects outside paths); `delete`/`overwrite` are `high` risk and require approval. |
| **Shell misuse** | `shell.run` commands with dangerous patterns (mount, rm -rf, format, update, fork bomb…) are auto-classified `high` → approval; every command runs with a bounded timeout and `$WS`-relative env cue. |
| **Exfiltration** | Network access (web fetch, git push) is `high` risk; actions surface with the target URL/resource for explicit approval. |
| **Credential theft** | Keys live in a Fernet-encrypted vault whose master key is stored in the OS keyring (fallback `0600` file); live values are redacted from logs/events/UI. |
| **Model-exfiltration to a hosted model** | Only the messages/plan JSON are sent to providers; tools result evidence is included only for real-world reasoning, which is the intended design (a hosted agent sees function results) — run with a local Ollama model for fully-air-gapped use. |

## Permissions

Every skill action is classified by risk: `low` (allowed), `medium` (allowed
subject to the approval mode), `high` (always prompt unless an explicit rule
overrides). Rules are stored as fnmatch patterns:

```
risk      pattern   policy   example
high      filesystem.delete       ask
medium    filesystem.write        allow
low       filesystem.*            allow
```

- **deny** always wins, then the most specific (longest) rule, then the risk
  default.
- There is no implicit catch-all allow.
- `approval_mode=auto` may auto-approve `medium`; `high` still requires consent.

All decisions are recorded in the `permissions` + `approvals` tables and in the
event log with evidence.

## Secret vault

- `SecretStore` (`jqc/security/secrets.py`) encrypts every value with **Fernet**.
- The Fernet key is stored in the OS keyring (Windows Credential Manager /
  macOS Keychain / Linux Secret Service via `keyring`); if the keyring is
  unavailable the key is written to `<data_dir>/vault.key` chmod `0600`.
- `LIVE_SECRETS` tracks exact values currently stored; `redact_text` /
  `redact_dict` / `redacted_str` scrub both exact secret values and common
  `key: value` / `Bearer <token>` patterns from logs, events, task results, and
  UI output.

## Reporting

To report a security issue privately, email **honeyamn10@gmail.com**. Do **not**
open a public issue for exploit details. We will respond within 72 hours.