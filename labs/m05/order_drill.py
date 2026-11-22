"""Run from repository root, on the M04 release held by the operator. Only the empty block mutates Anvil."""
from http.client import HTTPConnection
import json
import subprocess
import sys


def run(*args):
    subprocess.run(['bash', 'labs/m05/run.sh', *map(str, args)], check=True, stdout=sys.stderr)


def read(order, expected, key=None, claim=None):
    c = HTTPConnection('127.0.0.1', 18020, timeout=20)
    try:
        path = '/orders/' + order
        if key is None:
            c.request('GET', path)
        else:
            c.request('POST', path + '/callbacks/' + key, json.dumps({'amountWei': str(claim)}),
                      {'Content-Type': 'application/json'})
        resp = c.getresponse()
        result = json.load(resp)
        if resp.status != 200 or result.get('decision') != expected:
            raise ValueError(f'{order}: expected {expected}, HTTP {resp.status}: {result}')
        print(json.dumps(result, separators=(',', ':')), flush=True)
        return result
    finally:
        c.close()


def drill(amount):
    # Lab-only counterfactuals: retire an unbooked intent before creating another. Never reassign a booked order.
    run('OrderIntent', 'create', 'short-20', 'native:31337', amount + 1, 1)
    short = read('short-20', 'HOLD_AMOUNT', 'cart', amount + 1)
    if short['differenceWei'] != '1' or short['observed']['amountWei'] != str(amount):
        raise ValueError('the release is not the funding amount supplied to this drill')
    run('OrderIntent', 'retire', 'short-20')
    run('OrderIntent', 'create', 'asset-20', 'invoice:USD', amount, 1)
    asset = read('asset-20', 'HOLD_ASSET', 'cart', amount)
    if 'differenceWei' in asset or asset['bookingEvidence'] is not None:
        raise ValueError('cross-asset subtraction or unexpected booking')
    run('OrderIntent', 'retire', 'asset-20')
    # With a fresh --settle-wei release this asks for 2 confirmations; on an older release, ask for one more.
    run('OrderIntent', 'create', 'match-20', 'native:31337', amount, short['confirmations'] + 1)
    read('match-20', 'HOLD_DEPTH')
    subprocess.run(['cast', 'rpc', '--rpc-url', 'http://127.0.0.1:18556', 'evm_mine'], check=True, stdout=sys.stderr)
    lag = read('match-20', 'HOLD_LAG')
    if lag['lagBlocks'] != 1: raise ValueError('run this drill without other writers')
    run('Scan')
    read('match-20', 'READY_TO_BOOK')
    first = read('match-20', 'BOOKED_AT_HEAD', 'hint-a', 0)
    retry = read('match-20', 'BOOKED_AT_HEAD', 'hint-a', amount + 999)
    other = read('match-20', 'BOOKED_AT_HEAD', 'hint-b', 1)
    if (not first['newHint'] or retry['newHint'] or not other['newHint'] or
            not (first['bookingEvidence'] == retry['bookingEvidence'] == other['bookingEvidence'])):
        raise ValueError('callback key or booked evidence changed unexpectedly')
    sql = """SELECT (SELECT count(*) FROM order_booking WHERE order_id IN ('short-20','asset-20','match-20')) AS bookings,
                    (SELECT count(*) FROM order_outbox WHERE order_id IN ('short-20','asset-20','match-20')) AS notices,
                    (SELECT count(*) FROM callback_hint WHERE order_id='match-20') AS distinct_match_hints;"""
    subprocess.run(['bash', 'labs/m05/db.sh', 'sql'], input=sql, text=True, check=True, stdout=sys.stderr)


if __name__ == '__main__':
    if len(sys.argv) != 2 or not sys.argv[1].isascii() or not sys.argv[1].isdecimal() or not (0 < int(sys.argv[1]) <= 10**18):
        sys.exit('usage: python3 labs/m05/order_drill.py SETTLED_WEI (1..10^18)')
    drill(int(sys.argv[1]))
