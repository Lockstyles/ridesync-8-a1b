CREATE TABLE riders (
    id              INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            VARCHAR(100) NOT NULL UNIQUE,
    wallet_balance  DECIMAL(10,2) NOT NULL,
    CONSTRAINT chk_riders_wallet_balance
        CHECK (wallet_balance >= 0.00)
);

CREATE TABLE wallet_audit_logs (
    id              INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rider_id        INT NOT NULL REFERENCES riders(id),
    amount_changed  DECIMAL(10,2) NOT NULL,
    action_type     VARCHAR(10) NOT NULL,
    balance_after   DECIMAL(10,2) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (action_type IN ('CREDIT', 'DEBIT')),
    CHECK (balance_after >= 0.00)
);

CREATE TABLE vehicles (
    id              INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    license_plate   VARCHAR(20) NOT NULL UNIQUE,
    class           VARCHAR(50) NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE trips (
    id              INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rider_id        INT NOT NULL REFERENCES riders(id),
    vehicle_id      INT NOT NULL REFERENCES vehicles(id),
    fare_amount     DECIMAL(10,2) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'REQUESTED',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_trips_status
        CHECK (status IN ('REQUESTED', 'IN TRANSIT', 'COMPLETED')),
    CONSTRAINT chk_trips_fare_non_negative
        CHECK (fare_amount >= 0.00)
);

