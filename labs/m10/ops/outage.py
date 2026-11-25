"""Pause only the verified local M04 node. Exercise the real M05 API; never send a chain transaction."""
import argparse
from datetime import datetime, timezone
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'm04'))
from handoff import PORT, verify


def require(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def order_api(order, key=None):
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', order), 'invalid local order id')
    conn = HTTPConnection('127.0.0.1', 18020, timeout=16)  # M05 Web3j has an 8 s call deadline.
    try:
        path = '/orders/' + order
        if key is None:
            conn.request('GET', path)
        else:
            conn.request('POST', path + '/callbacks/' + key, '{}', {'Content-Type': 'application/json'})
        response = conn.getresponse()
        return response.status, json.load(response)
    finally:
        conn.close()


def node_pid():
    rows = subprocess.check_output(['lsof', '-nP', '-a', f'-iTCP:{PORT}', '-sTCP:LISTEN', '-Fpn'], text=True).splitlines()
    pids = [int(row[1:]) for row in rows if row.startswith('p')]
    require(len(pids) == 1 and [row for row in rows if row.startswith('n')] == [f'n127.0.0.1:{PORT}'],
            'expected one loopback-only listener, no signal sent')
    pid = pids[0]

    def ps(process, field):
        return subprocess.check_output(['ps', '-p', str(process), '-o', field + '='], text=True).strip()

    require(int(ps(pid, 'uid')) == os.getuid() and Path(ps(pid, 'comm')).name == 'anvil',
            'listener is not this user’s Anvil')
    parent = ps(int(ps(pid, 'ppid')), 'args')
    require('deployment.py' in parent and '--hold' in parent.split(), 'not an M04 --hold child')
    return pid


def expect_rpc_timeout():
    conn = HTTPConnection('127.0.0.1', PORT, timeout=1)
    try:
        conn.request('POST', '/', '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}',
                     {'Content-Type': 'application/json'})
        try:
            conn.getresponse()
        except TimeoutError:
            return 'response_timeout'
        raise RuntimeError('RPC replied while its verified process was paused')
    finally:
        conn.close()


def interrupt(signum, frame):
    raise SystemExit(f'interrupted by signal {signum}')


def exercise(manifest_path, order, report):
    manifest = json.loads(manifest_path.read_text())
    identity = verify(manifest)
    status, before = order_api(order)
    release = before.get('intent', {}).get('release', {})
    require(status == 200 and release.get('deployHash') == identity['deploymentBlockHash']
            and release.get('contractAddress', '').lower() == identity['contractAddress'].lower(),
            'wrong order, unavailable API or wrong deployment; no fault injected')
    pid = node_pid()
    report.update(order=order, pid=pid, deployHash=identity['deploymentBlockHash'], headHash=identity['readBlockHash'],
                  before=before, pausedAt=stamp())
    print(f'Pausing owned Anvil PID={pid}; emergency resume only this PID: kill -CONT {pid}', flush=True)
    started = time.monotonic()
    old = signal.signal(signal.SIGTERM, interrupt)
    try:
        os.kill(pid, signal.SIGSTOP)
        report['rpcProbe'] = expect_rpc_timeout()
        status, alert = order_api(order, 'outage-39')
        report.update(alertAt=stamp(), http=status, during=alert)
        print(f"ALERT HTTP {status} {alert.get('decision')} mayNotify={alert.get('mayNotifyAsOfHead')}", flush=True)
        require(status == 503 and alert.get('decision') == 'HOLD_UNAVAILABLE'
                and alert.get('mayNotifyAsOfHead') is False, 'M05 did not fail closed')
    finally:
        os.kill(pid, signal.SIGCONT)
        signal.signal(signal.SIGTERM, old)
        report['resumedAt'] = stamp()
        report['pauseSeconds'] = round(time.monotonic() - started, 3)
    current = verify(manifest)
    status, after = order_api(order)
    require(status == 200 and current['readBlockHash'] == identity['readBlockHash'] and
            before['decision'] == after['decision'] and before['bookingEvidence'] == after['bookingEvidence'],
            'head, decision or booking changed; isolate and investigate other writers')
    report.update(after=after, verdict='RPC_RESTORED_SAME_HEAD')
    print(f"RPC_RESTORED_SAME_HEAD after={after['decision']} head={current['readBlockNumber']}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('order')
    parser.add_argument('new_report', type=Path)
    args = parser.parse_args()
    report = {'verdict': 'INCOMPLETE'}
    with args.new_report.open('x') as destination:
        try:
            exercise(args.manifest, args.order, report)
        finally:
            json.dump(report, destination, indent=2)
            destination.write('\n')
