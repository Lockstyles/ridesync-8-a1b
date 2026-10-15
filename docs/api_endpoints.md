# RideSync API sketch

All responses are JSON. Pagination defaults to 20 rows and is capped at 100.
Expected conflicts use HTTP `409`, missing records use `404`, invalid input uses
`422`, and unavailable databases use `503`.

| Method | Endpoint | Inputs | Output / purpose |
|---|---|---|---|
| GET | `/api/health` | — | PostgreSQL and MongoDB availability |
| GET | `/api/riders` | `page`, `page_size`, `search` | Paginated riders and trip counts |
| GET | `/api/riders/{id}` | rider ID | Rider, wallet and recent trips |
| POST | `/api/riders` | name, starting wallet | Adds a rider for the demo |
| DELETE | `/api/riders/{id}` | rider ID | Deletes only when no trips/audit rows reference the rider; otherwise `409` |
| GET | `/api/vehicles` | pagination, `search`, `class`, `active_only` | Paginated fleet |
| GET | `/api/vehicles/{id}` | vehicle ID | Vehicle, recent trips and Mongo metadata |
| POST | `/api/vehicles` | license plate, class, active flag | Adds a vehicle for the demo |
| DELETE | `/api/vehicles/{id}` | vehicle ID | Deletes only when no trips reference the vehicle; otherwise `409` |
| GET | `/api/trips` | pagination, `status`, `rider_id`, `vehicle_id` | Paginated joined trip records |
| GET | `/api/trips/{id}` | trip ID | Joined trip detail |
| POST | `/api/bookings` | rider, vehicle and positive fare | Calls `sp_atomic_booking`; returns before/after balances, trip and audit entry |
| PATCH | `/api/trips/{id}/status` | `IN TRANSIT` or `COMPLETED` | Forward-only trip status change |
| GET | `/api/riders/{id}/audit` | optional `date_from`, `date_to` | Immutable ledger and running change |
| GET | `/api/analytics/revenue` | optional vehicle, 7–365 days | Window-function series and dense rankings |
| GET | `/api/analytics/summary` | result limit | Materialized lifetime earnings and refresh time |
| POST | `/api/analytics/refresh` | — | Calls `fn_refresh_vehicle_earnings()` |
| GET | `/api/map/nearby` | lat, lon, radius, limit | `$geoNear` available vehicles, closest first |
| GET | `/api/reviews/analytics` | city, 1–365 days | `$facet` rating, tag and average results |
| GET | `/api/reviews/cities` | — | Cities represented in reviews |
| GET | `/api/catalog/vehicles/{id}` | vehicle ID | Flexible `VehicleMetadata` document |
