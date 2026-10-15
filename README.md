# RideSync

CS6.302 Software Systems Development, Assignment 2 web application built on the inherited RideSync Assignment 1 PostgreSQL + MongoDB data layer.

## Contents

1. [Running the project](#1-running-the-project)
2. [Project overview](#2-project-overview)
3. [Submission details](#3-submission-details)
4. [PostgreSQL layer](#4-postgresql-layer)
5. [MongoDB layer](#5-mongodb-layer)
6. [Workflows](#6-workflows)
7. [Performance proof](#7-performance-proof)
8. [Assumptions](#8-assumptions)

---

## 1. Running the project

### 1.1 Prerequisites

- PostgreSQL and MongoDB (tested against MongoDB 8.0), both running locally or reachable over the network
- `psql` and `mongosh` command-line clients
- [`uv`](https://docs.astral.sh/uv/) for Python dependencies. Install it if needed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 1.2 Configure the environment

Copy `.env.example` to `.env` and set:

```text
POSTGRES_DSN=postgresql://postgres:<your password>@localhost:5432/ridesync
MONGO_URI=mongodb://localhost:27017
MONGO_DB=ridesync
```

Load it into your shell for the commands below:

```bash
set -a && source .env && set +a
```

### 1.3 Set up PostgreSQL

Apply the SQL scripts in order, seed, then build the materialized view:

```bash
psql "$POSTGRES_DSN" -f sql/01_schema_ddl.sql
psql "$POSTGRES_DSN" -f sql/02_indexes.sql
psql "$POSTGRES_DSN" -f sql/03_triggers_and_audit.sql
psql "$POSTGRES_DSN" -f sql/04_stored_procedures.sql

uv run data_generation/postgres_seeder.py --dsn "$POSTGRES_DSN"

psql "$POSTGRES_DSN" -f sql/05_materialized_views.sql
```

`sql/05_materialized_views.sql` must run **after** seeding so the materialized view starts with the seeded data.

The seeder creates 10,000 riders, 2,000 vehicles, 100,000 trips and exactly 100,000 wallet audit rows.

### 1.4 Set up MongoDB

Seed first, then build indexes:

```bash
uv run data_generation/mongo_seeder.py --drop --uri "$MONGO_URI"
mongosh ridesync mongo/01_collections_and_indexes.js
```

Locally, you can drop `--uri` and use `mongosh ridesync`.

Seed first, then build indexes: the TTL index deletes anything older than two hours, so creating it before the load would delete seed data as it arrived.

The seeder creates 2,000 VehicleMetadata documents, 100,000 TripReviews and 500,000 TelemetryPings, with Hyderabad telemetry centred around IIIT Hyderabad.

At startup the API also idempotently creates the MongoDB indexes required by `$geoNear`, TTL cleanup, review filtering and vehicle metadata lookup. Running `mongo/01_collections_and_indexes.js` is still recommended because it also installs the collection validators.

### 1.5 Start the application

```bash
uv sync --dev
set -a && source .env && set +a
uv run uvicorn api.main:app --reload
```

- Web app: <http://127.0.0.1:8000>
- Interactive API documentation: <http://127.0.0.1:8000/docs>

### 1.6 Run the tests

```bash
uv run pytest
```

This runs the focused transaction tests.

---

## 2. Project overview

The new `api/` and `web/` folders turn every inherited workflow into a browser screen: paginated browsing, atomic booking with friendly failures, immutable wallet history, revenue analytics, live nearby vehicles, and faceted review analytics with flexible vehicle metadata.

### Screens

| Screen | What it does |
|---|---|
| Browse | Paginated riders, vehicles and trips with search; add rider / add vehicle pop-ups; delete from the detail drawer |
| Book a trip | Atomic booking through the stored procedure (Workflow 1), wallet balance and active trip status |
| Audit trail | Immutable wallet ledger per rider, filterable by date |
| Analytics | Revenue trend with 7-day moving average, vehicle rankings, lifetime earnings (Workflow 2) |
| Live map | Nearest available vehicles on a map (Workflow 3) |
| Reviews | Rating distribution, feedback tags and vehicle metadata (Workflow 4) |

### Add / delete riders and vehicles

The Browse screen has **+ Rider** and **+ Vehicle** buttons. Each opens a pop-up form for adding that record, and delete actions are in each record's detail drawer.

Deletion is intentionally constrained by the inherited relational history: a rider with trips or wallet audit rows cannot be deleted, and a vehicle referenced by trips cannot be deleted. The API returns HTTP 409 with the reason instead of silently losing historical data. A newly added record with no dependent history can be deleted successfully, which demonstrates both paths.

### Design and engineering choices

- **FastAPI + psycopg2 + PyMongo:** a small typed API without duplicating the procedure, trigger, window query or MongoDB pipelines in a second data layer.
- **Vanilla HTML/CSS/JavaScript:** no front-end build output or `node_modules` in the submission; one responsive interface is served by the API process.
- **Leaflet + OpenStreetMap:** a clear geospatial display over the existing `$geoNear` results. The sorted result list remains usable if map tiles fail.
- **Application assumptions:** login is out of scope, the rider selector is the demo actor switcher, fares are charged at request time, status changes only move forward, and telemetry polling every 15 seconds is sufficiently live for the assignment.

### Supporting artifacts

[Handover note](docs/handover_note.md) · [API sketch](docs/api_endpoints.md) · [Users and visual system](docs/design/users.md) · [Wireframes](docs/design/wireframes.md)

### Screenshots

![RideSync paginated rider browser](docs/design/screenshot-browse.png)

---

## 3. Submission details

Repository: `https://github.com/Lockstyles/ridesync-8-a1b`

Demo video: `https://drive.google.com/drive/folders/1yIDfPpcrLLoxUqKtq62l9rvxD9Lh0HS1?usp=drive_link`

Final GitHub commit hash: `<hash>`

**Assignment 2 contribution table — fill the actual work split before submission:**

| Member | Roll number | Design contribution | Code contribution |
|---|---|---|---|
| `Aditya R. Mhatre` | `2026201066` | `<design work>` | `<code work>` |
| `Amit Singh` | `2026201021` | `audit, analytics` | `backend: main` |
| `Karyampudi Srinivas` | `2026201047` | `booking wireframes` | `backend: services, databases` |
| `Kavyanth Munagala` | `2026204016` | `browse, browse-detail` | `frontend` |

---

## 4. PostgreSQL layer

Four tables in `sql/01_schema_ddl.sql`. Fares and balances are `DECIMAL(10,2)`, never float. Trip status is `REQUESTED`, `IN TRANSIT` (space, not underscore), or `COMPLETED`.

- **riders** — unique `name` and `wallet_balance` (`CHECK >= 0`).
- **vehicles** — unique `license_plate`, `class`, `is_active`.
- **trips** — FKs to rider and vehicle, quoted/charged `fare_amount`, status, `created_at`. A trip row is only created once a vehicle is assigned (`vehicle_id` is `NOT NULL`).
- **wallet_audit_logs** — DEBIT ledger. Written by a trigger. The PostgreSQL seeder deliberately pre-fills exactly 100,000 rows from the 100,000 seeded booking debits.

The audit table has the required prefilled 100,000-row volume: one immutable DEBIT per seeded booking. No synthetic top-up rows are added. New riders and vehicles can be added from the Browse screen for demonstration.

### Trigger (audit logging)

`sql/03_triggers_and_audit.sql` — `trg_rider_wallet_audit` fires `AFTER UPDATE OF wallet_balance ON riders`. `log_wallet_change()` inserts one immutable row into `wallet_audit_logs`: the delta, `CREDIT` or `DEBIT`, and `balance_after`.

A second trigger, `trg_wallet_audit_logs_immutable`, rejects every `UPDATE`, `DELETE`, or `TRUNCATE` against the ledger, including statements that would match no rows. Inserts remain allowed so the wallet trigger can append entries.

The seeder never writes the ledger by hand; every seeded booking debit goes through this trigger. Its full database reset temporarily disables the immutability trigger in the same transaction and restores it before commit; this requires table-owner privileges.

```sql
CREATE TRIGGER trg_rider_wallet_audit
AFTER UPDATE OF wallet_balance ON riders
FOR EACH ROW
WHEN (OLD.wallet_balance IS DISTINCT FROM NEW.wallet_balance)
EXECUTE FUNCTION log_wallet_change();
```

### Partial indexing

`sql/02_indexes.sql` — we created partial indexes because they solve:

1. **One open trip per rider** (`idx_active_rider_trip`). Unique on `rider_id` only while status is `REQUESTED` or `IN TRANSIT`. Completed trips are left out so a rider can have many finished trips, but never two at once.
2. **Faster 7-day revenue** (`idx_trips_completed_vehicle_date`). Workflow 2 only reads completed trips. This index keeps `(vehicle_id, created_at)` and `fare_amount` for those rows only, so the window query does not scan requested / in-transit trips.
3. `idx_trips_rider_id` — index on `trips(rider_id)` so "trips for this rider" does not scan the whole table (Postgres does not auto-index FKs).
4. `idx_trips_vehicle_id` — same idea for `trips(vehicle_id)`: look up or join a vehicle's trips without a full scan.

### Materialized view

`sql/05_materialized_views.sql` — `mv_vehicle_earnings` joins every vehicle to its lifetime **completed** trip count and fare sum. Open trips do not count. A unique index on `vehicle_id` is required so refreshes can run `REFRESH CONCURRENTLY` without locking readers. Call the function below after new bookings.

```sql
SELECT fn_refresh_vehicle_earnings();
```

---

## 5. MongoDB layer

Three collections. `docs/mongo_schema_map.json` has the document shapes and a sample of each; `mongo/01_collections_and_indexes.js` creates them with validators and builds the indexes.

- **VehicleMetadata** — inspection history and feature flags. Only the outer shape is validated. The `features` object is left open on purpose, since different vehicles carry different feature sets and that is exactly what a relational column handles badly.
- **TripReviews** — ratings, feedback tags, timestamps. Validated strictly, because Workflow 4 aggregates over it: `rating` is bounded 1–5 so the histogram cannot grow a sixth bucket, and `feedback_tags` must be an array for `$unwind` to expand.
- **TelemetryPings** — GeoJSON Points in `[longitude, latitude]` order. Holds the 2dsphere index for Workflow 3 and a 7200-second TTL, so raw telemetry clears itself after two hours instead of growing without bound.

### Indexes

| Collection | Index | Why |
|---|---|---|
| VehicleMetadata | `vehicle_id` unique | one metadata document per vehicle |
| TelemetryPings | `location` 2dsphere | `$geoNear` for Workflow 3; 2dsphere rather than the legacy flat 2d, so distances come back in metres |
| TelemetryPings | `created_at` TTL 7200s | pings expire after two hours |
| TripReviews | `{city: 1, created_at: -1}` | backs the `$match` ahead of `$facet` in Workflow 4 |

### Geospatial and TTL indexes

`mongo/01_collections_and_indexes.js` builds both on `TelemetryPings`:

- **2dsphere** on `location` (`idx_pings_location_2dsphere`) — Workflow 3 `$geoNear` needs GeoJSON Points. 2dsphere (not the old flat `2d` index) so distances come back in metres.
- **TTL** on `created_at` (`idx_pings_created_at_ttl`, `expireAfterSeconds: 7200`) — pings older than two hours are deleted automatically. `created_at` must be a BSON Date; a string field would build the index and expire nothing.

```javascript
db.TelemetryPings.createIndex({ location: "2dsphere" });
db.TelemetryPings.createIndex({ created_at: 1 }, { expireAfterSeconds: 7200 });
```

---

## 6. Workflows

### Workflow 1 — Atomic booking (stored procedure)

The assignment's "atomic checkout / `orders`" flow is this procedure. Checkout = book a trip. The order row is `trips`, not a separate `orders` table.

`sql/04_stored_procedures.sql` — `sp_atomic_booking(rider, vehicle, fare)` is one PL/pgSQL transaction (`CALL` commits on success). It:

1. Locks the rider (`SELECT … FOR UPDATE`) so two bookings cannot debit the same wallet at once.
2. Rejects a missing rider or a non-positive fare.
3. Verifies the wallet can cover the fare. `riders.wallet_balance` also has `CHECK (>= 0)`, so a debit that would go negative is rejected.
4. Deducts the fare, then inserts a `REQUESTED` trip. The wallet trigger writes the immutable `DEBIT` into `wallet_audit_logs` (audit is on the balance change, not on the trip insert).
5. If the balance is insufficient, `RAISE EXCEPTION` aborts the `CALL`. Postgres rolls back the whole body — no debit, no trip, no audit row.

The fare is charged at **request** time, not at completion. A second open trip for the same rider fails on `idx_active_rider_trip` and also rolls back.

```sql
CALL sp_atomic_booking(1, 1, 250.00);
```

### Workflow 2 — 7-day window analytics

`sql/06_window_analytics.sql` is the Postgres workflow. Only `COMPLETED` trips count as revenue. It:

1. Sums `fare_amount` per vehicle per day.
2. Computes a 7-day moving average with `AVG(...) OVER (PARTITION BY vehicle_id ORDER BY revenue_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)`.
3. Computes two `DENSE_RANK()` values: the best vehicle on each day, and each vehicle's best days.

```bash
psql "$POSTGRES_DSN" -f sql/06_window_analytics.sql
```

### Workflow 3 — Nearest available vehicle

`mongo/02_workflow3_geonear.js` uses `$geoNear` against the 2dsphere index to find the closest available vehicles within 5 km of the IIIT Hyderabad demo origin (`[78.3488, 17.4454]`), returning distances in metres. The seeded telemetry is intentionally clustered around IIIT Hyderabad so the live demo has nearby results instead of an empty map.

```bash
mongosh ridesync mongo/02_workflow3_geonear.js
```

`$geoNear` must be first in the pipeline so it can use `idx_pings_location_2dsphere`. A collection scan would walk all 500,000 pings.

```
plan: GEO_NEAR_2DSPHERE  index=idx_pings_location_2dsphere
docsExamined=15133  nReturned=2339  executionTimeMillis=83
```

15,133 documents examined out of 500,000 seeded pings. The geo stage found 6,590 pings inside 5 km; the `is_available` FETCH cut that to 2,339. Full `explain("executionStats")` is under `workflow3_geonear` in `performance/mongo_execution_stats.json`.

### Workflow 4 — Faceted review analytics

`mongo/03_workflow4_facet.js` answers three questions in one pass over the collection: the 1–5 rating histogram, the ten most common feedback tags via `$unwind`, and the overall average rating.

```bash
mongosh ridesync mongo/03_workflow4_facet.js
```

The `$match` at the front is doing the real work. Sub-pipelines inside `$facet` cannot use an index — only the stage before it can — so without that leading match the whole thing degenerates into a collection scan. Matching on `{city, created_at}` lets it ride `idx_reviews_city_created_at` instead:

```
plan: IXSCAN  docsExamined=20243  nReturned=20243  collectionTotal=100000
```

20,243 documents examined out of 100,000, and every one of them returned, so nothing was read and thrown away. Full `explain("executionStats")` output is in `performance/mongo_execution_stats.json`, regenerated with:

```bash
W4_EXPLAIN_ONLY=1 mongosh --quiet ridesync --file mongo/03_workflow4_facet.js \
    > performance/mongo_execution_stats.json
```

---

## 7. Performance proof

- Workflow 2: `performance/postgres_explain_analyzes.txt`
- Workflows 3 and 4: `performance/mongo_execution_stats.json`

---

## 8. Assumptions

- `vehicle_id`, `rider_id` and `trip_id` are the PostgreSQL integer primary keys. Mongo does not enforce them as foreign keys, so keeping the two engines consistent is the application's job. Both seeders use matching entity counts so that stays true.
- `created_at` is a BSON Date everywhere, never an ISO string. A TTL index on a string field builds without complaint and then silently expires nothing.
- Pings are seeded inside a 90-minute window so the two-hour TTL does not delete them mid-demo.
- Hyderabad telemetry is centred around IIIT Hyderabad and jittered within roughly 4.5 km. The other city clusters remain available for broader review data generation.
- Existing riders and vehicles are intentionally protected by relational history: deletion returns a clear conflict when trips or wallet audit rows reference the record. Newly added riders/vehicles without history can be deleted, demonstrating both paths.
- Validators are applied with `collMod` after seeding, so they govern new writes rather than the documents already loaded.
- Tested against MongoDB 8.0.
- Only completed trips count as revenue.
- The amount is debited when the trip is requested.
