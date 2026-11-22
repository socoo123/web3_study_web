"""ABI and receipt helpers for the three local M06 contract labs; no public RPC."""
from functools import cache
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from anvil_lab import anvil, send_mined


def encode(command, signature, args):
    return subprocess.check_output(['cast', command, signature, *map(str, args)], text=True).strip()


@cache
def creation_code(contract):
    source = f'src/{contract}.sol'
    result = subprocess.check_output([
        os.environ.get('FOUNDRY_SOLC', 'solc'), '--evm-version', 'cancun', '--optimize',
        '--optimize-runs', '200', '--combined-json', 'bin', source,
    ], cwd=ROOT, text=True)
    return json.loads(result)['contracts'][f'{source}:{contract}']['bin']


def deploy(rpc, sender, contract, ctor=None, *args):
    tail = encode('abi-encode', ctor, args)[2:] if ctor is not None else ''
    receipt = send_mined(rpc, {'from': sender, 'gas': hex(4_000_000),
                               'data': '0x' + creation_code(contract) + tail})
    return receipt['contractAddress']


def call(rpc, to, sig, *args, block='latest'):
    word = rpc('eth_call', {'to': to, 'data': encode('calldata', sig, args)}, block)
    if len(word) != 66:
        raise ValueError(f'{sig}: expected exactly one ABI result word, got {word}')
    return int(word, 16)


def send(rpc, sender, to, sig, *args, success=True):
    # Explicit gas submits even an intended revert, instead of stopping at estimation.
    tx = {'from': sender, 'to': to, 'gas': hex(2_000_000), 'data': encode('calldata', sig, args)}
    return send_mined(rpc, tx, success=success)


@cache
def event_topic(signature):
    return subprocess.check_output(['cast', 'keccak', signature], text=True).strip().lower()


def check_event(logs, emitter, signature, addresses, amounts):
    """Match one event by contract and topic, then check its indexed addresses and uint data."""
    topic = event_topic(signature)
    entry, = (log for log in logs if log['address'].lower() == emitter.lower()
              and log['topics'] and log['topics'][0].lower() == topic)
    indexed = [f'0x{int(address, 16):064x}' for address in addresses]
    data = '0x' + ''.join(f'{amount:064x}' for amount in amounts)
    if [t.lower() for t in entry['topics'][1:]] != indexed or entry['data'].lower() != data:
        raise ValueError(f'{signature}: event participants or amounts do not match: {entry}')


def units(raw, decimals):
    """Render integer base units without binary floating point or Decimal context rounding."""
    whole, fraction = divmod(abs(raw), 10**decimals)
    digits = f'{fraction:0{decimals}d}'.rstrip('0')
    return ('-' if raw < 0 else '') + str(whole) + ('.' + digits if digits else '')
