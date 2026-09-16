# ADR 0003: Workspace-scoped filesystem + risk-classed permissions

- Status: Accepted
- Date: 2026-09-16

## Context

An autonomous agent with browser, shell and filesystem access on a personal
machine is a real attack surface. The system needs a model of "what may the
agent do" that is explicit, auditable, and conservative by default.

## Decision

1. **Workspace containment**: `JQC_WORKSPACE_DIR` is the only directory the
   agent may freely touch. The `filesystem` skill resolves every path and
   rejects anything outside the workspace.
2. **Risk classes**: every `ToolDef` declares a risk; tool runs are classified
   by (tool, action, resolved resource):
   - `low` → allowed,
   - `medium` → allowed when approval policy is not `ask`,
   - `high` → always `ask` unless a rule overrides it.
3. **Rules**: users store `(risk, fnmatch pattern, allow|deny|ask)` rules.
   Explicit `deny` beats everything; there is **no implicit wildcard allow**.
4. **Approvals** are persisted, resolvable via the API/CLI/UI, and time out.

## Consequences

- Deleting a file, `git push`, or a dangerous shell command always surfaces a
  human prompt first; this is the core of the demo safety story.
- The risk classification (juxtaposed with evidence/resource data) is logged
  for the audit trail.
- Admins can reach an "auto-approve low/medium" mode but never implicitly for
  high-risk actions without an explicit `allow` rule.