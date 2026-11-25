"""One private Compose project, two independent materializations of one M04 escrow."""
import argparse
from contextlib import contextmanager
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from string import Template
from time import monotonic, sleep
from uuid import uuid4

from compare import graph, post, sample
from fixture import LABS, require, rpc, save, seed, withdraw

HERE = Path(__file__).resolve().parent
CACHE = Path(os.getenv('XDG_CACHE_HOME', Path.home() / '.cache')) / 'chain-course/m09/subgraph'
DB = 'm05_index34'
META = '{ _meta { deployment hasIndexingErrors block { number hash } } }'


def command(args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def wait_for(desc, fn, timeout=180):
    end = monotonic() + timeout
    last = 'not yet served'
    while monotonic() < end:
        try:
            value = fn()
            if value:
                return value
        except (OSError, HTTPException, ValueError) as exc:
            last = str(exc)
        sleep(0.25)
    raise TimeoutError(f'{desc}: {last}')


@contextmanager
def stack(out):
    name = 'm09g' + uuid4().hex[:12]
    binary = CACHE / 'anvil-1.7.1'
    require(binary.is_file(), 'prepare Linux Anvil with setup.sh')
    os.environ['M09_ANVIL'] = str(binary)
    compose = ['docker', 'compose', '-p', name, '-f', str(HERE / 'compose.yml')]
    print(f'PROJECT {name}   OUTPUT {out}', flush=True)
    try:
        command([*compose, 'up', '--pull', 'never', '-d'])
        wait_for('Anvil', lambda: rpc('web3_clientVersion'))
        # An unknown JSON-RPC method returning an application error proves admin HTTP is up.
        wait_for('Graph admin', lambda: post(19341, '/', {'jsonrpc': '2.0', 'id': 1, 'method': 'course_ready', 'params': []}))
        yield compose
    finally:
        with (out / 'node.log').open('w') as log:
            subprocess.run([*compose, 'logs', '--no-color', 'graph'], stdout=log, stderr=subprocess.STDOUT)
        command([*compose, 'down', '--volumes', '--timeout', '5'])


def admin(method, params):
    msg = post(19341, '/', {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
    require('result' in msg and 'error' not in msg, f'{method}: {msg}')
    return msg['result']


def compile_mapping(out, release, late):
    p = out / 'project'
    p.mkdir()
    for f in ['mapping.ts', 'schema.graphql', 'package.json']:
        shutil.copyfile(HERE / f, p / f)
    start = 3 if late else release['deploymentBlockNumber']
    manifest = Template((HERE / 'subgraph.template.yaml').read_text()).substitute(
        address=release['contractAddress'], startBlock=start)
    (p / 'subgraph.yaml').write_text(manifest)
    save(p / 'Escrow.json', release['abi'])
    (p / 'node_modules').symlink_to(CACHE / 'node_modules', target_is_directory=True)
    cli = str(CACHE / 'node_modules/.bin/graph')
    env = {**os.environ, 'NO_COLOR': '1', 'FORCE_COLOR': '0'}
    try:
        command([cli, 'codegen', '--skip-migrations'], cwd=p, env=env)
        with (out / 'build.log').open('w') as log:
            command([cli, 'build', '--skip-migrations', '--ipfs', 'http://127.0.0.1:19342'],
                    cwd=p, env=env, stdout=log, stderr=subprocess.STDOUT)
    finally:
        (p / 'node_modules').unlink()
    cid = re.search(r'Build completed:\s*(Qm[1-9A-HJ-NP-Za-km-z]{44}|b[a-z2-7]+)', (out / 'build.log').read_text())
    require(cid, 'missing compiled deployment CID in build.log')
    return cid.group(1)


def caught_up(cid, height):
    def check():
        meta = graph(META)['_meta']
        if meta and meta['hasIndexingErrors']:
            raise RuntimeError('Graph Node reports an indexing error; see node.log')
        return meta if meta and meta['deployment'] == cid and meta['block']['number'] == height else None
    return wait_for(f'Graph cursor {height}', check)


def run(args):
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    with stack(out) as compose:
        pg = [*compose, 'exec', '-T', 'postgres']
        command([*pg, 'createdb', '-U', 'course', DB])
        def sql(statement):
            return command([*pg, 'psql', '-XAtq', '-v', 'ON_ERROR_STOP=1', '-U', 'course', '-d', DB],
                           input=statement, stdout=subprocess.PIPE).stdout.strip()
        sql((LABS / 'm05/schema.sql').read_text())
        release, receipts = seed(out, args.wei, args.refund)
        cid = compile_mapping(out, release, args.late_start)
        admin('subgraph_create', {'name': 'course/escrow'})
        # Excludes compilation, IPFS upload, infrastructure/DB startup on both sides.
        start = monotonic()
        admin('subgraph_deploy', {'name': 'course/escrow', 'ipfs_hash': cid, 'version_label': 'v1'})
        caught_up(cid, 3)
        graph_ms = round((monotonic() - start) * 1000)
        env = {**os.environ, 'M05_MANIFEST': str(out / 'manifest.json'), 'M05_DB': DB}
        def scan(log):
            with (out / log).open('w') as f:
                command(['bash', str(LABS / 'm05/run.sh'), 'Scan'], env=env, stdout=f)
        start = monotonic()
        scan('java-rebuild.txt')
        java_ms = round((monotonic() - start) * 1000)
        at3 = sample(sql, release, receipts, cid, 3)
        report = {'chainId': 31337, 'source': release['contractAddress'], 'deploymentBlockHash': release['deploymentBlockHash'],
                  'subgraphCID': cid, 'startBlock': 3 if args.late_start else 1, 'rebuildTo3Ms': {'graph': graph_ms, 'java': java_ms},
                  'pages': [at3]}
        save(out / 'report.json', report)
        print(f"REBUILD to=3 graphMs={graph_ms} javaMs={java_ms} cid={cid}")
        if not at3['match']:
            print(f"HOLD_VIEW_MISMATCH height=3 graph={len(at3['graph']['postings'])} java={len(at3['java']['postings'])} receipts={len(at3['receiptRows'])}")
            return 3
        actor = release['deployer'] if args.refund else release['constructor']['payee']
        receipts['withdraw'] = withdraw(release, actor)
        observed = monotonic()  # elapsed from receipt observation, not from signing or a block timestamp
        save(out / 'receipts.json', receipts)
        require(int(receipts['withdraw']['blockNumber'], 16) == 4, 'withdrawal must be in block 4')
        first_meta = graph(META)['_meta']
        require(first_meta['deployment'] == cid and not first_meta['hasIndexingErrors'], 'wrong live Graph response')
        java_before = int(sql('SELECT height FROM scan_cursor;'))
        require(java_before == 3, 'stopped Java scan unexpectedly advanced')
        caught_up(cid, 4)
        graph_visible = round((monotonic() - observed) * 1000)
        scan('java-catchup.txt')
        java_visible = round((monotonic() - observed) * 1000)
        report['afterReceipt4'] = {'sourceHead': 4, 'firstGraphMeta': first_meta, 'firstJavaCursor': java_before,
                                   'graphLagBlocks': 4 - first_meta['block']['number'], 'javaLagBlocks': 4 - java_before,
                                   'graphObservedCaughtUpMs': graph_visible, 'javaObservedCaughtUpMs': java_visible}
        for height in (3, 4):
            report['pages'].append(sample(sql, release, receipts, cid, height))
        require(all(p['match'] for p in report['pages']) and report['pages'][0]['receiptRows'] == report['pages'][1]['receiptRows'],
                'historical facts shifted or views disagree after withdrawal')
        final = report['pages'][-1]['receiptRows']
        require([r['kind'] for r in final] == ['Locked', 'Refunded' if args.refund else 'Settled', 'Withdrawn'] and
                all(r['amountWei'] == str(args.wei) for r in final) and final[1]['actor'] == final[2]['actor'] == actor,
                'unexpected escrow trace')
        save(out / 'report.json', report)
        print(f"AT3 rows=2 creditWei={args.wei} withdrawnWei=0; AT4 rows=3 creditWei=0 withdrawnWei={args.wei}")
        print(f"LAG head=4 graph={4-first_meta['block']['number']} java={4-java_before} blocks; MATCH_SOURCE")
        return 0


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True, help='new evidence directory')
    p.add_argument('--wei', type=int, default=125)
    p.add_argument('--refund', action='store_true', help='follow the payer refund branch at the deadline')
    p.add_argument('--late-start', action='store_true', help='start the subgraph at block 3, omitting Locked@2')
    a = p.parse_args()
    if not 0 < a.wei <= 10**18:
        p.error('need 1..1000000000000000000 wei')
    sys.exit(run(a))
