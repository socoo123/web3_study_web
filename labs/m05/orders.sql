-- Apply after schema.sql. Each database is a private, one-release teaching ledger.
BEGIN;
CREATE TABLE IF NOT EXISTS payment_intent (
    id text PRIMARY KEY, chain_id bigint NOT NULL, contract_address text NOT NULL,
    deploy_height bigint NOT NULL, deploy_hash text NOT NULL, payee text NOT NULL,
    asset text NOT NULL, expected_units numeric(78,0) NOT NULL CHECK (expected_units > 0),
    min_depth integer NOT NULL CHECK (min_depth > 0), active boolean NOT NULL DEFAULT true,
    FOREIGN KEY (chain_id, deploy_hash) REFERENCES chain_block
);
-- The teaching escrow owns exactly one order. Only unbooked test scenarios can retire.
CREATE UNIQUE INDEX IF NOT EXISTS one_live_intent
    ON payment_intent(chain_id, contract_address, deploy_hash) WHERE active;
CREATE TABLE IF NOT EXISTS callback_hint (
    order_id text REFERENCES payment_intent, hint_key text NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (order_id, hint_key)
);
CREATE TABLE IF NOT EXISTS order_booking (
    order_id text PRIMARY KEY REFERENCES payment_intent,
    chain_id bigint NOT NULL, block_hash text NOT NULL, tx_hash text NOT NULL, log_index bigint NOT NULL,
    booked_at timestamptz NOT NULL DEFAULT now(), UNIQUE(chain_id, block_hash, tx_hash, log_index),
    FOREIGN KEY (chain_id, block_hash, tx_hash, log_index) REFERENCES escrow_log
);
-- A durable notification of an accounting observation, NOT an instruction to ship.
CREATE TABLE IF NOT EXISTS order_outbox (
    order_id text PRIMARY KEY REFERENCES order_booking,
    kind text NOT NULL CHECK (kind = 'ENTITLEMENT_RECORDED'), created_at timestamptz NOT NULL DEFAULT now()
);
COMMIT;
