"""Drive two real histories of one disposable M04 deployment, recording SQL and RPC evidence."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
from secrets import token_hex
import subprocess
import sys

HERE = Path(__file__).resolve().parent
M04 = HERE.parent / 'm04'
sys.path[:0] = [str(M04), str(HERE.parent)]
from anvil_lab import send_mined
from handoff import rpc, selector


def require(ok, explanation):
    if not ok:
        raise RuntimeError(explanation)


def save(path, obj):
    path.write_text(json.dumps(obj, indent=2) + '\n')


@contextmanager
def release(path):
    # Only the child that owns port 18556 may announce a successful handoff. Never attach to an existing node.
    with subprocess.Popen([sys.executable, '-u', M04 / 'deployment.py', '--out', path, '--hold'],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as child:
        try:
            for line in child.stdout:
                print(line.rstrip(), flush=True)
                if line.startswith('HANDOFF '):
                    break
            else:
                raise RuntimeError('our fresh release failed; no fork RPC sent')
            yield json.loads((path / 'manifest.json').read_text())
        finally:
            child.communicate('\n')  # deployment.py exits its Anvil context, even after a failed check here.


def command(args, env, data=None, expect_interrupt=False):
    proc = subprocess.run(args, input=data, capture_output=True, text=True, env=env)
    output = proc.stdout + proc.stderr
    if expect_interrupt:
        require(proc.returncode != 0 and 'IllegalStateException: LAB_INTERRUPT_BEFORE_COMMIT' in output,
                'did not reach intentional rollback: ' + output)
    else:
        require(proc.returncode == 0, f'{args} failed: {output}')
    return output


def run(out, amount, leave_credit):
    out.mkdir(parents=True, exist_ok=False)
    with release(out / 'release') as m:
        db = 'm05_fork' + token_hex(4)
        env = dict(os.environ, M05_DB=db, M05_MANIFEST=str(out / 'release' / 'manifest.json'))
        sql = ['bash', HERE / 'db.sh', 'sql']
        command(sql, dict(env, M05_DB='m05'), 'CREATE DATABASE ' + db + ';\n')  # No IF EXISTS / overwrite.
        command(sql, env, (HERE / 'schema.sql').read_text())
        print(f'DATABASE {db}   EVIDENCE {out}', flush=True)
        (out / 'database.txt').write_text(db + '\n')
        cli = ['bash', HERE / 'run.sh']
        payer, payee = m['deployer'].lower(), m['constructor']['payee'].lower()
        address, deadline = m['contractAddress'], m['constructor']['deadline']
        read_evidence = (HERE / 'reorg-evidence.sql').read_text()

        def send(name, value=0):
            return send_mined(rpc, {'from': payer, 'to': address, 'data': selector(rpc, name + '()'),
                                    'value': hex(value), 'gas': hex(300_000)})

        def block(height='latest'):
            return rpc('eth_getBlockByNumber', height, False)

        def chain_credit(actor, anchor):
            data = selector(rpc, 'credit(address)') + actor[2:].rjust(64, '0')
            return int(rpc('eth_call', {'to': address, 'data': data}, {'blockHash': anchor, 'requireCanonical': True}), 16)

        def stage(name, anchor, live_kinds, payee_due, payer_due, payer_received, audits):
            state = json.loads(command(sql, env, read_evidence))
            save(out / (name + '.json'), state)
            live = [row['kind'] for row in state['logs'] if row['canonical']]
            money = {row['actor']: (int(row['credit_wei']), int(row['received_wei'])) for row in state['balances']}
            require(state['hash'] == anchor and live == live_kinds and len(state['audit']) == audits,
                    f'{name}: unexpected cursor, live events or audit count')
            require(money == {payee: (payee_due, 0), payer: (payer_due, payer_received)}, f'{name}: incorrect ledger')
            print(f"{name} height={state['height']} live={len(live)} raw={len(state['logs'])} "
                  f"payee={payee_due}/0 payer={payer_due}/{payer_received} audit={audits}", flush=True)
            return state

        locked = send('lock', amount)
        common = locked['blockHash']
        require(int(locked['blockNumber'], 16) == 2 and block()['hash'] == common, 'not an isolated fresh lock')
        snapshot = rpc('evm_snapshot')
        settled = send('settle')
        rpc('evm_mine')  # A4 has no application event. It must still be indexed and later invalidated.
        a4 = block()['hash']
        require(chain_credit(payee, a4) == amount, 'A settlement did not create payee credit')
        print(command(cli + ['Recover'], env).strip())  # empty cursor -> Scan
        a = stage('A', a4, ['Locked', 'Settled'], amount, 0, 0, 0)
        require(a['height'] == 4, 'missing A4')

        require(rpc('evm_revert', snapshot) is True and block()['hash'] == common, 'snapshot did not restore block 2')
        rpc('evm_setNextBlockTimestamp', deadline)  # the refund transaction itself mines B3 at the boundary
        refunded = send('refund')
        require(refunded['blockHash'] != settled['blockHash'] and int(block()['timestamp'], 16) == deadline,
                'expected a different B3 at the deadline')
        receipts = {'lock': locked, 'A-settle': settled, 'B-refund': refunded}
        if not leave_credit:
            receipts['B-withdraw'] = send('withdraw')
        b_tip = block()['hash']
        due, got = (amount, 0) if leave_credit else (0, amount)
        require((chain_credit(payee, b_tip), chain_credit(payer, b_tip)) == (0, due), 'B chain credits disagree')
        save(out / 'receipts.json', receipts)

        failure = command(cli + ['Recover', '--interrupt-before-commit'], env, expect_interrupt=True)
        (out / 'interrupt.log').write_text(failure)
        require(stage('rolled-back', a4, ['Locked', 'Settled'], amount, 0, 0, 0) == a, 'rollback changed A')
        print(command(cli + ['Recover', '--rewind-only'], env).strip())
        rewound = stage('ancestor', common, ['Locked'], 0, 0, 0, 1)
        audit, = rewound['audit']
        require(audit['old_hash'] == a4 and audit['ancestor_hash'] == common and audit['observed_hash'] == b_tip
                and audit['orphan_blocks'] == 2 and {r['hash'] for r in rewound['blocks'] if not r['canonical']}
                == {a4, settled['blockHash']}, 'audit and retained A blocks do not explain the rewind')
        print(command(cli + ['Recover'], env).strip())
        kinds = ['Locked', 'Refunded'] + ([] if leave_credit else ['Withdrawn'])
        b = stage('B', b_tip, kinds, 0, due, got, 1)
        require(len(b['logs']) == len(kinds) + 1, 'expected to retain exactly A-settle alongside the B events')
        print(command(cli + ['Scan', '3'], env).strip())  # actually feed the new suffix a second time
        print(command(cli + ['Recover'], env).strip())
        require(stage('replayed', b_tip, kinds, 0, due, got, 1) == b, 'replay changed the journal or audit')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path, help='new directory; cannot already exist')
    parser.add_argument('--wei', type=int, default=37, help='positive lock amount in wei, at most 10^18')
    parser.add_argument('--leave-credit', action='store_true', help='end B at block 3, before withdrawal')
    args = parser.parse_args()
    if not 1 <= args.wei <= 10**18:
        parser.error('--wei must be in 1..10^18')
    run(args.out.resolve(), args.wei, args.leave_credit)
