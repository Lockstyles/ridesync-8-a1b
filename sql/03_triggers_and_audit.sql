CREATE OR REPLACE FUNCTION log_wallet_change()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO wallet_audit_logs (
        rider_id,
        amount_changed,
        action_type,
        balance_after
    )
    VALUES (
        NEW.id,
        NEW.wallet_balance - OLD.wallet_balance,
        CASE
            WHEN NEW.wallet_balance > OLD.wallet_balance THEN 'CREDIT'
            ELSE 'DEBIT'
        END,
        NEW.wallet_balance
    );

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


CREATE OR REPLACE TRIGGER trg_rider_wallet_audit
AFTER UPDATE OF wallet_balance ON riders
FOR EACH ROW
WHEN (OLD.wallet_balance IS DISTINCT FROM NEW.wallet_balance)
EXECUTE FUNCTION log_wallet_change();


-- Audit rows are append-only.  A statement-level trigger also catches
-- zero-row UPDATE/DELETE statements, while the TRUNCATE event prevents the
-- table from being emptied without explicitly disabling this guard for a
-- maintenance operation.
CREATE OR REPLACE FUNCTION prevent_wallet_audit_log_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'wallet_audit_logs is immutable: % is not allowed', TG_OP
        USING ERRCODE = '55000';
END;
$$ LANGUAGE plpgsql;


CREATE OR REPLACE TRIGGER trg_wallet_audit_logs_immutable
BEFORE UPDATE OR DELETE OR TRUNCATE ON wallet_audit_logs
FOR EACH STATEMENT
EXECUTE FUNCTION prevent_wallet_audit_log_mutation();
