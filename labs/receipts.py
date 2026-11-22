"""Observe one local payment; never connect to an existing chain."""
import argparse

from anvil_lab import RpcError, anvil


PORT = 18552
# Runtime: empty calldata -> JUMPDEST, STOP; otherwise REVERT(0, 0).
RUNTIME = '3615600a5760006000fd5b00'
# Copy 12 bytes starting at offset 12 to memory, return them as contract code.
INIT = '0x600c600c600039600c6000f3' + RUNTIME
FEES = {'type': '0x2', 'maxFeePerGas': hex(10_000_000_000),
        'maxPriorityFeePerGas': hex(1_000_000_000)}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def number(value):
    return int(value, 16)


def state(rpc, label, block, payer, shop):
    tag = block['number']
    balance = number(rpc('eth_getBalance', payer, tag))
    received = number(rpc('eth_getBalance', shop, tag))
    nonce = number(rpc('eth_getTransactionCount', payer, tag))
    print(f'{label} height={number(tag)} block={block["hash"]} payerWei={balance} '
          f'shopWei={received} nonce={nonce}')
    return balance, received, nonce


def observe_depth(rpc, receipt, credited, expected):
    h, block_hash = receipt['blockNumber'], receipt['blockHash']
    at_height = rpc('eth_getBlockByNumber', h, False)
    require(at_height is not None and at_height['hash'] == block_hash,
            'Receipt anchor is no longer canonical; do not count confirmations')
    require(at_height['transactions'] == [receipt['transactionHash']],
            'Expected exactly the order transaction in this isolated block')
    head = rpc('eth_getBlockByNumber', 'latest', False)
    depth = number(head['number']) - number(h) + 1
    require(head['hash'] == block_hash or head['parentHash'] == block_hash,
            'Expected the receipt block or its immediate child in this lab')
    if number(receipt['status']) == 0:
        decision = 'HOLD_REVERTED'
    elif credited != expected:
        decision = 'HOLD_AMOUNT'
    elif depth < 2:
        decision = 'HOLD_DEPTH'
    else:
        decision = 'READY_LOCAL'
    print(f'DEPTH height={number(h)} canonicalHash={at_height["hash"]} '
          f'head={number(head["number"])} headHash={head["hash"]} '
          f'confirmations={depth} orderState={decision}')
    return decision


def observe_payment(rpc, args):
    payer, installer = rpc('eth_accounts')
    rpc('evm_setAutomine', False)
    deploy = rpc('eth_sendTransaction', {**FEES, 'from': installer, 'data': INIT, 'gas': hex(100_000)})
    rpc('evm_mine')
    setup = rpc('eth_getTransactionReceipt', deploy)
    require(setup and number(setup['status']) == 1, 'Shop deployment did not succeed')
    shop = setup['contractAddress']
    before = rpc('eth_getBlockByNumber', setup['blockNumber'], False)
    code = rpc('eth_getCode', shop, before['number'])
    require(before['hash'] == setup['blockHash'] and code == '0x' + RUNTIME,
            'Shop code or setup anchor differs')
    chain = number(rpc('eth_chainId'))
    require(chain == 31337, 'Unexpected chain')
    print(f'ORDER id={args.order_id} chain={chain} payer={payer} shop={shop} '
          f'orderWei={args.order_wei} requiredDepth=2 shopCode={code}')
    b0, s0, n0 = state(rpc, 'BEFORE', before, payer, shop)
    snapshot = rpc('evm_snapshot') if args.replace_block else None

    absent = '0x' + '00' * 32  # A lookup control, not a submitted transaction.
    require(rpc('eth_getTransactionReceipt', absent) is None and
            rpc('eth_getTransactionByHash', absent) is None, 'Lookup control unexpectedly exists')
    print(f'UNSEEN control={absent} receipt=null transaction=null')
    value = args.order_wei - int(args.short_pay)
    data = '0x01' if args.reject else '0x'
    tx_hash = rpc('eth_sendTransaction', {**FEES, 'from': payer, 'to': shop, 'nonce': hex(n0),
                                         'value': hex(value), 'data': data, 'gas': hex(50_000)})
    pending = rpc('eth_getTransactionByHash', tx_hash)
    require(rpc('eth_getTransactionReceipt', tx_hash) is None and pending and
            pending['hash'] == tx_hash and pending.get('blockNumber') is None and
            pending.get('blockHash') is None, 'Expected a known, unmined transaction')
    print(f'PENDING tx={tx_hash} nonce={number(pending["nonce"])} receipt=null block=none')

    rpc('evm_mine')
    r = rpc('eth_getTransactionReceipt', tx_hash)
    tx = rpc('eth_getTransactionByHash', tx_hash)
    require(r and tx and r['transactionHash'] == tx_hash == tx['hash'] and
            tx['blockHash'] == r['blockHash'] and tx['blockNumber'] == r['blockNumber'] and
            tx['from'].lower() == payer.lower() and tx['to'].lower() == shop.lower() and
            number(tx['nonce']) == n0 and number(tx['value']) == value and tx['input'] == data,
            'Mined transaction does not match the submitted attempt')
    included = rpc('eth_getBlockByNumber', r['blockNumber'], False)
    require(included and included['hash'] == r['blockHash'] and included['parentHash'] == before['hash']
            and included['transactions'] == [tx_hash], 'Expected the payment alone after the setup block')
    status, used, price = number(r['status']), number(r['gasUsed']), number(r['effectiveGasPrice'])
    fee = used * price
    print(f'RECEIPT tx={tx_hash} from={tx["from"]} to={tx["to"]} nonce={number(tx["nonce"])} '
          f'valueWei={value} input={data} status={status} height={number(r["blockNumber"])} '
          f'block={r["blockHash"]} gasUsed={used} priceWeiPerGas={price} feeWei={fee}')
    b1, s1, n1 = state(rpc, 'AFTER', included, payer, shop)
    credited = s1 - s0
    require(status == (0 if args.reject else 1) and n1 == n0 + 1 and fee > 0 and
            credited == (value if status == 1 else 0) and b0 - b1 == credited + fee,
            'Receipt status, nonce, or two-sided balance equation failed')
    observe_depth(rpc, r, credited, args.order_wei)
    rpc('evm_mine')
    last = observe_depth(rpc, r, credited, args.order_wei)

    if args.replace_block:
        require(rpc('evm_revert', snapshot) is True, 'Snapshot restore failed')
        rpc('evm_mine')  # Same height as the old receipt, no order transaction.
        new = rpc('eth_getBlockByNumber', r['blockNumber'], False)
        require(new and new['hash'] != r['blockHash'] and new['parentHash'] == before['hash'] and
                new['transactions'] == [] and rpc('eth_getTransactionReceipt', tx_hash) is None,
                'Expected a different empty block and no receipt at the old height')
        require(state(rpc, 'RESTORED', new, payer, shop) == (b0, s0, n0),
                'Order effects remain after restoring the parent')
        last = 'HOLD_RECHECK'
        print(f'ROLLBACK height={number(new["number"])} oldHash={r["blockHash"]} '
              f'canonicalHash={new["hash"]} receipt=null orderState={last}')
    return tx_hash, last


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--order-id', default='R-12')
    parser.add_argument('--order-wei', type=int, default=3_000_000_000_000_000)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--short-pay', action='store_true', help='send one wei less than the invoice')
    mode.add_argument('--reject', action='store_true', help='send nonempty calldata so the shop reverts')
    parser.add_argument('--replace-block', action='store_true', help='restore parent, mine empty replacement')
    args = parser.parse_args()
    if not 2 <= args.order_wei <= 10**18:
        parser.error('--order-wei must be between 2 wei and 1 test ETH (inclusive)')
    with anvil(PORT) as rpc:
        tx_hash, last = observe_payment(rpc, args)
    # The context has stopped *our* listener. The same read now fails at transport level.
    try:
        rpc('eth_getTransactionReceipt', tx_hash)
    except OSError as err:
        print(f'RPC_UNAVAILABLE tx={tx_hash} transport={type(err).__name__} '
              f'lastKnown={last} freshObservation=no resend=no')
    else:
        raise RuntimeError('Expected the local endpoint to be unreachable after shutdown')


if __name__ == '__main__':
    try:
        main()
    except RpcError as err:
        raise SystemExit(f'RPC_ERROR (not a transaction execution status): {err}') from err
