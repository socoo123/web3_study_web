-- One database follows exactly one M04 release, anchored at its event-free creation block.
BEGIN;
CREATE TABLE IF NOT EXISTS chain_block (
    chain_id bigint NOT NULL, height bigint NOT NULL, hash text NOT NULL,
    parent_hash text NOT NULL, canonical boolean NOT NULL,
    PRIMARY KEY (chain_id, hash)
);
CREATE UNIQUE INDEX IF NOT EXISTS canonical_height ON chain_block (chain_id, height) WHERE canonical;
CREATE TABLE IF NOT EXISTS scan_cursor (
    id integer PRIMARY KEY CHECK (id = 1), chain_id bigint NOT NULL, contract_address text NOT NULL,
    deploy_height bigint NOT NULL, deploy_hash text NOT NULL, height bigint NOT NULL, block_hash text NOT NULL,
    CHECK (height >= deploy_height), FOREIGN KEY (chain_id, block_hash) REFERENCES chain_block
);
CREATE TABLE IF NOT EXISTS escrow_log (
    chain_id bigint NOT NULL, block_hash text NOT NULL, tx_hash text NOT NULL, log_index bigint NOT NULL,
    address text NOT NULL, kind text NOT NULL CHECK (kind IN ('Locked','Settled','Refunded','Withdrawn')),
    actor text NOT NULL, amount_wei numeric(78,0) NOT NULL CHECK (amount_wei >= 0),
    PRIMARY KEY (chain_id, block_hash, tx_hash, log_index),
    FOREIGN KEY (chain_id, block_hash) REFERENCES chain_block
);
CREATE OR REPLACE VIEW canonical_log AS
    SELECT l.*, b.height FROM escrow_log l JOIN chain_block b ON (b.chain_id,b.hash)=(l.chain_id,l.block_hash)
    WHERE b.canonical;
COMMIT;
