-- Workflow 2: 7-calendar-day moving average of fare revenue per vehicle,
-- ranked two ways via DENSE_RANK().
--
-- Assumption:
--   Only COMPLETED trips count as earned revenue.
--
-- Important:
--   The calendar is explicitly generated so that every vehicle has
--   exactly one row for every calendar date. Therefore,
--   ROWS BETWEEN 6 PRECEDING AND CURRENT ROW represents exactly
--   7 consecutive calendar days, including days with zero revenue.


WITH calendar AS (

    -- Generate one row for every calendar day.
    -- The range covers the last 365 days so that the query supports
    -- the 7/14/30/90/365 day analytics options.
    SELECT
        generate_series(
            CURRENT_DATE - INTERVAL '364 days',
            CURRENT_DATE,
            INTERVAL '1 day'
        )::date AS revenue_date
),

vehicles_calendar AS (

    -- Create one vehicle/date combination for every vehicle
    -- and every calendar day.
    SELECT
        v.id AS vehicle_id,
        c.revenue_date
    FROM vehicles v
    CROSS JOIN calendar c
),

daily_revenue AS (

    -- Calculate the total completed-trip revenue for each
    -- vehicle on each calendar day.
    SELECT
        vehicle_id,
        created_at::date AS revenue_date,
        SUM(fare_amount) AS daily_fare
    FROM trips
    WHERE status = 'COMPLETED'
      AND created_at::date >= CURRENT_DATE - INTERVAL '364 days'
      AND created_at::date <= CURRENT_DATE
    GROUP BY
        vehicle_id,
        created_at::date
),

calendar_revenue AS (

    -- Combine the complete vehicle/date calendar with actual revenue.
    --
    -- If a vehicle had no completed trip on a particular day,
    -- daily_fare becomes 0.
    SELECT
        vc.vehicle_id,
        vc.revenue_date,
        COALESCE(dr.daily_fare, 0) AS daily_fare
    FROM vehicles_calendar vc
    LEFT JOIN daily_revenue dr
        ON dr.vehicle_id = vc.vehicle_id
       AND dr.revenue_date = vc.revenue_date
),

moving_avg AS (

    -- Calculate the true 7-calendar-day moving average.
    --
    -- Because calendar_revenue contains one row for EVERY calendar
    -- day, ROWS BETWEEN 6 PRECEDING AND CURRENT ROW is exactly
    -- 7 consecutive calendar days.
    SELECT
        vehicle_id,
        revenue_date,
        daily_fare,

        ROUND(
            AVG(daily_fare) OVER (
                PARTITION BY vehicle_id
                ORDER BY revenue_date
                ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
            ),
            2
        ) AS moving_avg_7d

    FROM calendar_revenue
)

SELECT
    vehicle_id,
    revenue_date,
    daily_fare,
    moving_avg_7d,

    -- Which vehicle had the best 7-calendar-day average
    -- on this particular day?
    DENSE_RANK() OVER (
        PARTITION BY revenue_date
        ORDER BY moving_avg_7d DESC
    ) AS rank_vehicle_per_day,

    -- Which day had the best 7-calendar-day average
    -- for this particular vehicle?
    DENSE_RANK() OVER (
        PARTITION BY vehicle_id
        ORDER BY moving_avg_7d DESC
    ) AS rank_day_for_vehicle

FROM moving_avg

ORDER BY
    vehicle_id,
    revenue_date;