"""Read the GraphQL and SQL views independently and trace every fact back to its log."""
from http.client import HTTPConnection
import json

from fixture import require, rpc

QUERY = '''query Page($at: Block_height!) {
  _meta(block: $at) { deployment hasIndexingErrors block { number hash } }
  postings(block: $at, first: 10, orderBy: height, orderDirection: asc) {
    height blockHash txHash logIndex address kind actor amountWei
  }
}'''


def post(port, path, obj):
    conn = HTTPConnection('127.0.0.1', port, timeout=20)
    try:
        conn.request('POST', path, json.dumps(obj), {'Content-Type': 'application/json'})
        res = conn.getresponse()
        body = res.read()
        if res.status != 200:
            raise OSError(f'{port}{path}: HTTP {res.status}: {body[:600]!r}')
        return json.loads(body)
    finally:
        conn.close()


def graph(query, variables=None):
    res = post(19340, '/subgraphs/name/course/escrow', {'query': query, 'variables': variables or {}})
    if res.get('errors'):
        raise ValueError(f'GraphQL: {res["errors"]}')
    return res['data']


def sample(sql, manifest, receipts, cid, height):
    block = rpc('eth_getBlockByNumber', hex(height), False)
    h = block['hash']
    view = graph(QUERY, {'at': {'hash': h}})
    meta = view['_meta']
    require(meta['deployment'] == cid and not meta['hasIndexingErrors'] and
            meta['block'] == {'number': height, 'hash': h}, 'wrong subgraph, query block or indexing error')
    # For M05 this is a prefix of immutable facts on the current canonical branch, not a SQL time machine.
    java = json.loads(sql(f'''SELECT json_build_object(
      'cursor', (SELECT row_to_json(c) FROM scan_cursor c),
      'blockHash', (SELECT hash FROM chain_block WHERE canonical AND height={height}),
      'postings', COALESCE((SELECT json_agg(row_to_json(p) ORDER BY p.height::bigint, p."logIndex"::bigint)
        FROM (SELECT height::text, block_hash AS "blockHash", tx_hash AS "txHash", log_index::text AS "logIndex",
                     address, kind, actor, amount_wei::text AS "amountWei"
                FROM canonical_log WHERE height <= {height}) p), '[]'::json));'''))
    cursor = java['cursor']
    require(java['blockHash'] == h and cursor['height'] >= height and
            cursor['chain_id'] == manifest['chainId'] and cursor['contract_address'] == manifest['contractAddress'] and
            cursor['deploy_hash'] == manifest['deploymentBlockHash'] and cursor['deploy_height'] == 1 and
            cursor['block_hash'] == rpc('eth_getBlockByNumber', hex(cursor['height']), False)['hash'],
            'Java cursor not anchored to source/deployment/query height')
    # Independent receipt witness: decode original topic/data words, not copies of either view.
    kinds = {rpc('web3_sha3', '0x' + (k + '(address,uint256)').encode().hex()): k
             for k in ['Locked', 'Settled', 'Refunded', 'Withdrawn']}
    raw = []
    for archived in receipts.values():
        if int(archived['blockNumber'], 16) > height:
            continue
        r = rpc('eth_getTransactionReceipt', archived['transactionHash'])
        require(r == archived and r['status'] == '0x1' and
                rpc('eth_getBlockByNumber', r['blockNumber'], False)['hash'] == r['blockHash'], 'changed receipt')
        for log in r['logs']:
            sig, indexed = log['topics']
            require(log['address'] == manifest['contractAddress'] and indexed[:26] == '0x' + '0' * 24
                    and len(indexed) == len(log['data']) == 66, 'unexpected receipt ABI or emitter')
            raw.append({'height': str(int(log['blockNumber'], 16)), 'blockHash': log['blockHash'],
                        'txHash': log['transactionHash'], 'logIndex': str(int(log['logIndex'], 16)),
                        'address': log['address'], 'kind': kinds[sig], 'actor': '0x' + indexed[-40:],
                        'amountWei': str(int(log['data'], 16))})
    require(raw and len(raw) < 10, 'this single-order exercise requires a nonempty, complete first page')
    require(rpc('eth_getBlockByNumber', hex(height), False)['hash'] == h, 'source changed while querying')
    return {'height': height, 'hash': h, 'graph': view, 'java': java, 'receiptRows': raw,
            'match': view['postings'] == java['postings'] == raw}
