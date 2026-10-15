from decimal import Decimal
from unittest.mock import MagicMock

import psycopg2
import pytest

from api import main
from api.services import BookingConflict, book_trip, friendly_booking_error


def connection_with_cursor():
    connection = MagicMock()
    cursor = MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor
    return connection, cursor


def test_booking_success_updates_balance_and_audit():
    connection, cursor = connection_with_cursor()
    cursor.fetchone.side_effect = [
        {"id": 7, "name": "Asha", "wallet_balance": Decimal("1000.00")},
        {"id": 7, "name": "Asha", "wallet_balance": Decimal("750.00")},
        {
            "id": 91,
            "rider_id": 7,
            "amount_changed": Decimal("-250.00"),
            "action_type": "DEBIT",
            "balance_after": Decimal("750.00"),
        },
        {"id": 42, "rider_id": 7, "vehicle_id": 3, "status": "REQUESTED"},
    ]

    result = book_trip(connection, 7, 3, Decimal("250.00"))

    assert result["balance_before"] == Decimal("1000.00")
    assert result["balance_after"] == Decimal("750.00")
    assert result["audit_entry"]["action_type"] == "DEBIT"
    assert result["trip"]["id"] == 42
    connection.commit.assert_called_once()
    connection.rollback.assert_not_called()


def test_booking_failure_rolls_back_on_active_trip_conflict():
    connection, cursor = connection_with_cursor()
    cursor.fetchone.return_value = {
        "id": 7,
        "name": "Asha",
        "wallet_balance": Decimal("1000.00"),
    }
    cursor.execute.side_effect = [
        None,
        psycopg2.IntegrityError(
            'duplicate key value violates unique constraint "idx_active_rider_trip"'
        ),
    ]

    with pytest.raises(BookingConflict, match="already has an active trip"):
        book_trip(connection, 7, 3, Decimal("250.00"))

    connection.rollback.assert_called_once()
    connection.commit.assert_not_called()


def test_insufficient_balance_error_is_friendly():
    error = psycopg2.DatabaseError(
        "Insufficient wallet balance. Balance: 100.00, Fare: 250.00"
    )
    assert friendly_booking_error(error) == (
        "The rider does not have enough wallet balance for this fare."
    )


def test_revenue_analytics_returns_moving_average_and_dense_rank(monkeypatch):
    connection, cursor = connection_with_cursor()
    cursor.fetchall.side_effect = [
        [
            {
                "vehicle_id": 1,
                "license_plate": "TS01AA1234",
                "revenue_date": "2026-10-15",
                "daily_fare": Decimal("700.00"),
                "moving_avg_7d": Decimal("650.00"),
                "rank_vehicle_per_day": 1,
                "rank_day_for_vehicle": 1,
            }
        ],
        [
            {
                "vehicle_id": 1,
                "license_plate": "TS01AA1234",
                "revenue_date": "2026-10-15",
                "moving_avg_7d": Decimal("650.00"),
                "rank_vehicle_per_day": 1,
            }
        ],
    ]
    monkeypatch.setattr(main, "postgres_connection", lambda: connection)

    result = main.revenue_analytics(days=30)

    assert result["days"] == 30
    assert result["series"][0]["moving_avg_7d"] == Decimal("650.00")
    assert result["series"][0]["rank_vehicle_per_day"] == 1
    assert result["latest_rankings"][0]["rank_vehicle_per_day"] == 1
    assert "DENSE_RANK" in main.REVENUE_CTE


def test_map_uses_geonear_and_limits_results_to_50(monkeypatch):
    collection = MagicMock()
    collection.aggregate.return_value = [
        {"vehicle_id": i, "distance_m": float(i * 100)} for i in range(1, 51)
    ]
    mongo = MagicMock()
    mongo.TelemetryPings = collection
    monkeypatch.setattr(main, "mongo_database", lambda: mongo)

    result = main.nearby_vehicles(lat=17.4454, lon=78.3489, radius_m=5000)

    assert len(result["vehicles"]) == 50
    pipeline = collection.aggregate.call_args.args[0]
    assert "$geoNear" in pipeline[0]
    assert pipeline[0]["$geoNear"]["maxDistance"] == 5000
    assert pipeline[3]["$limit"] == 50
    assert pipeline[0]["$geoNear"]["query"]["is_available"] is True


def test_reviews_facet_returns_rating_tags_and_average(monkeypatch):
    collection = MagicMock()
    collection.aggregate.return_value = iter(
        [
            {
                "rating_distribution": [
                    {"rating": 5, "count": 80},
                    {"rating": 4, "count": 20},
                ],
                "top_feedback_tags": [{"tag": "clean", "count": 70}],
                "overall": [{"average_rating": 4.8, "total_reviews": 100}],
            }
        ]
    )
    mongo = MagicMock()
    mongo.TripReviews = collection
    monkeypatch.setattr(main, "mongo_database", lambda: mongo)

    result = main.review_analytics(city="Hyderabad", days=90)

    assert result["average_rating"] == 4.8
    assert result["total_reviews"] == 100
    assert result["rating_distribution"][0]["rating"] == 5
    assert result["top_feedback_tags"][0]["tag"] == "clean"
    pipeline = collection.aggregate.call_args.args[0]
    assert "$facet" in pipeline[1]
