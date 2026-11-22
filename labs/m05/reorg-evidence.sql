-- A single statement: the cursor, flags, audit and amounts all use one MVCC snapshot.
COPY (
  WITH scope AS (SELECT * FROM scan_cursor WHERE id=1),
  raw AS (
    SELECT b.height,b.canonical,l.block_hash,l.tx_hash,l.log_index,l.kind,l.actor,l.amount_wei::text AS wei
    FROM escrow_log l JOIN scope s ON (l.chain_id,l.address)=(s.chain_id,s.contract_address)
    JOIN chain_block b ON (b.chain_id,b.hash)=(l.chain_id,l.block_hash)
  ),
  actors AS (SELECT DISTINCT actor FROM raw), -- Include former beneficiaries even if now owed zero.
  live AS (SELECT l.* FROM canonical_log l JOIN scope s ON (l.chain_id,l.address)=(s.chain_id,s.contract_address)),
  balances AS (
    SELECT a.actor,
      sum(CASE WHEN l.kind IN ('Settled','Refunded') THEN l.amount_wei
               WHEN l.kind='Withdrawn' THEN -l.amount_wei ELSE 0 END)::text AS credit_wei,
      sum(CASE WHEN l.kind='Withdrawn' THEN l.amount_wei ELSE 0 END)::text AS received_wei
    FROM actors a LEFT JOIN live l ON l.actor=a.actor GROUP BY a.actor
  )
  SELECT json_build_object(
    'height',s.height,'hash',s.block_hash,
    'blocks',(SELECT json_agg(b ORDER BY b.height,b.hash) FROM chain_block b WHERE b.chain_id=s.chain_id),
    'logs',(SELECT json_agg(r ORDER BY r.height,r.block_hash,r.log_index) FROM raw r),
    'balances',(SELECT json_agg(v ORDER BY v.actor) FROM balances v),
    'audit',COALESCE((SELECT json_agg(j ORDER BY j.id) FROM reorg_audit j
                     WHERE (j.chain_id,j.contract_address)=(s.chain_id,s.contract_address)),'[]'::json))::jsonb
  FROM scope s
) TO STDOUT;
