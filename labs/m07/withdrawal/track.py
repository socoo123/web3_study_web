"""Offline, single-withdrawal OP Sepolia Standard Bridge ETH case reader."""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

L2_BRIDGE = '0x4200000000000000000000000000000000000010'
PASSER = '0x4200000000000000000000000000000000000016'
L2_MSG = '0x4200000000000000000000000000000000000007'
PORTAL = '0x16fc5058f25648194471939df75cf27a2fdc48bc'
L1_MSG = '0x58cc85b8d04ea49cc6dbd3cbffd00b4b8d6cb3ef'
L1_BRIDGE = '0xfbb0621e0b23b5478b630bd55a5f21f67730b0f1'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def keccak(arg):
    # Foundry's Ethereum Keccak-256; Python hashlib.sha3_256 is NOT equivalent.
    return subprocess.check_output(['cast', 'keccak', arg], text=True).strip()


def raw(s):
    require(s.startswith('0x'), 'not hex data')
    return bytes.fromhex(s[2:])


def hx(data):
    return '0x' + data.hex()


def word(n):
    return n.to_bytes(32, 'big')


def slot(data, i):
    require(len(data) >= (i + 1) * 32, 'short ABI head')
    return data[i * 32:(i + 1) * 32]


def address(w):
    require(len(w) == 32 and w[:12] == bytes(12), 'not a padded address')
    return hx(w[12:])


def tail(data, offset_word, head_words):
    """All tuples used here have exactly one dynamic field, of type bytes."""
    start = head_words * 32
    require(slot(data, offset_word) == word(start), 'unexpected dynamic offset')
    length = int.from_bytes(slot(data, head_words), 'big')
    body = data[start + 32:]
    require(len(body) == (length + 31) // 32 * 32 and not any(body[length:]), 'bad bytes padding')
    return body[:length]


def event(receipt, emitter, signature, required=True):
    topic = keccak(signature)
    hits = [l for l in receipt['logs'] if l['address'] == emitter and l['topics'][0] == topic]
    if not hits and not required:
        return None
    require(len(hits) == 1, f'expected one {signature} from {emitter}, got {len(hits)}')
    return hits[0]


def receipt(packet, name, to):
    r, h = packet['receipts'][name], packet['blocks'][name]
    require(r['to'] == to and r['status'] == '0x1', 'wrong contract or failed outer transaction')
    require((r['blockNumber'], r['blockHash']) == (h['number'], h['hash']), 'receipt block mismatch')
    for l in r['logs']:
        require(not l['removed'] and all(l[k] == r[k] for k in ('blockHash', 'blockNumber', 'transactionHash', 'transactionIndex')), 'log anchor mismatch')
    utc = datetime.fromtimestamp(int(h['timestamp'], 16), timezone.utc).isoformat()
    print(f'{name.upper()} height={int(h["number"],16)} block={h["hash"]} utc={utc} tx={r["transactionHash"]}')
    return r


def observation(packet, key, method, request, block):
    obs = packet['reads'][key]
    require(obs['method'] == method and obs['params'] == [request, {'blockHash': block, 'requireCanonical': True}], f'{key}: request/anchor mismatch')
    return obs['response']


def replay(p, view):
    require(p['chainId'] == {'source': '0xaa37dc', 'l1': '0xaa36a7'}, 'unexpected network pair')
    print(f'ROUTE OP-Sepolia:11155420 -> Sepolia:11155111 captured={p["capturedUtc"]}')
    src = receipt(p, 'source', L2_BRIDGE)
    origin = event(src, L2_BRIDGE, 'ETHBridgeInitiated(address,address,uint256,bytes)')
    passed = event(src, PASSER, 'MessagePassed(uint256,address,address,uint256,uint256,bytes,bytes32)')
    fields = [raw(t) for t in passed['topics'][1:]]
    nonce, messenger, target = fields
    require((address(messenger), address(target)) == (L2_MSG, L1_MSG), 'not the official messenger route')
    body = raw(passed['data'])
    relay = tail(body, 2, 4)
    # abi.encode(nonce, sender, target, value, gasLimit, data): dynamic offset is 6 words.
    preimage = nonce + messenger + target + body[:64] + word(192) + body[128:]
    w = keccak(hx(preimage))
    require(w == hx(slot(body, 3)), 'withdrawal hash differs from MessagePassed')
    require(relay[:4].hex() == 'd764ad0b', 'expected relayMessage v1 selector')
    m = keccak(hx(relay))
    args = relay[4:]
    require(int.from_bytes(slot(args, 0), 'big') >> 240 == 1 and address(slot(args, 1)) == L2_BRIDGE and address(slot(args, 2)) == L1_BRIDGE, 'not the v1 Standard Bridge relay')
    inner = tail(args, 5, 6)
    require(inner[:4].hex() == '1635f5fd', 'expected finalizeBridgeETH')
    inner = inner[4:]
    sender, payee = map(address, (slot(inner, 0), slot(inner, 1)))
    amount_word, extra = slot(inner, 2), tail(inner, 3, 4)
    orig_data = raw(origin['data'])
    require(origin['topics'][1:] == [hx(slot(inner, 0)), hx(slot(inner, 1))] and tail(orig_data, 1, 2) == extra, 'source transfer identity mismatch')
    require(amount_word == slot(orig_data, 0) == slot(args, 3) == slot(body, 0), 'bridge / relay / withdrawal amount mismatch')
    amount = int.from_bytes(amount_word, 'big')
    print(f'INITIATED W={w} M={m} from={sender} to={payee} amountWei={amount}')
    if view == 'source-only':
        return 'PROCESSING reason=no_L1_evidence'

    proof = receipt(p, 'proof', PORTAL)
    proven = event(proof, PORTAL, 'WithdrawalProven(bytes32,address,address)')
    ext = event(proof, PORTAL, 'WithdrawalProvenExtension1(bytes32,address)')
    require(proven['topics'][1:] == [w, hx(messenger), hx(target)] and ext['topics'][1] == w, 'proof identity mismatch')
    submitter = raw(ext['topics'][2])
    print(f'PROVEN W={w} proofSubmitter={address(submitter)}')
    check_data = '0x71c1566e' + w[2:] + submitter.hex()
    check_request = {'to': PORTAL, 'data': check_data}
    early = observation(p, 'proofCheck', 'eth_call', check_request, proof['blockHash'])
    require(early.get('error', {}).get('data') == '0xd9bc01be', 'expected historical ProofNotOldEnough revert')
    if view == 'proof':
        return 'PROCESSING reason=proof_not_old_enough'

    h = p['blocks']['ready']
    require(int(h['number'], 16) > int(proof['blockNumber'], 16), 'ready observation predates proof')
    for key, data, expected in [('check', check_data, '0x'), ('paused', '0x5c975abb', hx(word(0))), ('finalized', '0xa14238e7' + w[2:], hx(word(0)))]:
        response = observation(p, key, 'eth_call', {'to': PORTAL, 'data': data}, h['hash'])
        require(response.get('result') == expected, f'{key} did not pass')
    # Bind the recorded read-only finalization simulation to this exact withdrawal and prover.
    simulated = p['reads']['simulate']['params'][0]
    calldata = '0x43ca1c50' + (word(64) + submitter + preimage).hex()
    request = {'from': address(submitter), 'to': PORTAL, 'gas': simulated['gas'], 'value': '0x0', 'data': calldata}
    require(observation(p, 'simulate', 'eth_call', request, h['hash']).get('result') == '0x', 'finalize simulation not successful')
    print(f'READY height={int(h["number"],16)} block={h["hash"]} paused=false finalized=false check=ok simulation=ok')
    if view == 'ready':
        return 'CLAIMABLE as_of=READY not_paid_yet=true'

    fin = receipt(p, 'final', PORTAL)
    require(p['blocks']['final']['parentHash'] == h['hash'], 'readiness is not anchored to parent of final block')
    if view == 'without-payment':
        fin = dict(fin, logs=[l for l in fin['logs'] if l['address'] != L1_BRIDGE])
    done = event(fin, PORTAL, 'WithdrawalFinalized(bytes32,bool)', required=False)
    relayed = event(fin, L1_MSG, 'RelayedMessage(bytes32)', required=False)
    paid = event(fin, L1_BRIDGE, 'ETHBridgeFinalized(address,address,uint256,bytes)', required=False)
    portal_ok = done is not None and done['topics'][1:] == [w] and done['data'] == hx(word(1))
    relay_ok = relayed is not None and relayed['topics'][1:] == [m]
    bridge_ok = paid is not None and paid['topics'][1:] == origin['topics'][1:] and paid['data'] == origin['data']
    print(f'DELIVERY portal={portal_ok} messenger={relay_ok} bridgePayment={bridge_ok}')
    before, after = [int(observation(p, k, 'eth_getBalance', payee, block)['result'], 16) for k, block in [('balanceBefore', h['hash']), ('balanceAfter', fin['blockHash'])]]
    fee = int(fin['gasUsed'], 16) * int(fin['effectiveGasPrice'], 16)
    print(f'BALANCE payeeBlockDeltaWei={after-before} finalizer={fin["from"]} finalTxFeeWei={fee}')
    return 'COMPLETED asset=testETH' if portal_ok and relay_ok and bridge_ok else 'PROCESSING reason=payment_not_established'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--case', choices=('A', 'B'), default='A')
    parser.add_argument('--view', choices=('source-only', 'proof', 'ready', 'full', 'without-payment'), default='full')
    args = parser.parse_args()
    try:
        packet = json.loads(Path(__file__).with_name(f'case-{args.case}.json').read_text())
        print('RESULT', replay(packet, args.view))
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError, IndexError) as err:
        sys.exit(f'INVALID_EVIDENCE: {err}')
