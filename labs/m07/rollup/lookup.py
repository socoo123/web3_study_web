"""Opt-in, read-only recollection of R-25. Output is JSON Lines, not a 2026 head replay."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

from replay import L1_BLOCK, SYSTEM_CONFIG, TX

L2 = 'https://sepolia.optimism.io'
L1 = 'https://ethereum-sepolia-rpc.publicnode.com'
EXPLORER = 'https://testnet-explorer.optimism.io/api/v2'


def read(url, method=None, params=()):
    body = None if method is None else json.dumps({
        'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params,
    }).encode()
    headers = {'Accept': 'application/json'} if method is None else {'Content-Type': 'application/json'}
    req = Request(url, data=body, headers=headers)
    with urlopen(req, timeout=20) as res:
        reply = json.load(res)
    print(json.dumps({'utc': datetime.now(timezone.utc).isoformat(), 'url': url,
                      'method': method or 'GET', 'params': params, 'reply': reply}), flush=True)
    if method is None:
        return reply
    if reply.get('result') is None:
        raise ValueError(f'{method}: null or RPC error (see preceding response)')
    return reply['result']


def collect(include_index):
    for url, expected in ((L2, 11155420), (L1, 11155111)):
        if int(read(url, 'eth_chainId'), 16) != expected:
            raise ValueError('wrong network')
    for tag in ('latest', 'safe', 'finalized'):
        read(L2, 'eth_getBlockByNumber', [tag, False])
    read(L1, 'eth_getBlockByNumber', ['finalized', False])
    read(L2, 'eth_getTransactionByHash', [TX])
    rec = read(L2, 'eth_getTransactionReceipt', [TX])
    block = read(L2, 'eth_getBlockByNumber', [rec['blockNumber'], False])
    if block['hash'] != rec['blockHash'] or block['transactions'][int(rec['transactionIndex'], 16)] != TX:
        raise ValueError('L2 transaction not in numbered block at receipt position')
    ref = {'blockHash': block['hash'], 'requireCanonical': True}
    for selector in ('0x8381f58a', '0x09bd5a60'):  # L1Block.number(), L1Block.hash()
        read(L2, 'eth_call', [{'to': L1_BLOCK, 'data': selector}, ref])
    # These are known historical transactions. A new explorer lookup is not required
    # to ask either execution client for its own original receipt.
    sample = json.loads(Path(__file__).with_name('observation.json').read_text())
    batch_tx = sample['publication']['transaction']['hash']
    read(L1, 'eth_getTransactionByHash', [batch_tx])
    r = read(L1, 'eth_getTransactionReceipt', [batch_tx])
    b = read(L1, 'eth_getBlockByNumber', [r['blockNumber'], False])
    if b['hash'] != r['blockHash'] or b['transactions'][int(r['transactionIndex'], 16)] != batch_tx:
        raise ValueError('batcher transaction not in numbered L1 block at receipt position')
    read(L1, 'eth_call', [{'to': SYSTEM_CONFIG, 'data': '0xe81b2c6d'},
                          {'blockHash': b['hash'], 'requireCanonical': True}])
    if include_index:
        indexed = read(f"{EXPLORER}/blocks/{int(block['number'], 16)}")
        if indexed['hash'] != block['hash']:
            raise ValueError('block explorer and L2 node do not agree on the block')
        batch = read(f"{EXPLORER}/optimism/batches/{indexed['optimism']['number']}")
        if batch['l1_transaction_hashes'] != [batch_tx]:
            raise ValueError('live index does not link the observed block to the archived batch transaction')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', action='store_true', help='also recheck the explorer’s L2-to-L1 index')
    try:
        collect(parser.parse_args().index)
    except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
        sys.exit(f'STOP: evidence incomplete: {exc}')
