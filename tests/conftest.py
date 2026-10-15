RESULT_DETAILS = {
    "test_booking_success_updates_balance_and_audit": (
        "Booking success: balance changes 1000.00 -> 750.00, DEBIT audit entry is created, "
        "trip 42 is returned, and the transaction commits."
    ),
    "test_booking_failure_rolls_back_on_active_trip_conflict": (
        "Active-trip conflict: BookingConflict is raised, the transaction rolls back, "
        "and no commit occurs."
    ),
    "test_insufficient_balance_error_is_friendly": (
        "Insufficient balance: database error is converted into a clear rider-facing message."
    ),
    "test_revenue_analytics_returns_moving_average_and_dense_rank": (
        "Revenue analytics: 7-day moving average is 650.00, DENSE_RANK result is 1, "
        "and the analytics query contains DENSE_RANK()."
    ),
    "test_map_uses_geonear_and_limits_results_to_50": (
        "Map: $geoNear is used with a 5 km radius, only available vehicles are queried, "
        "and the aggregation limits results to 50."
    ),
    "test_reviews_facet_returns_rating_tags_and_average": (
        "Reviews: $facet is used to calculate average rating, total reviews, rating "
        "distribution, and top feedback tags."
    ),
}

_RESULTS = []


def pytest_sessionstart(session):
    _RESULTS.clear()


def pytest_runtest_logreport(report):
    if report.when != "call":
        return

    name = report.nodeid.rsplit("::", 1)[-1]
    _RESULTS.append((name, report.outcome))


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if not _RESULTS:
        return

    terminalreporter.write_sep("=", "RideSync critical test results")

    for name, outcome in _RESULTS:
        detail = RESULT_DETAILS.get(name, "Critical RideSync test completed.")
        status = "PASS" if outcome == "passed" else outcome.upper()
        terminalreporter.write_line(f"{status}: {detail}")
