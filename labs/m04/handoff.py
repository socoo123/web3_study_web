"""Verify and query a local escrow using its release manifest. No build tools or keys."""
import argparse
from hashlib import sha256
from http.client import HTTPConnection
import json
from pathlib import Path
import sys


PORT = 18556


class Mismatch(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise Mismatch(reason)


def rpc(method, *params):
    # The endpoint is a local course convention, never taken from a manifest or proxy env var.
    connection = HTTPConnection('127.0.0.1', PORT, timeout=5)
    try:
        body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
        connection.request('POST', '/', body, {'Content-Type': 'application/json'})
        response = connection.getresponse()
        if response.status != 200:
            raise OSError(f'{method}: HTTP {response.status}')
        reply = json.load(response)
        if reply.get('id') != 1 or reply.get('jsonrpc') != '2.0' or 'result' not in reply:
            raise OSError(f"{method}: {reply.get('error', 'invalid JSON-RPC response')}")
        return reply['result']
    finally:
        connection.close()


def abi_digest(abi):
    data = json.dumps(abi, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    return sha256(data).hexdigest()


def hex_bytes(value):
    require(isinstance(value, str) and value.startswith('0x'), 'expected RPC hex data')
    return bytes.fromhex(value[2:])


def constructor_words(abi, payee, deadline):
    inputs = [[i['type'] for i in f['inputs']] for f in abi if f['type'] == 'constructor']
    require(inputs == [['address', 'uint256']], 'unexpected constructor ABI')
    address = hex_bytes(payee)
    require(len(address) == 20 and 0 < deadline < 2**256, 'invalid constructor values')
    return bytes(12) + address + deadline.to_bytes(32, 'big')


def selector(call_rpc, signature):
    digest = hex_bytes(call_rpc('web3_sha3', '0x' + signature.encode('ascii').hex()))
    require(len(digest) == 32, 'invalid Keccak result')
    return '0x' + digest[:4].hex()


def verify(manifest):
    m = manifest
    require(m['format'] == 'm04-escrow-release/1', 'unknown manifest format')
    require(rpc('web3_clientVersion') == 'anvil/v1.7.1', 'not the course Anvil version')
    chain = int(rpc('eth_chainId'), 16)
    require(chain == m['chainId'] == 31337, 'chain ID mismatch')
    height, block_hash = m['deploymentBlockNumber'], m['deploymentBlockHash']
    block = rpc('eth_getBlockByNumber', hex(height), False)
    require(block is not None, f'chainId={chain} missing deployment block {height}')
    require(block['hash'] == block_hash, 'canonical deployment block hash mismatch')
    tx_hash, address = m['deploymentTransactionHash'], m['contractAddress']
    receipt = rpc('eth_getTransactionReceipt', tx_hash)
    require(tx_hash in block['transactions'] and receipt and receipt['status'] == '0x1'
            and receipt['transactionHash'] == tx_hash and receipt['blockHash'] == block_hash
            and int(receipt['blockNumber'], 16) == height and receipt['contractAddress'] == address,
            'creation receipt mismatch')
    tx = rpc('eth_getTransactionByHash', tx_hash)
    require(tx and tx['hash'] == tx_hash and tx.get('to') is None and tx['blockHash'] == block_hash
            and tx['from'] == m['deployer'] and int(tx['value'], 16) == 0, 'creation tx mismatch')
    abi = m['abi']
    require(abi_digest(abi) == m['build']['abiSha256'], 'ABI fingerprint mismatch')
    args = m['constructor']
    tail = constructor_words(abi, args['payee'], args['deadline'])
    init = hex_bytes(tx['input'])
    require(len(init) > len(tail) and init.endswith(tail), 'constructor argument mismatch')
    require(sha256(init[:-len(tail)]).hexdigest() == m['build']['creationCodeSha256'],
            'creation bytecode fingerprint mismatch')

    head = rpc('eth_getBlockByNumber', 'latest', False)
    at = {'blockHash': head['hash'], 'requireCanonical': True}
    code = hex_bytes(rpc('eth_getCode', address, at))
    require(code and sha256(code).hexdigest() == m['runtimeSha256'], 'runtime code mismatch')

    def read_word(name, output_type, arg_address=None):
        # Only the five static, unambiguous getters in this course; no arbitrary manifest methods.
        functions = [f for f in abi if f['type'] == 'function' and f['name'] == name]
        require(len(functions) == 1, f'absent or ambiguous ABI: {name}')
        f = functions[0]
        types = [i['type'] for i in f['inputs']]
        require(types == ([] if arg_address is None else ['address']) and f['stateMutability'] == 'view'
                and [o['type'] for o in f['outputs']] == [output_type], f'wrong ABI: {name}')
        data = selector(rpc, f"{name}({','.join(types)})")
        if arg_address is not None:
            data += (bytes(12) + hex_bytes(arg_address)).hex()
        word = hex_bytes(rpc('eth_call', {'to': address, 'data': data}, at))
        require(len(word) == 32, f'invalid ABI word: {name}')
        if output_type == 'address':
            require(not any(word[:12]), f'invalid ABI address: {name}')
            return '0x' + word[12:].hex(), data
        return int.from_bytes(word, 'big'), data

    payer, _ = read_word('payer', 'address')
    payee, _ = read_word('payee', 'address')
    deadline, _ = read_word('deadline', 'uint256')
    require((payer, payee, deadline) == (m['deployer'].lower(), args['payee'].lower(), args['deadline']),
            'deployer/constructor getters mismatch')
    state, _ = read_word('state', 'uint8')
    require(0 <= state <= 3, 'unknown escrow state')
    credit, calldata = read_word('credit', 'uint256', payee)
    balance = int(rpc('eth_getBalance', address, at), 16)
    return {'chainId': chain, 'contractAddress': address, 'deploymentBlockNumber': height,
            'deploymentBlockHash': block_hash, 'readBlockNumber': int(head['number'], 16),
            'readBlockHash': head['hash'], 'payer': payer, 'payee': payee, 'deadline': deadline,
            'state': state, 'creditCalldata': calldata, 'payeeCreditWei': str(credit),
            'escrowBalanceWei': str(balance)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(json.loads(args.manifest.read_text())), indent=2))
    except Mismatch as error:
        print(f'STOP {error}', file=sys.stderr)
        sys.exit(3)
    except (OSError, ValueError, TypeError, KeyError) as error:
        sys.exit(f'ERROR cannot complete handoff: {error}')
