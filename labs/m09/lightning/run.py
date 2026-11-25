"""Two LND nodes, one private Core chain. Stdout is a credential-free JSON receipt."""
import argparse
import hashlib
import json
import os
import pwd
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from regtest import btc, check, sat

HOST = '127.0.0.1'
CAPACITY = 500_000
CACHE = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'chain-course/m09/lightning'


class CommandError(RuntimeError):
    pass


def program(group, name):
    cached = CACHE / group / 'bin' / name
    path = str(cached) if cached.is_file() else shutil.which(name)
    check(path, f'缺少 {name}：请先运行 setup.sh')
    return path


def clean_error(text):
    # No command argv in exceptions. In particular, do not archive a BOLT 11 request.
    text = re.sub(r'(?i)lnbcrt[0-9a-z]+|\b[0-9a-fA-F]{48,}\b', '[redacted]', text)
    return ' '.join(text.split())[:420]


def execute(cmd, env, method, timeout=45, payment_failure=False):
    try:
        p = subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise CommandError(f'{method} 超时（{timeout}s）') from None
    if p.returncode and not (payment_failure and p.stdout.strip().startswith('{')):
        raise CommandError(f'{method}: {clean_error(p.stderr)}')
    return p.returncode, p.stdout.strip()


def wait_for(label, probe, timeout=90):
    end = time.monotonic() + timeout
    last = '条件未满足'
    while time.monotonic() < end:
        try:
            value = probe()
            if value:
                return value
        except CommandError as exc:
            last = str(exc)
        time.sleep(0.25)
    raise ValueError(f'等候 {label} 超时：{last}')


def free_ports(n):
    with ExitStack() as stack:
        sockets = [stack.enter_context(socket.socket()) for _ in range(n)]
        for sock in sockets:
            sock.bind((HOST, 0))
        return [sock.getsockname()[1] for sock in sockets]


def daemon(stack, args, env, directory):
    log_path = directory / 'daemon.log'
    log = stack.enter_context(log_path.open('wb'))
    child = subprocess.Popen(args, env=env, cwd=directory, stdin=subprocess.DEVNULL,
                             stdout=log, stderr=subprocess.STDOUT, start_new_session=True)

    def stop():
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
    stack.callback(stop)

    def alive():
        if child.poll() is not None:
            lines = log_path.read_text(errors='replace').splitlines()
            errors = [s for s in lines if re.search(r'error|unable|unknown|failed|invalid', s, re.I)]
            detail = clean_error(errors[-1]) if errors else f'exit {child.returncode}'
            raise ValueError(f'{Path(args[0]).name} 未在运行：{detail}')
    return alive


class Lightning:
    def __init__(self, stack, env, root, name, rpc_port, peer_port, core_port, core_dir):
        self.directory = root / name
        self.directory.mkdir()
        self.env = env
        self.peer = f'{HOST}:{peer_port}'
        rpc = f'{HOST}:{rpc_port}'
        lnd_dir = f'--lnddir={self.directory}'
        config = self.directory / 'lnd.conf'
        config.touch()
        self.alive = daemon(stack, [program('lnd-v0.21.8-beta', 'lnd'), lnd_dir, f'--configfile={config}',
            '--bitcoin.regtest', '--bitcoin.node=bitcoind', f'--bitcoind.rpchost={HOST}:{core_port}',
            f'--bitcoind.rpccookie={core_dir}/regtest/.cookie', '--bitcoind.rpcpolling',
            '--bitcoind.blockpollinginterval=200ms', '--bitcoind.txpollinginterval=200ms',
            '--nobootstrap', '--norest', '--noseedbackup', f'--alias={name}',
            f'--listen={self.peer}', f'--rpclisten={rpc}'], env, self.directory)
        self.cli = [program('lnd-v0.21.8-beta', 'lncli'), lnd_dir, '--network=regtest', f'--rpcserver={rpc}']

    def call(self, method, *args, timeout=45):
        self.alive()
        _, text = execute([*self.cli, method, *args], self.env, method, timeout)
        return json.loads(text) if text else None

    def ready(self):
        info = self.call('getinfo', timeout=5)
        check(info['chains'] == [{'chain': 'bitcoin', 'network': 'regtest'}], 'LND 网络不符')
        check(info['version'].startswith('0.21.8-beta'), 'LND 版本不符')
        return info['identity_pubkey'] if info['synced_to_chain'] else None

    def channel(self):
        rows = self.call('listchannels')['channels']
        return rows[0] if len(rows) == 1 and rows[0]['active'] else None

    def pay(self, request, expect_failure=False):
        self.alive()
        code, text = execute([*self.cli, 'payinvoice', '--force', '--json', '--max_parts=1',
                              '--fee_limit=0', '--timeout=15s', request], self.env, 'payinvoice',
                             payment_failure=True)
        result = json.loads(text)
        check((code != 0) == expect_failure and result['status'] == ('FAILED' if expect_failure else 'SUCCEEDED'),
              f"payinvoice 未得到预期终态：{result['status']} / {result.get('failure_reason')}")
        return result


def open_pair(a, b):
    ac, bc = a.channel(), b.channel()
    if not ac or not bc or ac['pending_htlcs'] or bc['pending_htlcs']:
        return None
    check(ac['channel_point'] == bc['channel_point'], '两个节点指向不同的 funding outpoint')
    return ac, bc


def balances(pair):
    return {name: {k: int(row[k]) for k in ('local_balance', 'remote_balance', 'commit_fee')}
            for name, row in zip(('alice', 'bob'), pair)}


def run(root, stack, amount):
    env = {'HOME': str(root), 'PATH': os.environ['PATH'], 'LC_ALL': 'C'}
    core_dir = root / 'core'
    core_dir.mkdir()
    cp, ar, ap, br, bp = free_ports(5)
    common = ['-regtest', f'-datadir={core_dir}', f'-rpcport={cp}']
    core_alive = daemon(stack, [program('bitcoin-30.5', 'bitcoind'), *common, '-server',
        f'-rpcbind={HOST}', f'-rpcallowip={HOST}', '-listen=0', '-networkactive=0', '-dnsseed=0',
        '-fixedseeds=0', '-listenonion=0', '-fallbackfee=0.0002', '-printtoconsole=0'], env, core_dir)
    cli = [program('bitcoin-30.5', 'bitcoin-cli'), *common, f'-rpcconnect={HOST}']

    def rpc(method, *params, miner=False):
        core_alive()
        wallet = ['-rpcwallet=miner'] if miner else []
        _, text = execute([*cli, *wallet, method, *map(str, params)], env, method)
        if not text or text == 'null':
            return None
        return json.loads(text, parse_float=Decimal) if text[0] in '[{' else text

    chain = wait_for('Core 就绪', lambda: rpc('getblockchaininfo'))
    network = rpc('getnetworkinfo')
    check(chain['chain'] == 'regtest' and chain['blocks'] == 0 and network['version'] == 300500
          and not network['networkactive'] and network['connections'] == 0, '不是要求的空白、隔离 Core 30.5')
    rpc('createwallet', 'miner')
    miner_address = rpc('getnewaddress', miner=True)

    def mine(count):
        return rpc('generatetoaddress', count, miner_address)

    mine(101)  # Mature coinbase; recent tip lets the LND wallets sync.
    a = Lightning(stack, env, root, 'alice', ar, ap, cp, core_dir)
    b = Lightning(stack, env, root, 'bob', br, bp, cp, core_dir)
    a_key = wait_for('Alice 链同步', a.ready)
    b_key = wait_for('Bob 链同步', b.ready)
    check(a_key != b_key, '两端身份相同')
    addr = a.call('newaddress', 'p2wkh')['address']
    rpc('sendtoaddress', addr, btc(2_000_000), miner=True)
    mine(1)
    wait_for('Alice 链上充值', lambda: int(a.call('walletbalance')['confirmed_balance']) == 2_000_000)
    a.call('connect', f'{b_key}@{b.peer}')
    funding_id = a.call('openchannel', f'--node_key={b_key}', f'--local_amt={CAPACITY}',
                        '--private', '--channel_type=anchors', '--sat_per_vbyte=2')['funding_txid']
    wait_for('注资广播', lambda: funding_id in rpc('getrawmempool'))
    funding_blocks = mine(6)
    before = wait_for('双方通道 active', lambda: open_pair(a, b))
    channel = before[0]
    point = channel['channel_point']
    txid, vout = point.split(':')
    check(txid == funding_id and channel['private'] and int(channel['capacity']) == CAPACITY,
          '通道不是本次注资')
    first = rpc('getblock', funding_blocks[0], 1)
    check(txid in first['tx'], '第一个确认块缺少 funding transaction')

    def chain_anchor():
        out = rpc('gettxout', txid, vout)
        check(out is not None and sat(out['value']) == CAPACITY and out['scriptPubKey']['type'] == 'witness_v0_scripthash',
              'funding 输出非预期的 P2WSH UTXO')
        return {'bestblock': out['bestblock'], 'funding_unspent_sat': sat(out['value']),
                'mempool_txids': rpc('getrawmempool')}

    anchor = chain_anchor()
    check(not anchor['mempool_txids'], '对照期间不应存在其他待打包交易')
    initial = balances(before)
    check(initial['bob']['local_balance'] == 0, '实验设定无初始 push')
    invoice = b.call('addinvoice', f'--amt={amount}', '--memo=LN-33')
    decoded = a.call('decodepayreq', invoice['payment_request'])
    pay_hash = invoice['r_hash']
    check(decoded['destination'] == b_key and int(decoded['num_satoshis']) == amount
          and decoded['payment_hash'] == pay_hash, '解码的金额、收款人或哈希不符')
    check(b.call('lookupinvoice', pay_hash)['state'] == 'OPEN', '新发票未处于 OPEN')
    # An active link is not necessarily visible to Alice's router yet. Query, don't repay.
    wait_for('Alice 路由器能找到直连路径',
             lambda: a.call('queryroutes', b_key, str(amount))['routes'])
    payment = a.pay(invoice['payment_request'])
    receipt = b.call('lookupinvoice', pay_hash)
    matches = hashlib.sha256(bytes.fromhex(payment['payment_preimage'])).hexdigest() == pay_hash
    check(matches and payment['payment_hash'] == pay_hash and int(payment['value_sat']) == amount
          and int(payment['fee_sat']) == 0 and receipt['state'] == 'SETTLED'
          and int(receipt['amt_paid_sat']) == amount, '发票与付款不能对账')
    routes = [htlc['route']['hops'] for htlc in payment['htlcs'] if htlc['status'] == 'SUCCEEDED']
    check(len(routes) == 1 and len(routes[0]) == 1 and routes[0][0]['pub_key'] == b_key,
          '不是单次直连的一跳付款')

    def settled():
        pair = open_pair(a, b)
        return pair if pair and int(pair[1]['local_balance']) == amount else None

    after = balances(wait_for('两端更新承诺状态', settled))
    check(after['alice']['remote_balance'] == amount and after['bob']['remote_balance'] == after['alice']['local_balance'],
          '对端余额视图未收敛')
    # Change direction: even before reserve/fees, Bob owns less than this invoice.
    reverse_amount = amount + 10_000
    reverse = a.call('addinvoice', f'--amt={reverse_amount}', '--memo=LN-33-reverse')
    rejected = b.pay(reverse['payment_request'], expect_failure=True)
    unpaid = a.call('lookupinvoice', reverse['r_hash'])
    check(rejected['payment_hash'] == reverse['r_hash'] and unpaid['state'] == 'OPEN'
          and int(unpaid['amt_paid_sat']) == 0 and balances(wait_for('失败后两端无 HTLC', lambda: open_pair(a, b))) == after,
          '反向试付不应产生收款或挪动余额')
    check(chain_anchor() == anchor, '付款与拒付区间链尖、funding UTXO 或 mempool 改变')

    close_id = a.call('closechannel', f'--chan_point={point}', '--sat_per_vbyte=2',
                      '--max_fee_rate=20')['closing_txid']
    wait_for('协作关通道广播', lambda: close_id in rpc('getrawmempool'))
    # After inclusion this release keeps a cooperative close pending for two more blocks.
    close_block = rpc('getblock', mine(3)[0], 2)
    close_tx = next(tx for tx in close_block['tx'] if tx['txid'] == close_id)
    inputs = [f"{i['txid']}:{i['vout']}" for i in close_tx['vin']]
    outputs = [sat(out['value']) for out in close_tx['vout']]
    check(inputs == [point] and rpc('gettxout', txid, vout) is None and sum(outputs) < CAPACITY,
          '链上未见预期的单输入关闭交易')

    def closed():
        rows = [r for n in (a, b) for r in n.call('closedchannels', '--cooperative')['channels']
                if r['channel_point'] == point and r['closing_tx_hash'] == close_id
                and r['close_type'] == 'COOPERATIVE_CLOSE' and int(r['close_height']) == close_block['height']]
        return len(rows) == 2

    wait_for('两端协作关闭摘要', closed)
    return {'network': 'private-regtest', 'core_version': network['version'], 'lnd_version': '0.21.8-beta',
            'funding': {'channel_point': point, 'blockhash': first['hash'], 'height': first['height'],
                        'capacity_sat': CAPACITY, 'type': 'witness_v0_scripthash'},
            'before_sat': initial, 'after_sat': after,
            'payment': {'direction': 'alice->bob', 'payment_hash': pay_hash, 'value_sat': amount,
                        'status': payment['status'], 'fee_sat': int(payment['fee_sat']), 'hops': len(routes[0]),
                        'sha256_preimage_matches': matches, 'receiver_state': receipt['state'],
                        'amt_paid_sat': int(receipt['amt_paid_sat'])},
            'reverse': {'direction': 'bob->alice', 'payment_hash': reverse['r_hash'], 'value_sat': reverse_amount,
                        'status': rejected['status'], 'failure_reason': rejected['failure_reason'],
                        'receiver_state': unpaid['state'], 'amt_paid_sat': int(unpaid['amt_paid_sat']),
                        'balances_unchanged': True},
            'unchanged_chain_during_payments': anchor,
            'close': {'txid': close_id, 'blockhash': close_block['hash'], 'height': close_block['height'],
                      'spends': inputs, 'outputs_sat': outputs, 'miner_fee_sat': CAPACITY - sum(outputs),
                      'funding_unspent_after': False, 'both_nodes_close_type': 'COOPERATIVE_CLOSE'}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pay-sat', type=int, default=50_000, help='整数 sat，20,000 至 200,000')
    args = parser.parse_args()
    if not 20_000 <= args.pay_sat <= 200_000:
        parser.error('--pay-sat 必须在 20000..200000 内')
    # lncli looks for profiles under the OS account's home even with --lnddir.
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    profile_dir = home / ('Library/Application Support/Lncli' if sys.platform == 'darwin' else '.lncli')
    check(not os.path.lexists(profile_dir / 'profiles.json'),
          '检测到现有 lncli profile；请改用独立的系统实验用户，不要移动或复制现有凭证')
    os.umask(0o077)
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, signal.default_int_handler)
    with tempfile.TemporaryDirectory(prefix='ln33-') as d, ExitStack() as stack:
        evidence = run(Path(d), stack, args.pay_sat)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (CommandError, ValueError, FileNotFoundError) as e:
        sys.exit(str(e))
