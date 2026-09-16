# Architecture Decision Records

Each record documents a significant architecture decision and its context, so
future readers (and the AI itself) can understand *why* the system is shaped
the way it is, not just *what* it does.

## List

| ADR | Title |
| --- | --- |
| [0001](0001-python-core-loopback-ui.md) | Python asyncio core with loopback web UI |
| [0002](0002-mock-first-provider.md) | Deterministic mock provider as the default runtime |
| [0003](0003-workspace-and-permissions.md) | Workspace-scoped filesystem + risk-classed permissions |
| [0004](0004-sqlite-wal-and-migrations.md) | SQLite (WAL) with a sequential migration ledger |