import argparse
import random

import psycopg2
from faker import Faker
from psycopg2.extras import execute_values
from tqdm import trange, tqdm
from datetime import timezone

fake = Faker()
Faker.seed(42)


def clear_tables(cur):
    # The audit ledger rejects UPDATE, DELETE and TRUNCATE in normal use.
    # Seeding is an explicit owner-level reset, so suspend only that guard for
    # the reset transaction and restore it before the transaction is committed.
    cur.execute(
        "ALTER TABLE wallet_audit_logs "
        "DISABLE TRIGGER trg_wallet_audit_logs_immutable"
    )
    cur.execute(
        "TRUNCATE trips, wallet_audit_logs, vehicles, riders "
        "RESTART IDENTITY CASCADE"
    )
    cur.execute(
        "ALTER TABLE wallet_audit_logs "
        "ENABLE TRIGGER trg_wallet_audit_logs_immutable"
    )


def insert_riders(cur, count=10000):
    riders = []
    names = set()
    for _ in trange(count, desc="Generating riders"):
        name = fake.name()
        while name in names:
            name = fake.name()
        names.add(name)
        riders.append(
            (
                name,
                fake.pydecimal(min_value=50000, max_value=150000, right_digits=2),
            )
        )
    execute_values(
        cur,
        "INSERT INTO riders (name, wallet_balance) VALUES %s",
        riders,
    )

    cur.execute("SELECT id FROM riders ORDER BY id")
    return [row[0] for row in cur.fetchall()]


def insert_vehicles(cur, count=2000):
    vehicles = [
        (
            f"{fake.license_plate()}-{i:05d}"[:20],
            random.choice(["ECONOMY", "PREMIUM", "SUV", "AUTO"]),
            fake.boolean(chance_of_getting_true=75),
        )
        for i in trange(count, desc="Generating vehicles")
    ]
    execute_values(
        cur,
        "INSERT INTO vehicles (license_plate, class, is_active) VALUES %s",
        vehicles,
    )

    cur.execute("SELECT id FROM vehicles ORDER BY id")
    return [row[0] for row in cur.fetchall()]


def get_balances(cur):
   
    cur.execute("SELECT id, wallet_balance FROM riders")
    return dict(cur.fetchall())


BATCH_SIZE = 2000  # statements per round trip, not rows — tune down if Neon complains about tx size

def book_trips(cur, rider_ids, vehicle_ids, balances, count=100000):
    # Sanity-check the id-tracking assumption below before trusting it.
    cur.execute("SELECT COUNT(*) FROM trips")
    assert cur.fetchone()[0] == 0, (
        "trips is not empty — next_trip_id tracking assumes a fresh, "
        "TRUNCATE...RESTART IDENTITY'd table seeded only by this function"
    )

    active_trip_id = {}
    next_trip_id = 1  # trips.id is IDENTITY + table truncated first + sole writer
                       # -> id is just the row's insertion order, no SELECT needed

    statements = []

    def flush():
        if not statements:
            return
        try:
            cur.execute(b";".join(statements))
            cur.connection.commit()
        except Exception:
            cur.connection.rollback()
            raise
        statements.clear()

    for _ in trange(count, desc="Booking trips"):
        rider_id = random.choice(rider_ids)
        vehicle_id = random.choice(vehicle_ids)
        fare_amount = fake.pydecimal(min_value=100, max_value=3000, right_digits=2)

        if rider_id in active_trip_id:
            statements.append(cur.mogrify(
                "UPDATE trips SET status = 'COMPLETED' WHERE id = %s",
                (active_trip_id.pop(rider_id),),
            ))

        if balances[rider_id] < fare_amount:
            # The seeder's default rider balances are deliberately high enough
            # that the 100,000 booking debits can be generated without
            # synthetic top-up rows. This keeps wallet_audit_logs at exactly
            # 100,000 prefilled rows: one immutable DEBIT per seeded booking.
            raise RuntimeError(
                f"Seed balance unexpectedly too low for rider {rider_id}; "
                "increase the rider seed balance range before seeding."
            )

        statements.append(cur.mogrify(
            "CALL sp_atomic_booking(%s, %s, %s)",
            (rider_id, vehicle_id, fare_amount),
        ))
        balances[rider_id] -= fare_amount

        trip_id = next_trip_id
        next_trip_id += 1

        booked_at = fake.date_time_between(
            start_date="-30d", end_date="now", tzinfo=timezone.utc
        )
        status = random.choices(
            ["REQUESTED", "IN TRANSIT", "COMPLETED"],
            weights=[0.34, 0.33, 0.33],
        )[0]
        statements.append(cur.mogrify(
            "UPDATE trips SET created_at = %s, status = %s WHERE id = %s",
            (booked_at, status, trip_id),
        ))
        if status != "COMPLETED":
            active_trip_id[rider_id] = trip_id

        if len(statements) >= BATCH_SIZE:
            flush()

    flush()
    return 0, count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--riders", type=int, default=10000)
    parser.add_argument("--vehicles", type=int, default=2000)
    parser.add_argument(
        "--trips",
        type=int,
        default=100000,
        help=(
            "Trips to book. Every booking now produces exactly one DEBIT "
            "ledger row (the charge happens at booking, not completion), "
            "so this maps far more directly to ledger row count than it "
            "used to when only COMPLETED trips counted."
        ),
    )
    args = parser.parse_args()

    conn = psycopg2.connect(args.dsn)
    try:
        cur = conn.cursor()

        clear_tables(cur)
        conn.commit()

        rider_ids = insert_riders(cur, args.riders)
        conn.commit()

        vehicle_ids = insert_vehicles(cur, args.vehicles)
        conn.commit()

        balances = get_balances(cur)

        _, booked_count = book_trips(
            cur, rider_ids, vehicle_ids, balances, args.trips
        )
        conn.commit()
    finally:
        conn.close()

    ledger_rows = booked_count
    print("Data inserted successfully.")
    print(f"Ledger rows written: {ledger_rows} (one DEBIT per seeded booking)")
    if ledger_rows == 100000:
        print("wallet_audit_logs is prefilled with exactly 100,000 rows.")
    else:
        print("Adjust --trips if you need a different ledger size.")


if __name__ == "__main__":
    main()
