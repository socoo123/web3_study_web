"""Compile M04 sources and create one fresh real Anvil deployment inside Compose."""
from hashlib import sha256
from pathlib import Path
import json
import subprocess
import sys

LABS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(LABS / 'm04'))
from deployment import clean_build, describe, transact
from handoff import constructor_words, hex_bytes, rpc, selector, verify


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def seed(out, wei, refund):
    require(rpc('web3_clientVersion') == 'anvil/v1.7.1' and rpc('eth_chainId') == '0x7a69'
            and rpc('eth_blockNumber') == '0x0', 'need our fresh Anvil 1.7.1 / 31337')
    payer, payee = rpc('eth_accounts')
    t0 = int(rpc('eth_getBlockByNumber', '0x0', False)['timestamp'], 16)
    deadline = t0 + 3600
    version = subprocess.check_output(['forge', '--version'], text=True).splitlines()[0]
    require(version.split()[:3] == ['forge', 'Version:', '1.7.1-stable'] or
            version.split()[:3] == ['forge', 'Version:', '1.7.1'], 'need Forge 1.7.1')
    build, creation, abi = describe(clean_build(LABS / 'm04'), LABS / 'm04', version)
    words = constructor_words(abi, payee, deadline)
    deployed = transact(rpc, **{'from': payer, 'data': '0x' + (creation + words).hex()})
    address = deployed['contractAddress']
    runtime = hex_bytes(rpc('eth_getCode', address, {'blockHash': deployed['blockHash'], 'requireCanonical': True}))
    manifest = {'format': 'm04-escrow-release/1', 'chainId': 31337, 'genesisTimestamp': t0,
                'deployer': payer, 'contractAddress': address, 'abi': abi, 'build': build,
                'constructor': {'payee': payee, 'deadline': deadline}, 'runtimeSha256': sha256(runtime).hexdigest(),
                'deploymentTransactionHash': deployed['transactionHash'], 'deploymentBlockNumber': 1,
                'deploymentBlockHash': deployed['blockHash']}
    save(out / 'manifest.json', manifest)
    save(out / 'handoff.json', verify(manifest))
    call = {'from': payer, 'to': address}
    locked = transact(rpc, **call, value=hex(wei), data=selector(rpc, 'lock()'))
    if refund:
        rpc('evm_setNextBlockTimestamp', deadline)
    posted = transact(rpc, **call, data=selector(rpc, 'refund()' if refund else 'settle()'))
    receipts = {'deploy': deployed, 'lock': locked, 'post': posted}
    require([int(r['blockNumber'], 16) for r in receipts.values()] == [1, 2, 3], 'unexpected block layout')
    save(out / 'receipts.json', receipts)
    return manifest, receipts


def withdraw(manifest, actor):
    return transact(rpc, **{'from': actor, 'to': manifest['contractAddress'], 'data': selector(rpc, 'withdraw()')})
