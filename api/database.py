import os
from contextlib import contextmanager
from functools import lru_cache

import psycopg2
from fastapi import HTTPException
from psycopg2.extras import RealDictCursor
from pymongo import MongoClient
from pymongo.errors import (
    ConnectionFailure,
    OperationFailure,
    PyMongoError,
    ServerSelectionTimeoutError,
)


REQUIRED_MONGO_INDEXES = {
    "VehicleMetadata": {"idx_vehicle_metadata_vehicle_id"},
    "TelemetryPings": {
        "idx_pings_location_2dsphere",
        "idx_pings_created_at_ttl",
    },
    "TripReviews": {"idx_reviews_city_created_at"},
}


def postgres_dsn() -> str:
    dsn = os.getenv("POSTGRES_DSN") or os.getenv("NEON_DSN")
    if not dsn:
        raise HTTPException(
            status_code=503,
            detail="PostgreSQL is not configured. Set POSTGRES_DSN or NEON_DSN.",
        )
    return dsn


@contextmanager
def postgres_connection():
    try:
        connection = psycopg2.connect(
            postgres_dsn(), cursor_factory=RealDictCursor, connect_timeout=5
        )
    except HTTPException:
        raise
    except psycopg2.Error as exc:
        raise HTTPException(
            status_code=503, detail="PostgreSQL is currently unavailable."
        ) from exc

    try:
        yield connection
    finally:
        connection.close()


@lru_cache(maxsize=1)
def mongo_client() -> MongoClient:
    uri = os.getenv("MONGO_URI") or os.getenv("ATLAS_URI", "mongodb://localhost:27017")
    return MongoClient(uri, serverSelectionTimeoutMS=5000)


def mongo_database():
    return mongo_client()[os.getenv("MONGO_DB", "ridesync")]


def ensure_mongo_indexes() -> None:
    """Idempotently install indexes required by the browser workflows."""
    database = mongo_database()
    database.VehicleMetadata.create_index(
        [("vehicle_id", 1)],
        unique=True,
        name="idx_vehicle_metadata_vehicle_id",
    )
    database.TelemetryPings.create_index(
        [("location", "2dsphere")],
        name="idx_pings_location_2dsphere",
    )
    database.TelemetryPings.create_index(
        [("created_at", 1)],
        expireAfterSeconds=7200,
        name="idx_pings_created_at_ttl",
    )
    database.TripReviews.create_index(
        [("city", 1), ("created_at", -1)],
        name="idx_reviews_city_created_at",
    )


def missing_mongo_indexes() -> dict[str, list[str]]:
    database = mongo_database()
    missing = {}
    for collection_name, required in REQUIRED_MONGO_INDEXES.items():
        installed = set(database[collection_name].index_information())
        absent = sorted(required - installed)
        if absent:
            missing[collection_name] = absent
    return missing


def mongo_unavailable(exc: PyMongoError) -> HTTPException:
    if isinstance(exc, OperationFailure) and exc.code == 18:
        detail = "MongoDB authentication failed. Check MONGO_URI credentials."
    elif isinstance(exc, (ServerSelectionTimeoutError, ConnectionFailure)):
        detail = "MongoDB is currently unavailable. Check MONGO_URI and the MongoDB service."
    elif isinstance(exc, OperationFailure) and exc.code == 291:
        detail = (
            "MongoDB's geospatial index is missing. Restart the API to install "
            "required indexes or run mongo/01_collections_and_indexes.js."
        )
    elif isinstance(exc, OperationFailure):
        detail = "MongoDB rejected the query. Check database permissions and indexes."
    else:
        detail = "MongoDB is currently unavailable."
    return HTTPException(status_code=503, detail=detail)
