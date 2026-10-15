from decimal import Decimal

import psycopg2


class BookingConflict(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def friendly_booking_error(exc: psycopg2.Error) -> str:
    message = str(exc).lower()
    constraint = getattr(getattr(exc, "diag", None), "constraint_name", None)

    if constraint == "idx_active_rider_trip" or "idx_active_rider_trip" in message:
        return "This rider already has an active trip. Complete it before booking another."
    if "insufficient wallet balance" in message:
        return "The rider does not have enough wallet balance for this fare."
    if "fare amount must be greater than zero" in message:
        return "Fare must be greater than zero."
    if "rider" in message and "does not exist" in message:
        return "The selected rider no longer exists."
    if "foreign key" in message or "vehicle_id_fkey" in message:
        return "The selected vehicle no longer exists."
    return "The booking could not be completed. No balance was charged."


def book_trip(connection, rider_id: int, vehicle_id: int, fare_amount: Decimal) -> dict:
    """Run the inherited booking procedure and return its observable effects."""
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, name, wallet_balance FROM riders WHERE id = %s",
                (rider_id,),
            )
            rider_before = cursor.fetchone()
            if rider_before is None:
                raise BookingConflict("The selected rider no longer exists.")

            cursor.execute(
                "CALL sp_atomic_booking(%s, %s, %s)",
                (rider_id, vehicle_id, fare_amount),
            )
            cursor.execute(
                "SELECT id, name, wallet_balance FROM riders WHERE id = %s",
                (rider_id,),
            )
            rider_after = cursor.fetchone()
            cursor.execute(
                """
                SELECT id, rider_id, amount_changed, action_type,
                       balance_after, created_at
                FROM wallet_audit_logs
                WHERE rider_id = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (rider_id,),
            )
            audit_entry = cursor.fetchone()
            cursor.execute(
                """
                SELECT t.id, t.rider_id, t.vehicle_id, t.fare_amount,
                       t.status, t.created_at, v.license_plate
                FROM trips t
                JOIN vehicles v ON v.id = t.vehicle_id
                WHERE t.rider_id = %s AND t.status = 'REQUESTED'
                ORDER BY t.id DESC
                LIMIT 1
                """,
                (rider_id,),
            )
            trip = cursor.fetchone()
        connection.commit()
    except BookingConflict:
        connection.rollback()
        raise
    except psycopg2.Error as exc:
        connection.rollback()
        raise BookingConflict(friendly_booking_error(exc)) from exc

    return {
        "trip": trip,
        "balance_before": rider_before["wallet_balance"],
        "balance_after": rider_after["wallet_balance"],
        "audit_entry": audit_entry,
    }
