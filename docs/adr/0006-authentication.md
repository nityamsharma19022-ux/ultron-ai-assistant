# ADR-0006: Authentication — owner account, per-device tokens

- **Status:** Accepted
- **Date:** 2026-11-09

## Context
ULTRON is a personal assistant used from a few devices (Android phone,
Windows PC). It must work against a local backend without any third-party
identity provider, and lost devices must be revocable.

## Decision
- **One owner account**, created from the command line
  (`ultron-core create-owner`); no public sign-up endpoint.
- Passwords hashed with **Argon2id** (pwdlib), min 12 characters; unknown
  emails take the same time as wrong passwords.
- **Login creates or reuses a device.** Each device gets:
  - a short-lived **access token** (JWT, HS256, 15 min) carrying user and
    device ids, issuer and audience;
  - a long-lived **refresh token** (opaque, random, stored only as SHA-256)
    that **rotates on every use**. Reusing an old refresh token revokes the
    whole token family (theft detection).
- Every authenticated request checks that the device is not revoked, so
  logout / "remove device" takes effect immediately.
- Login attempts are rate-limited per IP and per email in Redis; if Redis is
  down the limiter fails open (logged) so the owner is not locked out of a
  local fallback backend.
- Tokens are per backend node; a device pairs with the cloud and the local
  backend separately.

## Alternatives
- Supabase Auth: would tie the core to Supabase, which must stay optional.
- fastapi-users: more than a single-owner system needs.

## Consequences
- Rotating `ULTRON_JWT_SECRET` signs everyone out (acceptable for one user).
- Multi-user support would need a sign-up/invite flow later.
