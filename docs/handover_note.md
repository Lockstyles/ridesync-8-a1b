# RideSync handover note

## What we inherited

RideSync arrived with a compact and understandable data layer: four PostgreSQL
tables, an atomic booking procedure, wallet audit trigger, partial unique index,
materialized earnings view, window-function report, and three MongoDB
collections with the required geospatial, TTL, and review analytics pipelines.
The seeders use matching integer IDs across both databases, which makes the two
stores practical to present as one product.

The PostgreSQL schema and audit behavior were validated against a temporary
PostgreSQL 18 instance. The trigger creates the expected debit entry and the
booking procedure leaves the charge and trip in one transaction. The MongoDB
scripts and their saved execution plans were reviewed; a live Atlas connection
is still needed to reproduce those plans on another machine.

## What needed attention

- The README described `wallet_audit_logs` as immutable, but PostgreSQL still
  allowed updates and deletes. A statement-level guard now rejects `UPDATE`,
  `DELETE`, and `TRUNCATE`. The destructive seeder reset explicitly suspends
  that guard only inside its owner-level reset transaction.
- The materialized view had no record of when it was refreshed, although the
  Assignment 2 screen requires that time. `materialized_view_refreshes` now
  records the initial and most recent successful refresh.
- There was no HTTP layer, so browser code could not safely call either
  database. The new FastAPI service exposes bounded, parameterized endpoints
  and translates expected booking failures into readable conflict responses.
- The data model allows `REQUESTED → IN TRANSIT → COMPLETED`; the new API
  enforces forward-only status changes so the partial unique index can be
  demonstrated without arbitrary state rewrites.
- The seed volume now deliberately produces exactly 100,000 immutable
  `wallet_audit_logs` rows: one DEBIT for each of the 100,000 seeded bookings.
- The Browse screen now supports adding riders and vehicles. Delete actions are
  also exposed, but PostgreSQL foreign keys deliberately block deletion when
  trip or wallet-audit history depends on the record.
- Workflow 3 telemetry is centered around IIIT Hyderabad so the 5 km map demo
  has local nearby vehicles instead of relying on a generic city center.

## Suggestions to the original authors

The SQL design is a good fit for the four workflows and should remain the
source of truth. Future work should add a proper migration tool rather than
reapplying numbered SQL files, introduce role-based database permissions for
the API, and record an opening wallet balance in the ledger if a fully
self-contained accounting history is required. For production telemetry, use
an authenticated stream and a dedicated retention policy rather than a seeder.

The web application deliberately keeps authentication out of scope, as the
assignment permits a demo rider switcher. Authentication and authorization are
the first additions recommended before any public deployment.
