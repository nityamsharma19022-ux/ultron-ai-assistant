# ADR-0005: Outbox-based sync; no automatic database switching

- **Status:** Accepted
- **Date:** 2026-11-09

## Context
Android must work offline and reconnect safely, first to the cloud backend
and otherwise to the Windows local backend. Cloud and local databases must
stay separate, and switching between them without a sync strategy risks
silent data loss or split-brain.

## Decision
- One **primary** node at a time, chosen by configuration. The Windows
  backend is primary until a cloud backend exists, then becomes an **edge**.
- Devices (and later the edge) use an **outbox** of idempotent operations
  (`op_id`) pushed in order, plus a **change feed** pulled by cursor.
- Field-level conflict handling; conflicting values are preserved as
  conflict copies, never discarded.
- `ULTRON_DB_MODE` selects exactly one database at startup. There is **no
  runtime failover** between databases; moving data is a manual,
  verified procedure.

Full design: [docs/SYNC.md](../SYNC.md).

## Consequences
- Every synchronised table needs client-generated UUIDs, `version`,
  tombstones and a change sequence (foundation laid in Phase 1).
- When the primary's database is down, writes queue on devices instead of
  going to a different database.
