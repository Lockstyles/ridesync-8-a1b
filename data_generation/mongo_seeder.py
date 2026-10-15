"""RideSync MongoDB data generator.

Seeds VehicleMetadata, TripReviews and TelemetryPings.
Run before mongo/01_collections_and_indexes.js.

    python3 data_generation/mongo_seeder.py --drop
"""

import argparse
import os
import random
import math
from datetime import datetime, timedelta, timezone
from tqdm import trange
from faker import Faker
from pymongo import MongoClient

fake = Faker()

CITIES = {
    "Hyderabad": (17.4454, 78.3488),  # IIIT Hyderabad campus / Gachibowli
    "Bengaluru": (12.9716, 77.5946),
    "Mumbai": (19.0760, 72.8777),
    "Delhi": (28.6139, 77.2090),
    "Chennai": (13.0827, 80.2707),
}

FEEDBACK_TAGS = [
    "clean_car", "safe_driving", "polite_driver", "on_time", "smooth_ride",
    "good_music", "helpful_with_luggage", "rash_driving", "late_pickup",
    "car_smelled", "rude_driver", "took_long_route", "ac_not_working",
]

VEHICLE_CLASSES = ["HATCHBACK", "SEDAN", "SUV", "AUTO", "BIKE"]
FUEL_TYPES = ["PETROL", "DIESEL", "CNG", "ELECTRIC"]
INSPECTION_RESULTS = ["PASS", "PASS", "PASS", "CONDITIONAL", "FAIL"]


def random_point_within_radius(lat, lon, radius_km=5.0):
    """Return a point uniformly distributed by area inside a radius."""
    # sqrt(random()) gives a uniform distribution over the disk area rather
    # than concentrating points near the origin.
    radius = radius_km * math.sqrt(random.random())
    angle = random.uniform(0.0, 2.0 * math.pi)
    north_km = radius * math.cos(angle)
    east_km = radius * math.sin(angle)
    new_lat = lat + north_km / 111.0
    new_lon = lon + east_km / (111.0 * math.cos(math.radians(lat)))
    return new_lat, new_lon


def seed_vehicle_metadata(db, vehicle_count, batch_size):
    docs, total = [], 0

    for vehicle_id in trange(1, vehicle_count + 1, desc="VehicleMetadata"):
        inspections = [
            {
                "inspected_on": datetime.now(timezone.utc) - timedelta(days=random.randint(1, 900)),
                "centre": fake.company() + " Auto Centre",
                "odometer_km": random.randint(1000, 250000),
                "result": random.choice(INSPECTION_RESULTS),
                "notes": fake.sentence(nb_words=6),
            }
            for _ in range(random.randint(1, 4))
        ]

        features = {
            "air_conditioning": random.random() < 0.8,
            "fuel_type": random.choice(FUEL_TYPES),
        }
        if random.random() < 0.3:
            features["child_seat"] = random.random() < 0.5
        if random.random() < 0.2:
            features["wheelchair_accessible"] = True
        if random.random() < 0.4:
            features["infotainment"] = random.sample(
                ["bluetooth", "usb_c", "aux", "android_auto"], k=random.randint(1, 3)
            )

        docs.append({
            "vehicle_id": vehicle_id,
            "features": features,
            "inspections": inspections,
            "certifications": random.sample(
                ["PUC", "COMMERCIAL_PERMIT", "FITNESS", "INSURANCE"], k=random.randint(1, 4)
            ),
        })

        if len(docs) >= batch_size:
            db.VehicleMetadata.insert_many(docs, ordered=False)
            total += len(docs)
            docs = []

    if docs:
        db.VehicleMetadata.insert_many(docs, ordered=False)
        total += len(docs)

    print(f"VehicleMetadata: {total}")


def seed_trip_reviews(db, count, vehicle_count, rider_count, batch_size):
    cities = list(CITIES.keys())
    now = datetime.now(timezone.utc)
    docs, total = [], 0

    for trip_id in trange(1, count + 1, desc="TripReviews"):
        rating = random.choices([1, 2, 3, 4, 5], weights=[5, 7, 15, 33, 40])[0]

        if rating >= 4:
            pool = FEEDBACK_TAGS[:7]
        elif rating == 3:
            pool = FEEDBACK_TAGS
        else:
            pool = FEEDBACK_TAGS[7:]

        docs.append({
            "trip_id": trip_id,
            "rider_id": random.randint(1, rider_count),
            "vehicle_id": random.randint(1, vehicle_count),
            "rating": rating,
            "feedback_tags": random.sample(pool, k=random.randint(1, 3)),
            "comment": fake.sentence(nb_words=12),
            "city": random.choice(cities),
            "created_at": now - timedelta(minutes=random.randint(0, 90 * 24 * 60)),
        })

        if len(docs) >= batch_size:
            db.TripReviews.insert_many(docs, ordered=False)
            total += len(docs)
            docs = []

    if docs:
        db.TripReviews.insert_many(docs, ordered=False)
        total += len(docs)

    print(f"TripReviews: {total}")


def seed_telemetry_pings(db, count, vehicle_count, batch_size, window_minutes):
    city_points = list(CITIES.values())
    now = datetime.now(timezone.utc)
    docs, total = [], 0

    for _ in trange(count, desc="TelemetryPings"):
        lat, lon = random_point_within_radius(*random.choice(city_points), radius_km=5.0)

        docs.append({
            "vehicle_id": random.randint(1, vehicle_count),
            "driver_id": random.randint(1, vehicle_count),
            # longitude first, as GeoJSON requires
            "location": {"type": "Point", "coordinates": [float(lon), float(lat)]},
            "is_available": random.random() < 0.35,
            "speed_kmph": round(random.uniform(0, 80), 1),
            # kept inside the 2 hour TTL window so the reaper does not delete the seed data
            "created_at": now - timedelta(minutes=random.randint(0, window_minutes)),
        })

        if len(docs) >= batch_size:
            db.TelemetryPings.insert_many(docs, ordered=False)
            total += len(docs)
            docs = []
            print(f"  pings inserted: {total}", end="\r")

    if docs:
        db.TelemetryPings.insert_many(docs, ordered=False)
        total += len(docs)

    print(f"TelemetryPings: {total}          ")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--uri", default=os.environ.get("MONGO_URI", "mongodb://localhost:27017"))
    parser.add_argument("--db", default=os.environ.get("MONGO_DB", "ridesync"))
    parser.add_argument("--drop", action="store_true")
    parser.add_argument("--vehicles", type=int, default=2000)
    parser.add_argument("--riders", type=int, default=10000)
    parser.add_argument("--reviews", type=int, default=100000)
    parser.add_argument("--pings", type=int, default=500000)
    parser.add_argument("--batch-size", type=int, default=10000)
    parser.add_argument("--ping-window-minutes", type=int, default=90)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    Faker.seed(args.seed)

    client = MongoClient(args.uri)
    db = client[args.db]

    if args.drop:
        for name in ("VehicleMetadata", "TripReviews", "TelemetryPings"):
            db.drop_collection(name)
        print("dropped existing collections")

    started = datetime.now()
    seed_vehicle_metadata(db, args.vehicles, args.batch_size)
    seed_trip_reviews(db, args.reviews, args.vehicles, args.riders, args.batch_size)
    seed_telemetry_pings(db, args.pings, args.vehicles, args.batch_size, args.ping_window_minutes)

    print(f"\ndone in {(datetime.now() - started).total_seconds():.1f}s")
    client.close()


if __name__ == "__main__":
    main()