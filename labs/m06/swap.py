"""Quote two sizes at one block, reject a tight minimum, then settle on Anvil."""
import argparse
import json
from decimal import Decimal
from typing import NamedTuple

from chain import anvil, call, check_event, deploy, send, units

A, B = 10**18, 10**6  # base units per whole token


class Ledger(NamedTuple):
    poolA: int
    poolB: int
    walletA: int
    walletB: int
    allowanceA: int


def state(rpc, block, a, b, pool, wallet):
    def balance(token, holder):
        return call(rpc, token, 'balanceOf(address)', holder, block=block)

    row = Ledger(balance(a, pool), balance(b, pool), balance(a, wallet), balance(b, wallet),
                 call(rpc, a, 'allowance(address,address)', wallet, pool, block=block))
    print('STATE_RAW', f'block={block}', *(f'{k}={v}' for k, v in row._asdict().items()))
    return row


def quoted(rpc, pool, block, row, amount):
    q = call(rpc, pool, 'quote(uint256)', amount, block=block)
    assert q == (997 * amount * row.poolB) // (1000 * row.poolA + 997 * amount)
    average = (Decimal(q) * A) / (amount * B)
    print(f'QUOTE block={block} inputA18={units(amount, 18)} outRawB6={q} avgB6PerA18={average:f}')
    return q


def run(small):
    with anvil(18623) as rpc:
        chain_id = int(rpc('eth_chainId'), 16)
        assert chain_id == 31337
        seed, wallet = rpc('eth_accounts')[:2]
        ctor = 'constructor(string,uint8,uint256)'
        a = deploy(rpc, seed, 'LabToken', ctor, 'A18', 18, 1100 * A)
        b = deploy(rpc, seed, 'LabToken', ctor, 'B6', 6, 2000 * B)
        pool = deploy(rpc, seed, 'CoursePool', 'constructor(address,address)', a, b)
        assert (call(rpc, a, 'decimals()'), call(rpc, b, 'decimals()')) == (18, 6)
        print(f'PAIR chainId={chain_id} A18={a} B6={b} pool={pool} wallet={wallet}')
        send(rpc, seed, a, 'transfer(address,uint256)', pool, 1000 * A)
        send(rpc, seed, b, 'transfer(address,uint256)', pool, 2000 * B)
        send(rpc, seed, a, 'transfer(address,uint256)', wallet, 100 * A)
        amount = small * A
        approved = send(rpc, wallet, a, 'approve(address,uint256)', pool, amount)
        base = approved['blockNumber']
        print(f'BASE block={base} hash={approved["blockHash"]}')
        before = state(rpc, base, a, b, pool, wallet)
        assert before == Ledger(1000 * A, 2000 * B, 100 * A, 0, amount)
        q = quoted(rpc, pool, base, before, amount)
        large = quoted(rpc, pool, base, before, 100 * A)
        assert q * 100 > large * small  # compare average outputs without division

        # Reject first: both receipts remain on the same canonical local chain.
        print(f'REQUEST reject minOutRawB6={q + 1}')
        bad = send(rpc, wallet, pool, 'swap(uint256,uint256)', amount, q + 1, success=False)
        print('REJECT_RECEIPT', json.dumps(bad))
        rejected = bad['blockNumber']
        after_reject = state(rpc, rejected, a, b, pool, wallet)
        assert after_reject == before and not bad['logs']
        fee = int(bad['gasUsed'], 16) * int(bad['effectiveGasPrice'], 16)
        eth_before = int(rpc('eth_getBalance', wallet, base), 16)
        eth_after = int(rpc('eth_getBalance', wallet, rejected), 16)
        assert eth_before - eth_after == fee and fee > 0
        print(f'REJECT status={bad["status"]} logs=0 nativeFeeWei={fee} tokenLedgerUnchanged=true')

        fresh = quoted(rpc, pool, rejected, after_reject, amount)
        assert fresh == q
        minimum = (fresh * 9950 + 9999) // 10000  # ceil; never allow a loss above 50 bp
        print(f'REQUEST fill minOutRawB6={minimum}')
        ok = send(rpc, wallet, pool, 'swap(uint256,uint256)', amount, minimum)
        print('FILL_RECEIPT', json.dumps(ok))
        after = state(rpc, ok['blockNumber'], a, b, pool, wallet)
        assert after == Ledger(before.poolA + amount, before.poolB - fresh,
                               before.walletA - amount, before.walletB + fresh, 0)
        assert after.poolA * after.poolB >= before.poolA * before.poolB
        transfer = 'Transfer(address,address,uint256)'
        check_event(ok['logs'], a, transfer, [wallet, pool], [amount])
        check_event(ok['logs'], b, transfer, [pool, wallet], [fresh])
        check_event(ok['logs'], pool, 'Swap(address,uint256,uint256)', [wallet], [amount, fresh])
        print(f'FILL status={ok["status"]} walletReceivedRawB6={after.walletB - before.walletB} '
              f'allowanceRawA18={after.allowanceA} matched=TransferA,TransferB,Swap')
        quoted(rpc, pool, ok['blockNumber'], after, amount)  # not a second fill


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trade-in', type=int, default=10, help='small order in whole A18 (1–99)')
    args = parser.parse_args()
    if not 1 <= args.trade_in < 100:
        parser.error('--trade-in must be 1..99 whole A18; comparison order is 100')
    run(args.trade_in)
