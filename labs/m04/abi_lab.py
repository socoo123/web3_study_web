"""Compare independent Java/Cast ABI codecs with execution and state on a fresh Anvil."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT.parent))
from anvil_lab import anvil, send_mined

SET = 'set(uint256)'


def output(*args):
    return subprocess.check_output(args, cwd=PROJECT, text=True).strip()


def same(label, actual, expected):
    if actual != expected:
        raise RuntimeError(f'{label}: expected {expected!r}, got {actual!r}')


def decoded(cast_cmd, sig, data):
    # v1.7.1 prints small uints as JSON integers, larger ones as strings. Never use floats.
    [amount] = json.loads(output('cast', cast_cmd, '--json', sig, data), parse_int=str)
    return amount


def run(amount, classes):
    output('javac', '--release', '17', '-d', classes, 'AmountAbi.java')

    def java(op, arg):
        return output('java', '-cp', classes, 'AmountAbi', op, arg)

    java_data = java('encode', amount)  # Reject out-of-domain orders before starting a node.
    expected = str(int(amount, 10))
    cast_data = output('cast', 'calldata', SET, expected)
    print(f'CALLDATA java={java_data}\nCALLDATA cast={cast_data}')
    same('calldata', java_data, cast_data)
    java_in = java('decode-call', cast_data)
    cast_in = decoded('decode-calldata', SET, java_data)
    same('decoded input', (java_in, cast_in), (expected, expected))
    print(f'INPUT java_wei={java_in} cast_wei={cast_in}')

    output('forge', 'build', '--root', '.', '--offline', 'src/AmountRegister.sol')
    artifact = json.loads((PROJECT / 'out/AmountRegister.sol/AmountRegister.json').read_text())
    get_data = output('cast', 'calldata', 'get()')
    with anvil(18613) as rpc:
        sender = rpc('eth_accounts')[0]
        deployment = send_mined(rpc, {'from': sender, 'data': artifact['bytecode']['object'],
                                      'gas': hex(500_000), 'value': '0x0'})
        address = deployment['contractAddress']
        print(f'DEPLOY chain_id=31337 address={address} tx={deployment["transactionHash"]}')
        setter = {'from': sender, 'to': address, 'data': java_data, 'value': '0x0'}
        getter = {'to': address, 'data': get_data}
        returned = rpc('eth_call', setter, deployment['blockNumber'])
        java_out = java('decode-result', returned)
        cast_out = decoded('decode-abi', SET + '(uint256)', returned)
        same('decoded return', (java_out, cast_out), (expected, expected))
        after_sim = int(rpc('eth_call', getter, 'latest'), 16)
        same('state after simulation', after_sim, 0)
        print(f'RETURN data={returned} java_wei={java_out} cast_wei={cast_out}')
        print(f'SIMULATION stored_wei={after_sim}')

        receipt = send_mined(rpc, {**setter, 'gas': hex(100_000)})
        tx = rpc('eth_getTransactionByHash', receipt['transactionHash'])
        same('mined calldata', tx['input'], java_data)
        same('mined value', int(tx['value'], 16), 0)
        at = receipt['blockNumber']
        readback = rpc('eth_call', getter, at)
        slot = rpc('eth_getStorageAt', address, '0x0', at)
        same('getter bytes', readback, returned)
        same('slot 0', slot, returned)
        balance = int(rpc('eth_getBalance', address, at), 16)
        same('contract balance', balance, 0)
        print(f'MINED tx={receipt["transactionHash"]} block={int(at, 16)} '
              f'block_hash={receipt["blockHash"]} status=1 value_wei=0')
        print(f'STATE get_wei={int(readback, 16)} slot0={slot} contract_balance_wei={balance}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--amount-wei', default='9007199254740993', metavar='DECIMAL')
    args = parser.parse_args()
    try:
        with tempfile.TemporaryDirectory(prefix='m04-java-') as classes:
            run(args.amount_wei, classes)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode)
