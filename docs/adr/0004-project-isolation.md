# ADR-0004: Strict isolation from other projects

- **Status:** Accepted (requested by project owner)
- **Date:** 2026-11-09

## Context
The owner's accounts contain resources for other, unrelated projects. ULTRON
must never read, modify or reuse them.

## Decision
- **Config:** every variable is `ULTRON_`-prefixed; only `.env.example`
  (placeholders) is committed; `.env` is git-ignored.
- **Local services:** Compose project `ultron`, containers `ultron-*`,
  volumes `ultron_*`, network `ultron_network`, non-default host ports
  (5433, 6380) bound to `127.0.0.1`.
- **Database:** local Postgres database/user `ultron`. Any future cloud
  database is a **new** ULTRON-only project.
- **Deployment:** ULTRON is not deployed to Netlify, and no existing
  Netlify site is modified. `.netlify/` and `.vercel/` are git-ignored to
  prevent accidental linking.
- **Credentials:** ULTRON keys are created for ULTRON alone and are never
  copied from, or shared with, other projects.

## Consequences
- Slight duplication of setup effort; in exchange no change to ULTRON can
  affect another project's data or deployments.
