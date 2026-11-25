"""Create a fresh one-validator Sui network and exercise the public handoff entry point."""
import argparse
import json
import os
import re
import resource
import shutil
import socket
import subprocess as sp
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import ExitStack
from pathlib import Path

from review import require, review

HERE = Path(__file__).resolve().parent
CACHE = Path.home() / '.cache/chain-course/m09/sui-1.53.2'
SUI, NODE = (CACHE / 'bin' / name for name in ('sui', 'sui-node'))
GAS_BUDGET = '100000000'  # MIST; a cap, not what was spent


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def stop(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except sp.TimeoutExpired:
            proc.kill()
            proc.wait()


def run(args, tmp, stack):
    network = tmp / 'network'
    network.mkdir()
    # v1.53.2's standalone node uses reqwest for IP lookup and analytics. Give its
    # non-local HTTP(S) requests a reserved, non-listening loopback proxy instead.
    blocked = stack.enter_context(socket.socket())
    blocked.bind(('127.0.0.1', 0))
    proxy = 'http://127.0.0.1:%d' % blocked.getsockname()[1]
    env = {'PATH': os.environ['PATH'], 'HOME': str(tmp), 'TMPDIR': str(tmp), 'SUI_CONFIG_DIR': str(network),
           'MOVE_HOME': str(tmp / '.move'), 'RUST_LOG': 'error', 'NO_COLOR': '1',
           'http_proxy': proxy, 'https_proxy': proxy, 'no_proxy': '127.0.0.1,localhost,::1'}
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    endpoint = f'http://127.0.0.1:{port}'
    http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def rpc(method, *params):
        data = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}).encode()
        req = urllib.request.Request(endpoint, data, {'Content-Type': 'application/json'})
        with http.open(req, timeout=6) as response:
            body = json.load(response)
        if 'error' in body:
            raise RuntimeError(f'{method}: {body["error"]}')
        return body['result']

    def cli(cmd, silent=False, check=True):
        result = sp.run([str(SUI), *map(str, cmd)], env=env, cwd=tmp, stdin=sp.DEVNULL,
                        stdout=sp.DEVNULL if silent else sp.PIPE, stderr=sp.PIPE, text=True, timeout=120)
        if check and result.returncode:
            raise RuntimeError((result.stderr or result.stdout or 'CLI failed').strip())
        return result

    version = cli(['--version']).stdout.strip()
    require('1.53.2' in version, 'use setup.sh to obtain the pinned Sui CLI')
    cli(['genesis', '--working-dir', network, '--committee-size', '1', '--epoch-duration-ms', '3600000'])
    validator, = [p for p in network.glob('*.yaml') if p.name not in ('client.yaml', 'network.yaml', 'fullnode.yaml')]
    nodes = []
    for name, config in [('validator', validator), ('fullnode', network / 'fullnode.yaml')]:
        # Change only generated socket bindings; don't rewrite any key or genesis data.
        text = config.read_text().replace('0.0.0.0:', '127.0.0.1:').replace('/ip4/0.0.0.0/', '/ip4/127.0.0.1/')
        if name == 'fullnode':
            text, count = re.subn(r'(?m)^json-rpc-address: [^\n]+$', f'json-rpc-address: 127.0.0.1:{port}', text)
            require(count == 1, 'unexpected fullnode config format')
        config.write_text(text)
        log = stack.enter_context((tmp / f'{name}.log').open('w'))
        process = sp.Popen([NODE, '--config-path', config], cwd=tmp, env=env,
                           stdin=sp.DEVNULL, stdout=log, stderr=sp.STDOUT)
        stack.callback(stop, process)
        nodes.append((name, process))
    deadline = time.monotonic() + 75
    while True:
        for name, process in nodes:
            if process.poll() is not None:
                raise RuntimeError(f'{name} stopped: ' + (tmp / f'{name}.log').read_text()[-2000:])
        try:
            chain = rpc('sui_getChainIdentifier')
            break
        except (urllib.error.URLError, TimeoutError, RuntimeError):
            if time.monotonic() > deadline:
                raise RuntimeError('local fullnode not ready')
            time.sleep(0.2)

    clients = {}
    for role, keys in [('A', network / 'sui.keystore'), ('B', tmp / 'receiver.keystore')]:
        path = tmp / f'{role}.yaml'
        # JSON is valid YAML. Each client knows only the endpoint in this run.
        save(path, {'keystore': {'File': str(keys)}, 'envs': [{'alias': 'lesson', 'rpc': endpoint}],
                    'active_env': 'lesson', 'active_address': None})
        clients[role] = ['client', '--client.config', path]
    cli([*clients['B'], 'new-address', 'ed25519'], silent=True)  # discard the recovery phrase
    addresses = {r: json.loads(cli([*c, 'addresses', '--json']).stdout)['activeAddress'] for r, c in clients.items()}
    first, second = ('B', 'A') if args.reverse else ('A', 'B')

    def tx(role, name, command):
        raw = cli([*clients[role], *command, '--gas-budget', GAS_BUDGET, '--json']).stdout
        # The compiler can print progress on publication. The last top-level object is the CLI response.
        digest = json.loads(raw[raw.rfind('\n{') + 1:])['digest']
        result = rpc('sui_getTransactionBlock', digest, {'showInput': True, 'showEffects': True, 'showObjectChanges': True})
        save(args.out / f'{name}.json', result)
        require(result['effects']['status']['status'] == 'success', name + ': not successful')
        return result

    # B needs its own gas, even for the positive control (return). All coins originate in this genesis.
    coins = rpc('suix_getCoins', addresses['A'], '0x2::sui::SUI', None, 1)['data']
    tx('A', 'fund-B', ['transfer-sui', '--sui-coin-object-id', coins[0]['coinObjectId'],
                       '--to', addresses['B'], '--amount', '1000000000'])
    package = tmp / 'ticket'
    shutil.copytree(HERE / 'ticket', package)
    (tmp / 'framework').symlink_to(CACHE / 'framework', target_is_directory=True)
    pub = tx(first, 'publish', ['publish', package, '--verify-deps'])
    pkg, = [c['packageId'] for c in pub['objectChanges'] if c['type'] == 'published']
    call = ['call', '--package', pkg, '--module', 'ticket', '--function']
    created = tx(first, 'open', [*call, 'open', '--args', str(args.number)])
    oid, = [c['objectId'] for c in created['objectChanges'] if c['type'] == 'created' and
            c.get('objectType') == pkg + '::ticket::Ticket']

    def snapshot(name):
        doc = rpc('sui_getObject', oid, {'showType': True, 'showOwner': True, 'showContent': True,
                                         'showPreviousTransaction': True})
        save(args.out / (name + '.json'), doc)
        return doc['data']

    snapshot('created')
    tx(first, 'handoff', [*call, 'handoff', '--args', oid, addresses[second]])
    snapshot('handed')
    back = [*call, 'handoff', '--args', oid, addresses[first]]
    denied = cli([*clients[first], *back, '--gas-budget', GAS_BUDGET, '--json'], check=False)
    detail = '\n'.join(s.strip() for s in (denied.stderr, denied.stdout) if s.strip())
    save(args.out / 'refusal.json', {'sender': addresses[first], 'recipient': addresses[first],
         'exitCode': denied.returncode, 'detail': detail})
    require(denied.returncode != 0, 'former holder unexpectedly succeeded')
    snapshot('after-refusal')
    tx(second, 'return', back)  # same entry, object and recipient; select the current holder's wallet
    snapshot('returned')
    save(args.out / 'run.json', {'cli': version, 'chainIdentifier': chain, 'addresses': addresses,
         'reverse': args.reverse, 'number': str(args.number), 'package': pkg, 'object': oid})
    review(args.out, args.number, first)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True, help='new directory for public evidence only')
    p.add_argument('--number', type=int, default=3601)
    p.add_argument('--reverse', action='store_true', help='B opens; hand B → A, then A → B')
    args = p.parse_args()
    if not 0 <= args.number < 2**64:
        p.error('number must fit u64')
    if not all(pth.is_file() for pth in (SUI, NODE, CACHE / 'framework/sui-framework/Move.toml')):
        p.error('run bash labs/m09/move-ticket/setup.sh first')
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=False)
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft < 8192:
        resource.setrlimit(resource.RLIMIT_NOFILE, (8192 if hard == resource.RLIM_INFINITY else min(8192, hard), hard))
    with tempfile.TemporaryDirectory(prefix='m09-ticket-') as home, ExitStack() as stack:
        run(args, Path(home), stack)
