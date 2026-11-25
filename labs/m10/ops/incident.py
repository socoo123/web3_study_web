"""M10 handoff conductor; calls the original M04/M05 programs, never signs or broadcasts."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys

from outage import order_api, require, stamp, verify

LABS = Path(__file__).resolve().parents[2]
M05 = LABS / 'm05'
ORDER = 'OPS-39'


def record(path, obj):
    with path.open('x') as f:
        json.dump(obj, f, indent=2)
        f.write('\n')


def load(path):
    return json.loads(path.read_text())


def env(db, manifest):
    return {**os.environ, 'M05_DB': db, 'M05_MANIFEST': str(manifest)}


def dbtool(db, action, **kwargs):
    return subprocess.run(['bash', str(M05 / 'db.sh'), action], env={**os.environ, 'M05_DB': db}, check=True, **kwargs)


def java(db, manifest, *args):
    result = subprocess.run(['bash', str(M05 / 'run.sh'), *args], env=env(db, manifest), check=True,
                            stdout=subprocess.PIPE, text=True)
    print(result.stdout, end='')
    return result.stdout


def ledger(db):
    # A machine-readable, single-statement snapshot, not separate time-of-check counts.
    sql = """\\set QUIET on
\\pset format unaligned
\\pset tuples_only on
SELECT json_build_object('height',height,'hash',block_hash,
 'orders',(SELECT count(*) FROM payment_intent WHERE active),
 'logs',(SELECT count(*) FROM canonical_log), 'bookings',(SELECT count(*) FROM order_booking),
 'outbox',(SELECT count(*) FROM order_outbox), 'hints',(SELECT count(*) FROM callback_hint)) FROM scan_cursor WHERE id=1;
"""
    return json.loads(dbtool(db, 'sql', input=sql, capture_output=True, text=True).stdout)


def run_app(db, manifest):
    print(f'OrderApp on 127.0.0.1:18020; database={db}. Ctrl-C stops this app, not the node.', flush=True)
    os.execvpe('bash', ['bash', str(M05 / 'run.sh'), 'OrderApp'], env(db, manifest))


def no_other_app():
    with socket.socket() as s:
        require(s.connect_ex(('127.0.0.1', 18020)) != 0, 'stop the previous OrderApp/desk; never serve two databases')


def prepare(manifest, ops):
    no_other_app()
    before = verify(load(manifest))
    require(before['state'] == 0 and before['readBlockNumber'] == before['deploymentBlockNumber'] == 1,
            'start an unpaid, new --hold release at block 1')
    ops.mkdir(mode=0o700)
    tag = secrets.token_hex(5)
    source, restored = 'm05_s' + tag, 'm05_r' + tag
    dbtool('m05', 'sql', input=f'CREATE DATABASE {source};\n', text=True)
    for name in ('schema.sql', 'orders.sql'):
        with (M05 / name).open('rb') as f:
            dbtool(source, 'sql', stdin=f)
    java(source, manifest, 'Scan')
    java(source, manifest, 'OrderIntent', 'create', ORDER, 'native:31337', '125', '2')
    snapshot = ledger(source)
    require(snapshot == dict(height=1, hash=before['deploymentBlockHash'], orders=1, logs=0, bookings=0, outbox=0, hints=0),
            'unexpected backup point')
    dump = ops / 'before-payment.dump'
    with dump.open('xb') as f:
        dbtool(source, 'dump', stdout=f)
    record(ops / 'backup.json', dict(takenAt=stamp(), sourceDb=source, restoreDb=restored, ledger=snapshot,
                                     deployHash=before['deploymentBlockHash'], contractAddress=before['contractAddress'],
                                     dumpSha256=sha256(dump.read_bytes()).hexdigest()))
    run_app(source, manifest)


def restore(manifest, ops):
    no_other_app()
    meta = load(ops / 'backup.json')
    incident = load(ops / 'outage.json')
    now = verify(load(manifest))
    require(incident['verdict'] == 'RPC_RESTORED_SAME_HEAD' and incident['order'] == ORDER
            and incident['after']['decision'] == 'HOLD_LAG' and incident['headHash'] == now['readBlockHash']
            and incident['deployHash'] == meta['deployHash'] == now['deploymentBlockHash'], 'unexpected recovery target')
    require(ledger(meta['sourceDb']) == meta['ledger'], 'old DB moved, or failed callback committed; stop')
    dump = ops / 'before-payment.dump'
    require(sha256(dump.read_bytes()).hexdigest() == meta['dumpSha256'], 'dump fingerprint mismatch')
    with dump.open('rb') as f:
        dbtool(meta['restoreDb'], 'restore', stdin=f)  # createdb must succeed: no in-place overwrite.
    snapshot = ledger(meta['restoreDb'])
    require(snapshot == meta['ledger'], 'restored ledger differs from backup')
    record(ops / 'restored.json', dict(restoredAt=stamp(), database=meta['restoreDb'], ledger=snapshot))
    run_app(meta['restoreDb'], manifest)


def audit(manifest, ops):
    db = load(ops / 'restored.json')['database']
    status, lag = order_api(ORDER)
    require(status == 200 and lag['decision'] == 'HOLD_LAG' and (lag['headHeight'], lag['cursorHeight']) == (4, 1),
            'expected a real unscanned interval: 2..4')
    caught = java(db, manifest, 'Recover')
    status, ready = order_api(ORDER)
    event = ready.get('observed') or {}
    require(status == 200 and ready.get('confirmations') == 2 and event.get('kind') == 'Settled',
            'no confirmed settlement on restored DB; check service routing')
    payer_receipt = load(ops / 'settle.json')
    require(payer_receipt['transactionHash'] == event['txHash'] and payer_receipt['blockHash'] == event['blockHash']
            and event['height'] == 3, 'payer receipt and journal anchors differ')
    delta = 125 - int(event['amountWei'])
    require(ready['decision'] == ('READY_TO_BOOK' if delta == 0 else 'HOLD_AMOUNT')
            and ready['differenceWei'] == str(delta), 'wrong reconciliation decision')
    expected = 'BOOKED_AT_HEAD' if delta == 0 else 'HOLD_AMOUNT'
    status, first = order_api(ORDER, 'retry-39')
    require(status == 200 and first['newHint'] and first['decision'] == expected, 'first callback not accepted as expected')
    counts = ledger(db)
    replay = java(db, manifest, 'Scan', '2')
    status, second = order_api(ORDER, 'retry-39')
    require(status == 200 and not second['newHint'] and second['decision'] == expected
            and second['bookingEvidence'] == first['bookingEvidence'] == (event if delta == 0 else None)
            and second['mayNotifyAsOfHead'] == (delta == 0), 'callback replay changed evidence or permission')
    require('matched=2 inserted=0 cursor=4' in replay and ledger(db) == counts == dict(height=4, hash=ready['headHash'],
            orders=1, logs=2, bookings=int(delta == 0), outbox=int(delta == 0), hints=1), 'unexpected replay counts')
    # Independent read-only reviewer: validate the receipt on the live canonical block, not a file.
    check = subprocess.run([sys.executable, str(LABS / 'm10/demo/witness.py'), str(manifest), ORDER, '--depth', '2'],
                           stdout=subprocess.PIPE, text=True)
    witness = json.loads(check.stdout)
    require(check.returncode == (0 if delta == 0 else 3) and witness['outcome'] == ('MATCH' if delta == 0 else 'HOLD_ORDER')
            and witness['settledWei'] == event['amountWei'] and witness['receipt']['transactionHash'] == event['txHash'],
            'independent receipt check failed')
    record(ops / 'audit.json', dict(reviewedAt=stamp(), lag=lag, recover=caught, beforeCallback=ready, first=first,
                                    replay=replay, second=second, ledger=counts, witness=witness))
    print(f"{expected} differenceWei={delta} bookings={counts['bookings']} outbox={counts['outbox']} hints=1")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'restore', 'audit'))
    parser.add_argument('work', type=Path)
    args = parser.parse_args()
    work = args.work.resolve()
    manifest, ops = work / 'release/manifest.json', work / 'ops'
    if args.action == 'prepare':
        prepare(manifest, ops)
    elif args.action == 'restore':
        restore(manifest, ops)
    else:
        audit(manifest, ops)
