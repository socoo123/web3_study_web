"""Trace one locally signed 4337 v0.7 operation. No bundler service or public RPC."""
import argparse
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'm06'))
from chain import anvil, call, encode, event_topic, send_mined
from anvil_lab import RpcError

OP = '(address,uint256,bytes,bytes,bytes32,uint256,bytes32,bytes,bytes)'
EVENT = 'UserOperationEvent(bytes32,address,address,uint256,bool,uint256,uint256)'
VERIFY, EXECUTE, PRE, PM_VERIFY, PM_POST = 150_000, 100_000, 65_000, 85_000, 0
PRICE = 2_000_000_000  # Both fee fields use this wei/gas amount in this lab.
PREFUND = (VERIFY + EXECUTE + PRE + PM_VERIFY + PM_POST) * PRICE


def check(condition, message):
    if not condition:
        raise ValueError(message)


def artifacts():
    path = subprocess.check_output(['bash', HERE / 'prepare.sh', '--offline'], text=True).strip()
    with tarfile.open(path, 'r:gz') as archive:
        def member(name):
            return archive.extractfile('package/' + name).read()

        code = {name: json.loads(member(f'artifacts/{name}.json'))['bytecode']
                for name in ('EntryPoint', 'SimpleAccountFactory')}
        sources = {'Ticket.sol': {'content': (HERE / 'Ticket.sol').read_text()}}
        for name in ('IPaymaster', 'PackedUserOperation'):
            src = f'interfaces/{name}.sol'
            sources[src] = {'content': member(src).decode()}
    settings = {'evmVersion': 'cancun', 'optimizer': {'enabled': True, 'runs': 200},
                'outputSelection': {'Ticket.sol': {'*': ['evm.bytecode.object']}}}
    request = {'language': 'Solidity', 'settings': settings, 'sources': sources}
    result = json.loads(subprocess.check_output([os.environ.get('FOUNDRY_SOLC', 'solc'), '--standard-json'],
                                                input=json.dumps(request), text=True))
    for err in result.get('errors', []):
        if err['severity'] == 'error':
            raise ValueError(err['formattedMessage'])
    for name in ('TicketDesk', 'TicketSponsor'):
        code[name] = '0x' + result['contracts']['Ticket.sol'][name]['evm']['bytecode']['object']
    return code


def data(signature, *args):
    return encode('calldata', signature, args)


def setup(rpc, owner, bundler, code, budget, held):
    def deploy(name, constructor=None, *args):
        tail = encode('abi-encode', constructor, args)[2:] if constructor else ''
        r = send_mined(rpc, {'from': bundler, 'gas': hex(8_000_000), 'data': code[name] + tail})
        return r['contractAddress']

    ep = deploy('EntryPoint')
    factory = deploy('SimpleAccountFactory', 'ctor(address)', ep)
    send_mined(rpc, {'from': bundler, 'to': factory, 'data': data('createAccount(address,uint256)', owner, 0)})
    account = f"0x{call(rpc, factory, 'getAddress(address,uint256)', owner, 0):040x}"
    check(call(rpc, account, 'owner()') == int(owner, 16) and call(rpc, account, 'entryPoint()') == int(ep, 16),
          'unexpected account wiring')
    desk = deploy('TicketDesk', 'ctor(address,bool)', account, str(held).lower())
    sponsor = deploy('TicketSponsor', 'ctor(address,address,address)', ep, account, desk)
    cap = call(rpc, sponsor, 'CAP_WEI()')
    check(cap == PREFUND, 'voucher limit differs from the exercise')
    r = send_mined(rpc, {'from': bundler, 'to': ep, 'value': hex(budget), 'data': data('depositTo(address)', sponsor)})
    print(f'NETWORK chainId={int(rpc("eth_chainId"), 16)} setupBlock={r["blockNumber"]} blockHash={r["blockHash"]}')
    print(f'ROLES entryPoint={ep} owner={owner} account={account} paymaster={sponsor} desk={desk} bundler={bundler}')
    print(f'VOUCHER ticket=27 fullNonce=0 capWei={cap} fundedWei={budget} requiredPrefundWei={PREFUND}')
    return ep, account, desk, sponsor, r['blockNumber']


def packed128(high, low):
    check(0 <= high < 2**128 and 0 <= low < 2**128, 'uint128 packing overflow')
    return f'0x{high:032x}{low:032x}'


def build_bundle(rpc, owner, bundler, ep, account, desk, sponsor, nonce, ticket):
    account_call = data('execute(address,uint256,bytes)', desk, 0, data('record(uint32)', ticket))
    limits = packed128(VERIFY, EXECUTE)
    fees = packed128(PRICE, PRICE)
    paymaster_data = sponsor + packed128(PM_VERIFY, PM_POST)[2:]

    def operation(signature):
        return f'({account},{nonce},0x,{account_call},{limits},{PRE},{fees},{paymaster_data},{signature})'

    op_hash = rpc('eth_call', {'to': ep, 'data': data(f'getUserOpHash({OP})', operation('0x'))}, 'latest')
    signature = rpc('personal_sign', op_hash, owner)
    bundle = data(f'handleOps({OP}[],address)', '[' + operation(signature) + ']', bundler)
    return op_hash, {'from': bundler, 'to': ep, 'data': bundle, 'gas': hex(2_000_000)}


def state(rpc, ep, account, desk, sponsor, block):
    return (call(rpc, ep, 'balanceOf(address)', sponsor, block=block),
            call(rpc, ep, 'getNonce(address,uint192)', account, 0, block=block),
            call(rpc, desk, 'recorded()', block=block))


def trace(rpc, code, args):
    bundler, owner = rpc('eth_accounts')
    ep, account, desk, sponsor, start = setup(rpc, owner, bundler, code, args.budget_wei, args.mode == 'held')
    before = state(rpc, ep, account, desk, sponsor, start)
    check(before == (args.budget_wei, 0, 0), 'unexpected initial deposit, nonce or desk state')
    op_hash, tx = build_bundle(rpc, owner, bundler, ep, account, desk, sponsor, before[1], args.ticket)
    print(f'OP userOpHash={op_hash} signedNonce={before[1]} requestedTicket={args.ticket}')
    query = {'address': ep, 'fromBlock': start, 'topics': [event_topic(EVENT), op_hash]}
    try:
        rpc('eth_call', tx, start)  # Full local dry run, not mempool admission. No transaction hash.
    except RpcError as error:
        # Match the node's complete ABI revert payload, not words in an error message.
        response = ast.literal_eval(str(error).removeprefix('eth_call: '))
        print('RAW_REVERT', json.dumps(response, separators=(',', ':')))
        if before[0] < PREFUND:
            expected = data('FailedOp(uint256,string)', 0, 'AA31 paymaster deposit too low')
            reason, result = 'AA31', 'REJECTED_DEPOSIT'
        elif args.ticket != 27:
            expected = data('FailedOpWithRevert(uint256,string,bytes)', 0, 'AA33 reverted', data('OutsideVoucher()'))
            reason, result = 'AA33/OutsideVoucher', 'REJECTED_SCOPE'
        else:
            raise
        check(response.get('data') == expected, 'unexpected revert bytes, not the requested business refusal')
        latest = rpc('eth_blockNumber')
        logs = rpc('eth_getLogs', {**query, 'toBlock': latest})
        check(not logs and state(rpc, ep, account, desk, sponsor, latest) == before and latest == start,
              'simulation must not change state or produce events')
        print(f'RESULT {result} reason={reason} outerTx=absent opEvents={len(logs)} '
              f'depositWei={before[0]} nonce={before[1]} recorded={before[2]}')
        return 3

    check(before[0] >= PREFUND and args.ticket == 27, 'preflight unexpectedly accepted')
    submitted = send_mined(rpc, tx)
    entry, = rpc('eth_getLogs', {**query, 'toBlock': submitted['blockNumber']})
    receipt = rpc('eth_getTransactionReceipt', entry['transactionHash'])
    print('RAW_RECEIPT', json.dumps(receipt, separators=(',', ':')))
    receipt_log, = [log for log in receipt['logs'] if log['logIndex'] == entry['logIndex']]
    check(all(entry[k] == receipt_log[k] for k in ('address', 'topics', 'data', 'transactionHash', 'blockHash'))
          and not entry.get('removed') and entry['blockHash'] == receipt['blockHash']
          and receipt['transactionHash'] == submitted['transactionHash'] != op_hash and receipt['status'] == '0x1'
          and receipt['from'].lower() == bundler.lower() and receipt['to'].lower() == ep.lower(), 'receipt link mismatch')
    topics = entry['topics']
    check(len(topics) == 4 and topics[:2] == query['topics'] and int(topics[2], 16) == int(account, 16)
          and int(topics[3], 16) == int(sponsor, 16), 'wrong operation participants')
    words = bytes.fromhex(entry['data'][2:])
    check(len(words) == 128, 'UserOperationEvent must contain four ABI data words')
    nonce, success, cost, used = (int.from_bytes(words[i:i+32], 'big') for i in range(0, 128, 32))
    deposit, next_nonce, recorded = state(rpc, ep, account, desk, sponsor, receipt['blockNumber'])
    print(f'GETTERS blockNumber={receipt["blockNumber"]} desk={desk} recorded={recorded} '
          f'accountNonce={next_nonce} paymasterDepositWei={deposit}')
    check(nonce == before[1] and next_nonce == nonce + 1 and 0 < cost <= PREFUND and cost == used * PRICE
          and deposit == before[0] - cost, 'nonce, actual fee or deposit mismatch')
    check(success == int(args.mode == 'open') and recorded == (args.ticket if success else 0), 'unexpected desk outcome')
    if not success:
        reason_topic = event_topic('UserOperationRevertReason(bytes32,address,uint256,bytes)')
        reason, = [log for log in receipt['logs'] if log['address'].lower() == ep.lower()
                   and log['topics'] == [reason_topic, op_hash, topics[2]]]
        check(reason['data'] == encode('abi-encode', 'reason(uint256,bytes)', [nonce, data('TicketHeld()')]),
              'not the TicketHeld execution failure')
        print('INNER_REVERT TicketHeld()')
    print(f'LINK userOpHash={op_hash} transactionHash={receipt["transactionHash"]} blockHash={entry["blockHash"]} '
          f'logIndex={int(entry["logIndex"],16)}')
    print(f'FEE actualGasUsed={used} priceWeiPerGas={PRICE} actualGasCostWei={cost} '
          f'depositBeforeWei={before[0]} depositAfterWei={deposit}')
    result = 'RECORDED' if success else 'INNER_REVERTED'
    print(f'RESULT {result} outerStatus=1 opSuccess={str(bool(success)).lower()} nonceAfter={next_nonce} recorded={recorded}')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--budget-wei', type=int, default=PREFUND)
    parser.add_argument('--mode', choices=('open', 'held'), default='open')
    parser.add_argument('--ticket', type=int, default=27)
    args = parser.parse_args()
    if not 0 <= args.budget_wei <= PREFUND or not 0 <= args.ticket < 2**32:
        parser.error(f'budget-wei must be in [0, {PREFUND}]; ticket must fit uint32')
    code = artifacts()
    with anvil(18727) as rpc:
        return trace(rpc, code, args)


if __name__ == '__main__':
    sys.exit(main())
