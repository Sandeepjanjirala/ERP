# 14. Demo mode: a public showcase that can never touch real data

**Status:** Accepted, November 2026 (Phase 6)

## Context

EduNexa needs a public demo: visitors should try every role without an account, see realistic data, and never be able to harm anything real. The same code runs real schools, so the demo's powers (signing in without a password, wiping all data every night) must be impossible outside the demo.

## Decision

`DEMO_MODE=1` turns on:

- **One-click logins** on the sign-in page, one per role, signing in as a seeded Madhapur account.
- **A banner on every page**: synthetic data, reset nightly, emails not sent, payments in the Sandbox.
- **No real email**: the console backend, whatever `EMAIL_HOST` says.
- **The Sandbox only**: settings refuse to start with Razorpay keys.
- **A nightly reset** (03:45). In one transaction it flushes the data and seeds a fresh synthetic school group (`DEMO_SIZE`, `full` by default). Visitors see the old data until the new data is complete.

**Two independent guards** stand between the reset and a real database:

1. The setting: the reset, the one-click logins and seeding refuse to run without `DEMO_MODE=1` (seeding also runs in development).
2. A marker *inside the database*, `demo.DemoMarker`. `seed_demo` writes it, and seeding requires an empty database. A real school's database is never seeded, so it never has the marker.

So a demo server wrongly pointed at a school's database refuses to reset it or to offer one-click logins.

## Consequences

- Visitors can change anything; the night undoes it. If a visitor switches a demo account off, its one-click login says so until the reset.
- The demo runs the production stack and settings (HTTPS, PostgreSQL, Redis, Celery), so it shows real deployment behaviour.
- Seeding goes through the real services, so the demo data obeys every business rule. Registers and mark sheets are saved in bulk, so the full seed takes about 15 seconds (it used to take a minute).
