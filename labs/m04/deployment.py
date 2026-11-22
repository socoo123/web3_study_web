"""Release the course escrow onto a new Anvil, rebuild it, and run the independent reader."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from handoff import PORT, abi_digest, constructor_words, hex_bytes, selector

ROOT = Path(__file__).resolve().parent
SOURCE = Path('src/MilestoneEscrow.sol')
sys.path.insert(0, str(ROOT.parent))
from anvil_lab import anvil, send_mined


def store(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n')


def copy_inputs(source, target):
    (target / 'src').mkdir()
    for path in (SOURCE, Path('foundry.toml')):
        shutil.copyfile(source / path, target / path)


def clean_build(inputs):
    # Same source unit name on both builds; no cached artifact and no network download.
    with tempfile.TemporaryDirectory(prefix='m04-build-') as tmp:
        work = Path(tmp)
        copy_inputs(inputs, work)
        subprocess.run(['forge', 'build', '--root', '.', '--offline', '--extra-output', 'metadata'],
                       cwd=work, check=True)
        return (work / 'out' / SOURCE.name / 'MilestoneEscrow.json').read_bytes()


def describe(artifact, archive, forge_version):
    a = json.loads(artifact)
    metadata = a['metadata']
    settings = metadata['settings']
    if (metadata['compiler']['version'] != '0.8.28+commit.7893614a'
            or set(metadata['sources']) != {str(SOURCE)} or settings.get('libraries')
            or settings['optimizer']['enabled'] is not True or settings['optimizer']['runs'] != 200
            or settings['evmVersion'] != 'cancun'):
        raise ValueError('Unexpected compiler, source units or settings. Check the M04 tool setup.')
    creation = hex_bytes(a['bytecode']['object'])
    build = {'forgeVersion': forge_version, 'compiler': metadata['compiler']['version'],
             'settings': settings, 'sourcePath': str(SOURCE),
             'sourceSha256': sha256((archive / SOURCE).read_bytes()).hexdigest(),
             'configSha256': sha256((archive / 'foundry.toml').read_bytes()).hexdigest(),
             'artifactSha256': sha256(artifact).hexdigest(), 'abiSha256': abi_digest(a['abi']),
             'creationCodeSha256': sha256(creation).hexdigest()}
    return build, creation, a['abi']


def transact(rpc, **params):
    return send_mined(rpc, {**params, 'gas': hex(3_000_000)})


def receiver(archive):
    # Only this trusted read-only program and an explicit manifest path; no project workdir/imports.
    with tempfile.TemporaryDirectory(prefix='m04-reader-') as tmp:
        return subprocess.run([sys.executable, '-I', str(ROOT / 'handoff.py'), str(archive / 'manifest.json')],
                              cwd=tmp, capture_output=True, text=True, timeout=45)


def run(args):
    version = subprocess.check_output(['forge', '--version'], text=True).splitlines()[0]
    if not re.match(r'^forge Version: 1\.7\.1(?:\b|$)', version):
        raise ValueError(f'expected forge 1.7.1, got {version}')
    if args.out is None:
        archive = Path(tempfile.mkdtemp(prefix='m04-release-')).resolve()
    else:
        archive = args.out.resolve()
        archive.mkdir(parents=True, exist_ok=False)  # An earlier release is never overwritten.
    print(f'ARCHIVE {archive}', flush=True)
    copy_inputs(ROOT, archive)
    artifact = clean_build(archive)
    (archive / 'artifact.json').write_bytes(artifact)
    build, creation, abi = describe(artifact, archive, version)

    with anvil(PORT) as rpc:
        payer, payee = rpc('eth_accounts')
        genesis = rpc('eth_getBlockByNumber', '0x0', False)
        t0 = int(genesis['timestamp'], 16)
        deadline = t0 + args.ttl
        words = constructor_words(abi, payee, deadline)
        deployed = transact(rpc, **{'from': payer, 'data': '0x' + (creation + words).hex()})
        address = deployed['contractAddress']
        height = int(deployed['blockNumber'], 16)
        if height != 1 or not address:
            raise ValueError('expected a direct contract creation in the first non-genesis block')
        at = {'blockHash': deployed['blockHash'], 'requireCanonical': True}
        runtime = hex_bytes(rpc('eth_getCode', address, at))
        if not runtime:
            raise ValueError('no code at the address in the creation receipt')
        receipts = {'deploy': deployed}
        if args.settle_wei:
            call = {'from': payer, 'to': address}
            receipts['lock'] = transact(rpc, **call, value=hex(args.settle_wei), data=selector(rpc, 'lock()'))
            receipts['settle'] = transact(rpc, **call, data=selector(rpc, 'settle()'))
        store(archive / 'receipts.json', receipts)

        # Independent fresh compilation compared with the actual transaction, not just a local hash.
        rebuilt, init2, abi2 = describe(clean_build(archive), archive, version)
        tx = rpc('eth_getTransactionByHash', deployed['transactionHash'])
        if (abi2 != abi or rebuilt['settings'] != build['settings']
                or init2 + words != hex_bytes(tx['input'])):
            raise ValueError('fresh build + constructor words do not match published deployment')
        (archive / 'deployment-input.hex').write_text(tx['input'] + '\n')
        print(f"REBUILD creationArgsMatch=true constructorBytes={len(words)} compiler={build['compiler']} "
              f"creationCodeSha256={build['creationCodeSha256']}")
        manifest = {'format': 'm04-escrow-release/1', 'chainId': int(rpc('eth_chainId'), 16),
                    'genesisTimestamp': t0, 'deployer': payer, 'contractAddress': address,
                    'constructor': {'payee': payee, 'deadline': deadline}, 'abi': abi,
                    'deploymentTransactionHash': deployed['transactionHash'], 'deploymentBlockNumber': height,
                    'deploymentBlockHash': deployed['blockHash'], 'runtimeSha256': sha256(runtime).hexdigest(),
                    'build': build}
        store(archive / 'manifest.json', manifest)
        checked = receiver(archive)
        if checked.returncode != 0:
            raise ValueError(f'reader refused actual release: {checked.stderr.strip()}')
        report = json.loads(checked.stdout)
        store(archive / 'handoff.json', report)
        expected = str(args.settle_wei)
        if (report['state'] != (2 if args.settle_wei else 0) or report['payeeCreditWei'] != expected
                or report['escrowBalanceWei'] != expected):
            raise ValueError('verified read does not match the isolated order')
        print(f"HANDOFF chainId={report['chainId']} deployBlock={height} readBlock={report['readBlockNumber']} "
              f"state={report['state']} payeeCreditWei={report['payeeCreditWei']} "
              f"escrowBalanceWei={report['escrowBalanceWei']}", flush=True)
        if args.hold:
            input('Live local node: run handoff.py in another terminal. Press Enter to stop. ')

    if args.reset:
        with anvil(PORT):  # Same chain ID and endpoint, now a different empty ledger.
            stale = receiver(archive)
            reason = f'STOP chainId=31337 missing deployment block {height}'
            if stale.returncode != 3 or stale.stderr.strip() != reason or stale.stdout:
                raise ValueError(f'reset check did not produce the expected refusal: {stale.stderr}')
            (archive / 'refusal.txt').write_text(stale.stderr)
            print(reason)
            return 3
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, help='new archive directory (default: a new temporary path, retained)')
    parser.add_argument('--ttl', type=int, default=3600, help='deadline offset from genesis, in seconds')
    parser.add_argument('--settle-wei', type=int, default=0, help='nonzero: lock and settle this order before handoff')
    parser.add_argument('--reset', action='store_true', help='try the unchanged manifest on a fresh empty Anvil')
    parser.add_argument('--hold', action='store_true', help='wait for Enter before shutting down the live node')
    options = parser.parse_args()
    if not (60 <= options.ttl <= 7 * 86400 and 0 <= options.settle_wei <= 10**18):
        parser.error('require 60..604800 seconds and 0..1000000000000000000 wei')
    try:
        sys.exit(run(options))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        sys.exit(f'ERROR {error}')
