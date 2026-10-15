import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import psycopg2
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pymongo.errors import PyMongoError

from api.database import (
    ensure_mongo_indexes,
    missing_mongo_indexes,
    mongo_database,
    mongo_unavailable,
    postgres_connection,
)
from api.services import BookingConflict, book_trip


ROOT_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT_DIR / "web"
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    # Index creation is idempotent. Keep PostgreSQL-only screens available if
    # MongoDB is temporarily offline during startup.
    try:
        ensure_mongo_indexes()
        application.state.mongo_bootstrap_error = None
    except PyMongoError as exc:
        application.state.mongo_bootstrap_error = type(exc).__name__
        logger.warning("MongoDB index bootstrap skipped: %s", type(exc).__name__)
    yield

app = FastAPI(
    title="RideSync API",
    version="1.0.0",
    description="Browser API for the RideSync PostgreSQL and MongoDB workflows.",
    lifespan=lifespan,
)


class BookingRequest(BaseModel):
    rider_id: int = Field(gt=0)
    vehicle_id: int = Field(gt=0)
    fare_amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class TripStatusRequest(BaseModel):
    status: str


class RiderCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    wallet_balance: Decimal = Field(ge=0, max_digits=10, decimal_places=2)


class VehicleCreateRequest(BaseModel):
    license_plate: str = Field(min_length=2, max_length=20)
    vehicle_class: str = Field(min_length=2, max_length=50)
    is_active: bool = True


def pagination(page: int, page_size: int) -> tuple[int, int]:
    return page_size, (page - 1) * page_size


def page_result(items: list, total: int, page: int, page_size: int) -> dict:
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@app.get("/api/health")
def health():
    result = {
        "status": "ok",
        "postgres": False,
        "mongo": False,
        "mongo_indexes": False,
    }
    try:
        with postgres_connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            result["postgres"] = cursor.fetchone() is not None
    except HTTPException:
        result["status"] = "degraded"

    try:
        mongo_database().command("ping")
        result["mongo"] = True
        missing = missing_mongo_indexes()
        result["mongo_indexes"] = not missing
        if missing:
            result["status"] = "degraded"
            result["missing_mongo_indexes"] = missing
    except PyMongoError:
        result["status"] = "degraded"
    return result


@app.get("/api/riders")
def list_riders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query("", max_length=100),
):
    limit, offset = pagination(page, page_size)
    pattern = f"%{search.strip()}%"
    with postgres_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*) AS total
            FROM riders
            WHERE %s = '' OR name ILIKE %s OR id::text = %s
            """,
            (search.strip(), pattern, search.strip()),
        )
        total = cursor.fetchone()["total"]
        cursor.execute(
            """
            SELECT r.id, r.name, r.wallet_balance,
                   count(t.id) AS trip_count,
                   count(t.id) FILTER (
                       WHERE t.status IN ('REQUESTED', 'IN TRANSIT')
                   ) AS active_trip_count
            FROM riders r
            LEFT JOIN trips t ON t.rider_id = r.id
            WHERE %s = '' OR r.name ILIKE %s OR r.id::text = %s
            GROUP BY r.id
            ORDER BY r.id
            LIMIT %s OFFSET %s
            """,
            (search.strip(), pattern, search.strip(), limit, offset),
        )
        items = cursor.fetchall()
    return page_result(items, total, page, page_size)


@app.post("/api/riders", status_code=201)
def create_rider(payload: RiderCreateRequest):
    name = payload.name.strip()
    with postgres_connection() as connection, connection.cursor() as cursor:
        try:
            cursor.execute(
                "INSERT INTO riders (name, wallet_balance) VALUES (%s, %s) RETURNING id, name, wallet_balance",
                (name, payload.wallet_balance),
            )
            rider = cursor.fetchone()
            connection.commit()
        except psycopg2.Error as exc:
            connection.rollback()
            if getattr(getattr(exc, "diag", None), "constraint_name", None) == "riders_name_key":
                raise HTTPException(status_code=409, detail="A rider with this name already exists.") from exc
            raise HTTPException(status_code=500, detail="Rider could not be added.") from exc
    return rider


@app.delete("/api/riders/{rider_id}")
def delete_rider(rider_id: int):
    with postgres_connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT id, name FROM riders WHERE id = %s", (rider_id,))
        rider = cursor.fetchone()
        if rider is None:
            raise HTTPException(status_code=404, detail="Rider not found.")
        try:
            cursor.execute("DELETE FROM riders WHERE id = %s", (rider_id,))
            connection.commit()
        except psycopg2.Error as exc:
            connection.rollback()
            if getattr(getattr(exc, "diag", None), "constraint_name", None) in {
                "wallet_audit_logs_rider_id_fkey", "trips_rider_id_fkey"
            } or "foreign key" in str(exc).lower():
                raise HTTPException(
                    status_code=409,
                    detail="This rider cannot be deleted because trips or wallet audit history still references the rider. Add riders freely, but keep historical riders for audit integrity.",
                ) from exc
            raise HTTPException(status_code=500, detail="Rider could not be deleted.") from exc
    return {"deleted": True, "rider": rider}


@app.get("/api/riders/{rider_id}")
def rider_detail(rider_id: int):
    with postgres_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, name, wallet_balance FROM riders WHERE id = %s", (rider_id,)
        )
        rider = cursor.fetchone()
        if rider is None:
            raise HTTPException(status_code=404, detail="Rider not found.")
        cursor.execute(
            """
            SELECT t.id, t.vehicle_id, v.license_plate, t.fare_amount,
                   t.status, t.created_at
            FROM trips t
            JOIN vehicles v ON v.id = t.vehicle_id
            WHERE t.rider_id = %s
            ORDER BY t.created_at DESC, t.id DESC
            LIMIT 20
            """,
            (rider_id,),
        )
        rider["recent_trips"] = cursor.fetchall()
    return rider


@app.get("/api/vehicles")
def list_vehicles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query("", max_length=100),
    vehicle_class: str | None = Query(None, alias="class"),
    active_only: bool = False,
):
    limit, offset = pagination(page, page_size)
    filters = ["(%s = '' OR license_plate ILIKE %s OR id::text = %s)"]
    pattern = f"%{search.strip()}%"
    params: list = [search.strip(), pattern, search.strip()]
    if vehicle_class:
        filters.append("class = %s")
        params.append(vehicle_class)
    if active_only:
        filters.append("is_active = TRUE")
    where = " AND ".join(filters)

    with postgres_connection() as connection, connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) AS total FROM vehicles WHERE {where}", params)
        total = cursor.fetchone()["total"]
        cursor.execute(
            f"""
            SELECT id, license_plate, class, is_active
            FROM vehicles
            WHERE {where}
            ORDER BY id
            LIMIT %s OFFSET %s
            """,
            [*params, limit, offset],
        )
        items = cursor.fetchall()
    return page_result(items, total, page, page_size)


@app.post("/api/vehicles", status_code=201)
def create_vehicle(payload: VehicleCreateRequest):
    plate = payload.license_plate.strip().upper()
    with postgres_connection() as connection, connection.cursor() as cursor:
        try:
            cursor.execute(
                "INSERT INTO vehicles (license_plate, class, is_active) VALUES (%s, %s, %s) RETURNING id, license_plate, class, is_active",
                (plate, payload.vehicle_class.strip().upper(), payload.is_active),
            )
            vehicle = cursor.fetchone()
            connection.commit()
        except psycopg2.Error as exc:
            connection.rollback()
            if getattr(getattr(exc, "diag", None), "constraint_name", None) == "vehicles_license_plate_key":
                raise HTTPException(status_code=409, detail="A vehicle with this license plate already exists.") from exc
            raise HTTPException(status_code=500, detail="Vehicle could not be added.") from exc

    # Mongo metadata is optional for a newly added vehicle; the relational
    # vehicle remains usable even when MongoDB is temporarily unavailable.
    try:
        mongo_database().VehicleMetadata.update_one(
            {"vehicle_id": vehicle["id"]},
            {"$setOnInsert": {"vehicle_id": vehicle["id"], "features": {}, "inspections": [], "certifications": []}},
            upsert=True,
        )
    except PyMongoError:
        pass
    return vehicle


@app.delete("/api/vehicles/{vehicle_id}")
def delete_vehicle(vehicle_id: int):
    with postgres_connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT id, license_plate, class FROM vehicles WHERE id = %s", (vehicle_id,))
        vehicle = cursor.fetchone()
        if vehicle is None:
            raise HTTPException(status_code=404, detail="Vehicle not found.")
        try:
            cursor.execute("DELETE FROM vehicles WHERE id = %s", (vehicle_id,))
            connection.commit()
        except psycopg2.Error as exc:
            connection.rollback()
            if "foreign key" in str(exc).lower() or getattr(getattr(exc, "diag", None), "constraint_name", None) == "trips_vehicle_id_fkey":
                raise HTTPException(
                    status_code=409,
                    detail="This vehicle cannot be deleted because trip history still references it. Keep historical vehicles for analytics and auditability.",
                ) from exc
            raise HTTPException(status_code=500, detail="Vehicle could not be deleted.") from exc

    try:
        mongo_database().VehicleMetadata.delete_one({"vehicle_id": vehicle_id})
        mongo_database().TelemetryPings.delete_many({"vehicle_id": vehicle_id})
    except PyMongoError:
        pass
    return {"deleted": True, "vehicle": vehicle}


@app.get("/api/vehicles/{vehicle_id}")
def vehicle_detail(vehicle_id: int):
    with postgres_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, license_plate, class, is_active FROM vehicles WHERE id = %s",
            (vehicle_id,),
        )
        vehicle = cursor.fetchone()
        if vehicle is None:
            raise HTTPException(status_code=404, detail="Vehicle not found.")
        cursor.execute(
            """
            SELECT id, rider_id, fare_amount, status, created_at
            FROM trips WHERE vehicle_id = %s
            ORDER BY created_at DESC, id DESC LIMIT 20
            """,
            (vehicle_id,),
        )
        vehicle["recent_trips"] = cursor.fetchall()
    try:
        metadata = mongo_database().VehicleMetadata.find_one(
            {"vehicle_id": vehicle_id}, {"_id": 0}
        )
    except PyMongoError:
        metadata = None
    vehicle["metadata"] = metadata
    return vehicle


@app.get("/api/trips")
def list_trips(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    rider_id: int | None = Query(None, ge=1),
    vehicle_id: int | None = Query(None, ge=1),
):
    limit, offset = pagination(page, page_size)
    filters = ["TRUE"]
    params: list = []
    if status:
        filters.append("t.status = %s")
        params.append(status)
    if rider_id:
        filters.append("t.rider_id = %s")
        params.append(rider_id)
    if vehicle_id:
        filters.append("t.vehicle_id = %s")
        params.append(vehicle_id)
    where = " AND ".join(filters)

    with postgres_connection() as connection, connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) AS total FROM trips t WHERE {where}", params)
        total = cursor.fetchone()["total"]
        cursor.execute(
            f"""
            SELECT t.id, t.rider_id, r.name AS rider_name, t.vehicle_id,
                   v.license_plate, t.fare_amount, t.status, t.created_at
            FROM trips t
            JOIN riders r ON r.id = t.rider_id
            JOIN vehicles v ON v.id = t.vehicle_id
            WHERE {where}
            ORDER BY t.created_at DESC, t.id DESC
            LIMIT %s OFFSET %s
            """,
            [*params, limit, offset],
        )
        items = cursor.fetchall()
    return page_result(items, total, page, page_size)


@app.get("/api/trips/{trip_id}")
def trip_detail(trip_id: int):
    with postgres_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT t.id, t.rider_id, r.name AS rider_name, t.vehicle_id,
                   v.license_plate, v.class AS vehicle_class, t.fare_amount,
                   t.status, t.created_at
            FROM trips t
            JOIN riders r ON r.id = t.rider_id
            JOIN vehicles v ON v.id = t.vehicle_id
            WHERE t.id = %s
            """,
            (trip_id,),
        )
        trip = cursor.fetchone()
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found.")
    return trip


@app.post("/api/bookings", status_code=201)
def create_booking(payload: BookingRequest):
    with postgres_connection() as connection:
        try:
            return book_trip(
                connection,
                payload.rider_id,
                payload.vehicle_id,
                payload.fare_amount,
            )
        except BookingConflict as exc:
            raise HTTPException(status_code=409, detail=exc.message) from exc


@app.patch("/api/trips/{trip_id}/status")
def update_trip_status(trip_id: int, payload: TripStatusRequest):
    target = payload.status.upper()
    allowed = {
        "REQUESTED": {"IN TRANSIT", "COMPLETED"},
        "IN TRANSIT": {"COMPLETED"},
        "COMPLETED": set(),
    }
    if target not in allowed:
        raise HTTPException(status_code=422, detail="Unknown trip status.")

    with postgres_connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT status FROM trips WHERE id = %s FOR UPDATE", (trip_id,))
        current = cursor.fetchone()
        if current is None:
            raise HTTPException(status_code=404, detail="Trip not found.")
        if target not in allowed[current["status"]]:
            raise HTTPException(
                status_code=409,
                detail=f"A {current['status']} trip cannot move to {target}.",
            )
        cursor.execute(
            """
            UPDATE trips SET status = %s WHERE id = %s
            RETURNING id, rider_id, vehicle_id, fare_amount, status, created_at
            """,
            (target, trip_id),
        )
        trip = cursor.fetchone()
        connection.commit()
    return trip


@app.get("/api/riders/{rider_id}/audit")
def audit_trail(
    rider_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
):
    with postgres_connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT id, name FROM riders WHERE id = %s", (rider_id,))
        rider = cursor.fetchone()
        if rider is None:
            raise HTTPException(status_code=404, detail="Rider not found.")
        cursor.execute(
            """
            WITH ledger AS (
                SELECT id, rider_id, amount_changed, action_type, balance_after,
                       created_at,
                       SUM(amount_changed) OVER (
                           PARTITION BY rider_id ORDER BY created_at, id
                           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                       ) AS running_change
                FROM wallet_audit_logs
                WHERE rider_id = %s
            )
            SELECT * FROM ledger
            WHERE (%s::date IS NULL OR created_at >= %s::date)
              AND (%s::date IS NULL OR created_at < %s::date + INTERVAL '1 day')
            ORDER BY created_at DESC, id DESC
            """,
            (rider_id, date_from, date_from, date_to, date_to),
        )
        entries = cursor.fetchall()
    return {"rider": rider, "entries": entries}


REVENUE_CTE = """
WITH bounds AS (
    SELECT CURRENT_DATE - (%s - 1) AS start_date, CURRENT_DATE AS end_date
), calendar AS (
    SELECT generate_series(
        (SELECT start_date FROM bounds),
        (SELECT end_date FROM bounds),
        INTERVAL '1 day'
    )::date AS revenue_date
), vehicles_calendar AS (
    SELECT v.id AS vehicle_id, c.revenue_date
    FROM vehicles v CROSS JOIN calendar c
), daily_revenue AS (
    SELECT vehicle_id, created_at::date AS revenue_date,
           SUM(fare_amount) AS daily_fare
    FROM trips
    WHERE status = 'COMPLETED'
      AND created_at::date >= (SELECT start_date FROM bounds)
      AND created_at::date <= (SELECT end_date FROM bounds)
    GROUP BY vehicle_id, created_at::date
), calendar_revenue AS (
    SELECT vc.vehicle_id, vc.revenue_date,
           COALESCE(dr.daily_fare, 0)::numeric AS daily_fare
    FROM vehicles_calendar vc
    LEFT JOIN daily_revenue dr
      ON dr.vehicle_id = vc.vehicle_id
     AND dr.revenue_date = vc.revenue_date
), moving_average AS (
    SELECT vehicle_id, revenue_date, daily_fare,
           ROUND(AVG(daily_fare) OVER (
               PARTITION BY vehicle_id
               ORDER BY revenue_date
               ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
           ), 2) AS moving_avg_7d
    FROM calendar_revenue
), ranked AS (
    SELECT vehicle_id, revenue_date, daily_fare, moving_avg_7d,
           DENSE_RANK() OVER (
               PARTITION BY revenue_date ORDER BY moving_avg_7d DESC
           ) AS rank_vehicle_per_day,
           DENSE_RANK() OVER (
               PARTITION BY vehicle_id ORDER BY moving_avg_7d DESC
           ) AS rank_day_for_vehicle
    FROM moving_average
)
"""


@app.get("/api/analytics/revenue")
def revenue_analytics(
    vehicle_id: int | None = Query(None, ge=1),
    days: int = Query(30, ge=7, le=365),
):
    with postgres_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            REVENUE_CTE
            + """
            SELECT r.vehicle_id, v.license_plate, r.revenue_date,
                   r.daily_fare, r.moving_avg_7d,
                   r.rank_vehicle_per_day, r.rank_day_for_vehicle
            FROM ranked r
            JOIN vehicles v ON v.id = r.vehicle_id
            WHERE (%s::int IS NULL OR r.vehicle_id = %s)
            ORDER BY r.revenue_date, r.vehicle_id
            """,
            (days, vehicle_id, vehicle_id),
        )
        series = cursor.fetchall()
        cursor.execute(
            REVENUE_CTE
            + """
            SELECT r.vehicle_id, v.license_plate, r.revenue_date,
                   r.moving_avg_7d, r.rank_vehicle_per_day
            FROM ranked r
            JOIN vehicles v ON v.id = r.vehicle_id
            WHERE r.revenue_date = CURRENT_DATE
            ORDER BY r.rank_vehicle_per_day, r.vehicle_id
            LIMIT 25
            """,
            (days,),
        )
        latest_rankings = cursor.fetchall()
    return {"series": series, "latest_rankings": latest_rankings, "days": days}


@app.get("/api/analytics/summary")
def earnings_summary(limit: int = Query(10, ge=1, le=100)):
    with postgres_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT vehicle_id, license_plate, class, lifetime_trip_count,
                   lifetime_earnings
            FROM mv_vehicle_earnings
            ORDER BY lifetime_earnings DESC, vehicle_id
            LIMIT %s
            """,
            (limit,),
        )
        vehicles = cursor.fetchall()
        cursor.execute(
            """
            SELECT refreshed_at
            FROM materialized_view_refreshes
            WHERE view_name = 'mv_vehicle_earnings'
            """
        )
        refreshed = cursor.fetchone()
    return {
        "vehicles": vehicles,
        "last_refreshed": refreshed["refreshed_at"] if refreshed else None,
    }


@app.post("/api/analytics/refresh")
def refresh_earnings():
    try:
        with postgres_connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT fn_refresh_vehicle_earnings()")
            cursor.execute(
                """
                SELECT refreshed_at FROM materialized_view_refreshes
                WHERE view_name = 'mv_vehicle_earnings'
                """
            )
            refreshed = cursor.fetchone()
            connection.commit()
    except psycopg2.Error as exc:
        raise HTTPException(
            status_code=409,
            detail="The earnings summary is already being refreshed. Try again shortly.",
        ) from exc
    return {"last_refreshed": refreshed["refreshed_at"]}


@app.get("/api/map/nearby")
def nearby_vehicles(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_m: int = Query(5000, ge=100, le=20000),
):
    pipeline = [
        {
            "$geoNear": {
                "near": {"type": "Point", "coordinates": [lon, lat]},
                "distanceField": "distance_m",
                "maxDistance": radius_m,
                "spherical": True,
                "query": {"is_available": True},
                "key": "location",
            }
        },
        {
            "$group": {
                "_id": "$vehicle_id",
                "vehicle_id": {"$first": "$vehicle_id"},
                "distance_m": {"$first": "$distance_m"},
                "location": {"$first": "$location"},
                "driver_id": {"$first": "$driver_id"},
                "speed_kmph": {"$first": "$speed_kmph"},
                "created_at": {"$first": "$created_at"},
            }
        },
        {"$sort": {"distance_m": 1}},
        {"$limit": 50},
        {"$project": {"_id": 0}},
    ]
    try:
        vehicles = list(mongo_database().TelemetryPings.aggregate(pipeline))
    except PyMongoError as exc:
        raise mongo_unavailable(exc) from exc
    return {
        "origin": {"lat": lat, "lon": lon},
        "radius_m": radius_m,
        "vehicles": vehicles,
        "generated_at": datetime.now(timezone.utc),
    }


@app.get("/api/reviews/analytics")
def review_analytics(
    city: str = Query("Hyderabad", min_length=1, max_length=80),
    days: int = Query(90, ge=1, le=365),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    pipeline = [
        {"$match": {"city": city, "created_at": {"$gte": since}}},
        {
            "$facet": {
                "rating_distribution": [
                    {"$group": {"_id": "$rating", "count": {"$sum": 1}}},
                    {"$sort": {"_id": 1}},
                    {"$project": {"_id": 0, "rating": "$_id", "count": 1}},
                ],
                "top_feedback_tags": [
                    {"$unwind": "$feedback_tags"},
                    {"$group": {"_id": "$feedback_tags", "count": {"$sum": 1}}},
                    {"$sort": {"count": -1, "_id": 1}},
                    {"$limit": 10},
                    {"$project": {"_id": 0, "tag": "$_id", "count": 1}},
                ],
                "overall": [
                    {
                        "$group": {
                            "_id": None,
                            "average_rating": {"$avg": "$rating"},
                            "total_reviews": {"$sum": 1},
                        }
                    },
                    {"$project": {"_id": 0}},
                ],
            }
        },
    ]
    try:
        result = next(mongo_database().TripReviews.aggregate(pipeline), {})
    except PyMongoError as exc:
        raise mongo_unavailable(exc) from exc
    overall = (result.get("overall") or [{}])[0]
    return {
        "city": city,
        "days": days,
        "rating_distribution": result.get("rating_distribution", []),
        "top_feedback_tags": result.get("top_feedback_tags", []),
        "average_rating": round(overall.get("average_rating"), 2)
        if overall.get("average_rating") is not None
        else None,
        "total_reviews": overall.get("total_reviews", 0),
    }


@app.get("/api/reviews/cities")
def review_cities():
    try:
        cities = sorted(mongo_database().TripReviews.distinct("city"))
    except PyMongoError as exc:
        raise mongo_unavailable(exc) from exc
    return {"cities": cities}


@app.get("/api/catalog/vehicles/{vehicle_id}")
def vehicle_catalog(vehicle_id: int):
    try:
        document = mongo_database().VehicleMetadata.find_one(
            {"vehicle_id": vehicle_id}, {"_id": 0}
        )
    except PyMongoError as exc:
        raise mongo_unavailable(exc) from exc
    if document is None:
        raise HTTPException(status_code=404, detail="Vehicle metadata not found.")
    return document


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
