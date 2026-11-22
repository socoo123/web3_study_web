"""Audit M04 escrow deployment costs locally; public commands never sign or send."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
M04 = HERE.parents[1] / 'm04'
sys.path.insert(0, str(M04))
from deployment import clean_build, describe, store
from handoff import constructor_words, hex_bytes
from anvil_lab import anvil, send_mined


class Hold(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise Hold(reason)


def load(path):
    return json.loads(path.read_text())


def number(record, key):
    raw = record.get(key)
    need(isinstance(raw, str) and re.fullmatch(r'0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)', raw),
         f'missing_or_invalid={key}')
    return int(raw, 16)


def charge(receipt, profile, timestamp):
    need(number(receipt, 'type') == 2 and number(receipt, 'status') in (0, 1), 'unsupported receipt')
    gas = number(receipt, 'gasUsed')
    price = number(receipt, 'effectiveGasPrice')
    execution = gas * price
    print(f'EXEC gasUsed={gas} effectiveWeiPerGas={price} executionWei={execution}')
    if profile['network'] == 'anvil-cancun':
        print('RULE plain-Anvil-Cancun l1Data=not-applicable operator=not-applicable')
        return execution
    data = number(receipt, 'l1Fee')
    print(f'DATA l1FeeWei={data}')
    schedule = profile['historicalSchedule']
    need(schedule['holocene'] <= timestamp < schedule['isthmus'], 'fee_rules_not_covered_for_block')
    print('RULE Base-Sepolia-Holocene operator=not-applicable reason=before-Isthmus')
    return execution + data


def historical(path, profile):
    doc = load(path)
    block, tx, receipt = (doc[k] for k in ('block', 'transaction', 'receipt'))
    need(number(doc, 'chainId') == number(tx, 'chainId') == profile['chainId'], 'wrong_chain')
    need(tx['hash'] == receipt['transactionHash'] and tx['blockHash'] == block['hash'] == receipt['blockHash']
         and block['number'] == receipt['blockNumber'] and tx['transactionIndex'] == receipt['transactionIndex']
         and tx['type'] == receipt['type'], 'receipt_anchor_mismatch')
    print(f"ARCHIVE chainId={profile['chainId']} height={number(block, 'number')} block={block['hash']} "
          f"tx={tx['hash']} timestamp={number(block, 'timestamp')}")
    total = charge(receipt, profile, number(block, 'timestamp'))
    print(f'RESULT totalFeeWei={total} basis=archived-receipt-and-fork')


def build_contract():
    version = subprocess.check_output(['forge', '--version'], text=True).splitlines()[0]
    need(re.match(r'^forge Version: 1\.7\.1(?:\b|$)', version), 'expected Foundry 1.7.1')
    return describe(clean_build(M04), M04, version)


def block_ref(block_hash):
    return {'blockHash': block_hash, 'requireCanonical': True}


def check_release(rpc, m, artifact):
    build, creation, abi = artifact
    need(build['sourceSha256'] == m['sourceSha256'] and build['creationCodeSha256'] == m['creationCodeSha256'],
         'source_or_build_mismatch')
    h, txh = m['deploymentBlockHash'], m['deploymentTransactionHash']
    block = rpc('eth_getBlockByNumber', hex(m['deploymentBlockNumber']), False)
    receipt = rpc('eth_getTransactionReceipt', txh)
    tx = rpc('eth_getTransactionByHash', txh)
    need(block and block['hash'] == h and txh in block['transactions'] and receipt and tx, 'missing_or_stale_anchor')
    need(receipt['transactionHash'] == tx['hash'] == txh and tx['blockHash'] == receipt['blockHash'] == h
         and number(tx, 'chainId') == m['chainId'] and number(receipt, 'status') == 1
         and number(receipt, 'blockNumber') == m['deploymentBlockNumber'] and tx['to'] is None
         and number(tx, 'value') == 0 and tx['from'].lower() == m['deployer'].lower()
         and receipt['contractAddress'] and receipt['contractAddress'].lower() == m['contractAddress'].lower(),
         'not_the_expected_successful_direct_creation')
    tail = constructor_words(abi, m['payee'], m['deadline'])
    need(hex_bytes(tx['input']) == creation + tail, 'creation_input_or_constructor_mismatch')
    code = hex_bytes(rpc('eth_getCode', m['contractAddress'], block_ref(h)))
    need(code and sha256(code).hexdigest() == m['runtimeSha256'], 'runtime_mismatch')
    print(f"DEPLOY chainId={m['chainId']} height={m['deploymentBlockNumber']} address={m['contractAddress']} "
          f'block={h} tx={txh} rebuiltInputMatch=true runtimeMatch=true')
    return block, receipt


def local(args):
    profile = load(HERE / f'{args.expect}.json')
    with anvil(18626) as rpc:
        chain = int(rpc('eth_chainId'), 16)
        need(chain == profile['chainId'], f"wrong_chain expected={profile['chainId']} actual={chain} before_send=true")
        args.out.mkdir(parents=True, exist_ok=False)
        artifact = build_contract()
        build, creation, abi = artifact
        genesis = rpc('eth_getBlockByNumber', '0x0', False)
        payer, payee = rpc('eth_accounts')
        deadline = number(genesis, 'timestamp') + 3600
        tx = {'from': payer, 'value': '0x0', 'data': '0x' + (creation + constructor_words(abi, payee, deadline)).hex(),
              'maxFeePerGas': hex(2_000_000_000), 'maxPriorityFeePerGas': hex(1_000_000_000)}
        estimate = int(rpc('eth_estimateGas', tx), 16)
        print(f'BUDGET estimateGas={estimate} gasLimit={args.gas_limit} maxWeiPerGas=2000000000')
        r = send_mined(rpc, {**tx, 'gas': hex(args.gas_limit)})
        runtime = hex_bytes(rpc('eth_getCode', r['contractAddress'], block_ref(r['blockHash'])))
        m = {'chainId': chain, 'genesisHash': genesis['hash'], 'sourceSha256': build['sourceSha256'],
             'creationCodeSha256': build['creationCodeSha256'], 'deployer': payer, 'payee': payee, 'deadline': deadline,
             'deploymentTransactionHash': r['transactionHash'], 'deploymentBlockHash': r['blockHash'],
             'deploymentBlockNumber': number(r, 'blockNumber'), 'contractAddress': r['contractAddress'],
             'runtimeSha256': sha256(runtime).hexdigest()}
        store(args.out / 'deployment.json', m)
        block, receipt = check_release(rpc, load(args.out / 'deployment.json'), artifact)
        store(args.out / 'receipt.json', receipt)
        total = charge(receipt, profile, number(block, 'timestamp'))
        need(block['parentHash'] == genesis['hash'] and block['transactions'] == [r['transactionHash']],
             'not_an_isolated_first_block')
        before, after = (int(rpc('eth_getBalance', payer, block_ref(h)), 16)
                         for h in (genesis['hash'], block['hash']))
        need(before - after == total, 'balance_delta_differs_from_fee')
        store(args.out / 'balances.json', {'payer': payer, 'parentHash': genesis['hash'], 'blockHash': block['hash'],
              'beforeWei': str(before), 'afterWei': str(after), 'estimateGas': estimate, 'gasLimit': args.gas_limit})
        print(f'RESULT totalFeeWei={total} payerDebitWei={before-after} balanceMatch=true')


def verify_base(path, profile):
    m = load(path)
    need(m['chainId'] == profile['chainId'], 'wrong_chain_in_release before_public_read=true')

    def rpc(method, *params):
        data = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}).encode()
        with urlopen(Request(profile['rpc'], data, {'Content-Type': 'application/json'}), timeout=15) as res:
            reply = json.load(res)
        need(reply.get('jsonrpc') == '2.0' and reply.get('id') == 1 and 'result' in reply,
             f'{method} unavailable: {reply.get("error")}')
        return reply['result']

    need(int(rpc('eth_chainId'), 16) == profile['chainId'], 'wrong_rpc_chain')
    genesis = rpc('eth_getBlockByNumber', '0x0', False)
    need(genesis and genesis['hash'] == m['genesisHash'] == profile['genesisHash'], 'wrong_or_missing_genesis')
    block, receipt = check_release(rpc, m, build_contract())
    total = charge(receipt, profile, number(block, 'timestamp'))
    print(f'RESULT totalFeeWei={total} basis=public-read-only')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    cmds = parser.add_subparsers(dest='mode', required=True)
    p = cmds.add_parser('local')
    p.add_argument('--out', type=Path, required=True, help='new, non-existing local evidence directory')
    p.add_argument('--expect', choices=('anvil', 'base-sepolia'), default='anvil')
    p.add_argument('--gas-limit', type=int, default=3_000_000, metavar='1000000..5000000')
    p = cmds.add_parser('history')
    p.add_argument('extract', type=Path, nargs='?', default=HERE / 'receipt-22000000.json')
    p = cmds.add_parser('verify-base')
    p.add_argument('manifest', type=Path)
    args = parser.parse_args()
    if args.mode == 'local' and not 1_000_000 <= args.gas_limit <= 5_000_000:
        parser.error('--gas-limit must be between 1000000 and 5000000')
    try:
        if args.mode == 'local':
            local(args)
        elif args.mode == 'history':
            historical(args.extract, load(HERE / 'base-sepolia.json'))
        else:
            verify_base(args.manifest, load(HERE / 'base-sepolia.json'))
    except (Hold, KeyError) as error:
        print(f'HOLD {error} totalFeeWei=unavailable', file=sys.stderr)
        sys.exit(3)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError, RuntimeError) as error:
        sys.exit(f'ERROR {error}; total unavailable')
