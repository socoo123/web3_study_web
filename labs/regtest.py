"""Run one course experiment on a fresh, loopback-only Bitcoin Core regtest."""
import json
import signal
import socket
import subprocess
import tempfile
from decimal import Decimal

SAT = 100_000_000


def check(ok, message):
    if not ok:
        raise ValueError(message)


def sat(amount):
    value = Decimal(amount) * SAT
    check(value == int(value), 'RPC 金额不是整数聪')
    return int(value)


def btc(amount_sat):
    return format(Decimal(amount_sat) / SAT, '.8f')


def run(lab):
    with tempfile.TemporaryDirectory(prefix='bitcoin-lab-') as directory:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        common = ['-regtest', '-datadir=' + directory, f'-rpcport={port}']
        cli = ['bitcoin-cli', *common, '-rpcconnect=127.0.0.1']

        def rpc(method, *args, wallet=None, wait=False):
            options = ['-rpcwait', '-rpcwaittimeout=30'] if wait else []
            if wallet is not None:
                options.append('-rpcwallet=' + wallet)
            params = [a if isinstance(a, str) else json.dumps(a) for a in args]
            p = subprocess.run([*cli, *options, method, *params], capture_output=True, text=True)
            if p.returncode:
                raise ValueError(f'{method}: {p.stderr.strip()}')
            data = p.stdout.strip()
            if not data or data == 'null':
                return None
            if data[0] in '[{':
                return json.loads(data, parse_float=Decimal)
            return data  # bitcoin-cli prints scalar strings without JSON quotes.

        node = subprocess.Popen(['bitcoind', *common, '-server', '-rpcbind=127.0.0.1', '-rpcallowip=127.0.0.1',
                                 '-listen=0', '-networkactive=0', '-dnsseed=0', '-fixedseeds=0', '-listenonion=0',
                                 '-printtoconsole=0'], start_new_session=True)
        handlers = {sig: signal.signal(sig, signal.default_int_handler) for sig in (signal.SIGHUP, signal.SIGTERM)}
        try:
            chain = rpc('getblockchaininfo', wait=True)
            network = rpc('getnetworkinfo')
            print(f"NODE chain={chain['chain']} height={chain['blocks']} networkactive={network['networkactive']} peers={network['connections']} version={network['version']}")
            check(chain['chain'] == 'regtest' and chain['blocks'] == 0 and not network['networkactive'] and network['connections'] == 0,
                  '不是全新、断开 P2P 的 regtest，拒绝创建钱包')
            return lab(rpc)
        finally:
            if node.poll() is None:
                node.terminate()
            node.wait()
            for sig, handler in handlers.items():
                signal.signal(sig, handler)
