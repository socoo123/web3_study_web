"""Read one local desk order and corroborate its Settled receipt; never book or pay."""
import argparse
from datetime import datetime, timezone
from http.client import HTTPConnection, HTTPException
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'm04'))
from handoff import require, rpc, verify


def view(order):
    conn = HTTPConnection('127.0.0.1', 18020, timeout=12)
    try:
        conn.request('GET', '/orders/' + order)
        resp = conn.getresponse()
        return resp.status, json.load(resp)
    finally:
        conn.close()


def witness(args, packet):
    status, order = view(args.order)
    packet.update(http=status, order=order)
    require(status == 200, f'order service returned HTTP {status}')
    intent = order['intent']
    require(intent['id'] == args.order, 'order ID mismatch')
    event = order.get('observed')  # Never substitute bookingEvidence from an old head.
    if event is None:
        return 'HOLD_ORDER'

    release = verify(json.loads(args.manifest.read_text()))  # M04 pins code, creation and read block.
    head = release['readBlockNumber']
    require((order['headHeight'], order['headHash']) == (head, release['readBlockHash']) ==
            (order['cursorHeight'], order['cursorHash']), 'head/cursor changed; reread')
    anchor = intent['release']
    require((anchor['chainId'], anchor['deployHeight'], anchor['deployHash'],
             anchor['contractAddress'], anchor['payee']) ==
            (release['chainId'], release['deploymentBlockNumber'], release['deploymentBlockHash'],
             release['contractAddress'].lower(), release['payee']), 'wrong order release')

    tx = event['txHash']
    receipt = rpc('eth_getTransactionReceipt', tx)
    require(receipt and receipt['status'] == '0x1' and receipt['transactionHash'] == tx and
            receipt['blockHash'] == event['blockHash'], 'missing or changed receipt')
    height = int(receipt['blockNumber'], 16)
    block = rpc('eth_getBlockByNumber', hex(height), False)
    require(release['deploymentBlockNumber'] <= height <= head and height == event['height'] and
            block and block['hash'] == receipt['blockHash'] and tx in block['transactions'],
            'receipt is not on the observed canonical block')
    rows = [log for log in receipt['logs'] if int(log['logIndex'], 16) == event['logIndex']]
    require(len(rows) == 1, 'wrong log index')
    log = rows[0]
    topic = rpc('web3_sha3', '0x' + b'Settled(address,uint256)'.hex())
    require(not log.get('removed', False) and log['address'].lower() == anchor['contractAddress'] and
            log['topics'] == [topic, '0x' + anchor['payee'][2:].rjust(64, '0')] and
            re.fullmatch(r'0x[0-9a-fA-F]{64}', log['data']), 'not the settlement to this payee')
    amount = str(int(log['data'], 16))
    require((event['chainId'], event['address'], event['kind'], event['actor'], event['amountWei']) ==
            (31337, anchor['contractAddress'], 'Settled', anchor['payee'], amount), 'index differs from raw log')
    depth = head - height + 1
    require(rpc('eth_getBlockByNumber', 'latest', False)['hash'] == order['headHash'], 'head moved; reread')
    packet.update(receipt=receipt, confirmedAtHead=order['headHash'], settledWei=amount,
                  confirmations=depth, requiredDepth=max(args.depth, intent['minDepth']))
    if order['decision'] != 'BOOKED_AT_HEAD':
        return 'HOLD_ORDER'
    require(intent['active'] and intent['asset'] == 'native:31337' and intent['expectedUnits'] == amount and
            depth == order['confirmations'] >= intent['minDepth'] and order['bookingEvidence'] == event,
            'booking does not match its terms and raw receipt')
    return 'MATCH' if depth >= packet['requiredDepth'] else 'WAIT_EXTRA_DEPTH'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('order')
    parser.add_argument('--depth', type=int, required=True, help='reviewer minimum confirmations (1..64)')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', args.order) or not 1 <= args.depth <= 64:
        parser.error('invalid course order ID or review depth (1..64)')
    packet = {'orderId': args.order, 'reviewDepth': args.depth}
    try:
        outcome = witness(args, packet)
    except (OSError, HTTPException, ValueError, TypeError, KeyError) as exc:
        outcome = 'UNVERIFIED'
        packet['reason'] = str(exc)
    packet.update(outcome=outcome, recordedUtc=datetime.now(timezone.utc).isoformat())
    print(json.dumps(packet, indent=2, ensure_ascii=False))
    print(outcome, file=sys.stderr)
    return 0 if outcome == 'MATCH' else 3


if __name__ == '__main__':
    sys.exit(main())
