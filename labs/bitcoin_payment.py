"""第 06 课：在一次性 regtest 上取得可复算的付款凭证。"""
import sys
from decimal import Decimal

from regtest import SAT, btc, check, run, sat

PAY_SAT = 125_000_000          # Alice 实际发出的货款
FEE_SAT = 1_000               # 绝对费用，不是费率
ORDER_DUE_SAT = 125_000_000    # 商户保存的订单；不从交易的输出推算
MIN_CONFIRMATIONS = 2         # 本订单的业务规则，不是 Bitcoin 共识规则


def mature_reward(rpc, alice, miner):
    # 只有第一项奖励进 Alice，以后出块不再干扰双方的余额差。
    for count, destination, height in [(1, alice, 1), (99, miner, 100), (1, miner, 101)]:
        tip = rpc('generatetoaddress', count, destination)[-1]
        if height == 1:
            reward_block = tip
            reward_id = rpc('getblock', tip)['tx'][0]
        depth = rpc('gettransaction', reward_id, wallet='alice')['confirmations']
        balances = rpc('getbalances', wallet='alice')
        immature = sat(balances['mine']['immature'])
        trusted = sat(balances['mine']['trusted'])
        observed_height = balances['lastprocessedblock']['height']
        coins = rpc('listunspent', wallet='alice')
        print(f'MATURITY height={observed_height} reward_confirmations={depth} immature_sat={immature} trusted_sat={trusted} selectable={len(coins)}')
        expected = (0, 50 * SAT, 1) if height == 101 else (50 * SAT, 0, 0)
        check(observed_height == depth == height and (immature, trusted, len(coins)) == expected,
              '区块奖励的成熟期证据不匹配')

    coin, = coins
    outpoint = {'txid': coin['txid'], 'vout': coin['vout']}
    old = rpc('gettxout', coin['txid'], coin['vout'])
    check(old is not None and old['coinbase'] and coin['txid'] == reward_id and
          old['scriptPubKey']['address'] == alice and sat(old['value']) == sat(coin['amount']), '输入来源不匹配')
    print(f"UTXO txid={coin['txid']} vout={coin['vout']} coinbase={old['coinbase']} input_sat={sat(old['value'])}")
    return outpoint, old, reward_block


def sign_payment(rpc, outpoint, old, reward_block, bob, change):
    change_sat = sat(old['value']) - PAY_SAT - FEE_SAT
    check(change_sat > 0, '输入不足以支付金额、手续费并产生找零')
    raw = rpc('createrawtransaction', [outpoint], [{bob: btc(PAY_SAT)}, {change: btc(change_sat)}])
    signed = rpc('signrawtransactionwithwallet', raw, wallet='alice')
    check(signed['complete'], 'Alice 无法完成对所选输入的签名')
    tx = rpc('decoderawtransaction', signed['hex'])
    vin, = tx['vin']  # 本题恰好一个输入；多输入时每一个都要查，不能只取第一项。
    check((vin['txid'], vin['vout']) == (outpoint['txid'], outpoint['vout']), '签名后输入已改变')
    parent = rpc('getrawtransaction', vin['txid'], 1, reward_block)
    prev = parent['vout'][vin['vout']]
    prev_script = prev['scriptPubKey']
    check(parent['in_active_chain'] and parent['txid'] == vin['txid'] and prev['n'] == vin['vout'] and
          prev['value'] == old['value'] and prev_script['hex'] == old['scriptPubKey']['hex'], '前序交易与 UTXO 快照不符')
    prev_sat = sat(prev['value'])
    print(f"PREVOUT blockhash={reward_block} txid={parent['txid']} vout={prev['n']} value_sat={prev_sat} type={prev_script['type']} script_hex={prev_script['hex']}")

    witness = vin.get('txinwitness', [])
    check(prev_script['type'] == 'witness_v0_keyhash' and vin['scriptSig']['hex'] == '' and len(witness) == 2,
          '不是本题的原生 P2WPKH 花费')
    sig, pubkey = witness
    funding_info = rpc('getaddressinfo', prev_script['address'], wallet='alice')
    check(bool(sig) and pubkey == funding_info['pubkey'], '见证公钥与原收款钱包不符')
    print(f"SIGNED complete={signed['complete']} prev_txid={vin['txid']} prev_vout={vin['vout']} witness_items={len(witness)} vsize={tx['vsize']} signature_item_bytes={len(bytes.fromhex(sig))} pubkey_bytes={len(bytes.fromhex(pubkey))}")

    bob_info = rpc('getaddressinfo', bob, wallet='bob')
    change_info = rpc('getaddressinfo', change, wallet='alice')
    check(bob_info['ismine'] and change_info['ismine'] and change_info['ischange'], '收款或找零地址归属不符')
    print(f"OWNERSHIP bob_receive_script={bob_info['scriptPubKey']} alice_change_script={change_info['scriptPubKey']} alice_ischange={change_info['ischange']}")
    outputs = tx['vout']
    output_total = 0
    for out in outputs:
        script = out['scriptPubKey']
        value_sat = sat(out['value'])
        output_total += value_sat
        print(f"OUTPUT n={out['n']} address={script['address']} value_sat={value_sat} script_hex={script['hex']}")
    check(len(outputs) == 2, '付款交易不是两项输出')
    payment, = [o for o in outputs if o['scriptPubKey']['hex'] == bob_info['scriptPubKey']]
    returned, = [o for o in outputs if o['scriptPubKey']['hex'] == change_info['scriptPubKey']]
    check(sat(payment['value']) == PAY_SAT and sat(returned['value']) == change_sat, '收款或找零金额不匹配')

    fee = prev_sat - output_total
    result, = rpc('testmempoolaccept', [signed['hex']])
    check(result.get('allowed'), f"节点预检拒绝交易：{result.get('reject-reason', '未知原因')}")
    node_fee = sat(result['fees']['base'])
    vsize = tx['vsize']
    check(fee == node_fee == FEE_SAT and result['vsize'] == vsize, '手续费或虚拟大小不符')
    print(f"PREFLIGHT allowed={result['allowed']} input_minus_outputs_sat={fee} node_fee_sat={node_fee} vsize={vsize} rate_sat_vb={Decimal(fee) / vsize:.3f}")
    return signed['hex'], tx['txid'], payment, fee


def wallet_views(rpc, txid, payment_block, tip):
    alice, bob = [rpc('gettransaction', txid, wallet=w) for w in ('alice', 'bob')]
    for receipt in (alice, bob):
        check(receipt['txid'] == txid and receipt.get('blockhash') == payment_block and
              receipt['lastprocessedblock']['hash'] == tip, '付款回执的交易、包含块或观察链尖不匹配')
    check(alice['confirmations'] == bob['confirmations'], '两个钱包的确认数不一致')
    return alice, bob


def order_check(label, received, due, depth):
    if received < due:
        decision = 'HOLD_SHORT'
    elif received > due:
        decision = 'HOLD_OVER'
    elif depth < MIN_CONFIRMATIONS:
        decision = 'WAIT_DEPTH'
    else:
        decision = 'MATCH'
    print(f'ORDER case={label} due_sat={due} received_sat={received} delta_sat={received - due} confirmations={depth} decision={decision}')


def lab(rpc):
    for name in ('alice', 'bob', 'miner'):
        rpc('createwallet', name)
    alice = rpc('getnewaddress', '', 'bech32', wallet='alice')
    bob = rpc('getnewaddress', '', 'bech32', wallet='bob')
    change = rpc('getrawchangeaddress', 'bech32', wallet='alice')
    miner = rpc('getnewaddress', '', 'bech32', wallet='miner')
    print(f'ADDRESSES alice_funding={alice} bob_receive={bob} alice_change={change}')
    outpoint, old, reward_block = mature_reward(rpc, alice, miner)
    before_a = sat(rpc('getbalances', wallet='alice')['mine']['trusted'])
    before_b = sat(rpc('getbalances', wallet='bob')['mine']['trusted'])
    raw_hex, signed_id, payment, fee = sign_payment(rpc, outpoint, old, reward_block, bob, change)
    txid = rpc('sendrawtransaction', raw_hex)
    check(txid == signed_id, '提交的交易与解码结果不是同一笔')
    entry = rpc('getmempoolentry', txid)
    before_conf = rpc('gettransaction', txid, wallet='bob')['confirmations']
    pending = sat(rpc('getbalances', wallet='bob')['mine']['untrusted_pending'])
    print(f"MEMPOOL txid={txid} fee_sat={sat(entry['fees']['base'])} confirmations={before_conf} bob_pending_sat={pending}")
    check(before_conf == 0 and pending == PAY_SAT and sat(entry['fees']['base']) == fee, '内存池收款或费用不匹配')

    blockhash, = rpc('generatetoaddress', 1, miner)
    block = rpc('getblock', blockhash)
    payer, payee = wallet_views(rpc, txid, blockhash, blockhash)
    spent = rpc('gettxout', outpoint['txid'], outpoint['vout'], False) is None
    depth = payee['confirmations']
    print(f"BLOCK height={block['height']} hash={blockhash} includes_tx={txid in block['tx']} confirmations={depth} old_utxo_spent={spent}")
    check(block['height'] == 102 and txid in block['tx'] and depth == 1 and spent, '包含块或旧 UTXO 状态不匹配')
    detail, = [d for d in payee['details'] if d['category'] == 'receive' and d['address'] == bob and d['vout'] == payment['n']]
    received = sat(detail['amount'])
    check(received == sat(payment['value']) == sat(payee['amount']) and sat(payer['amount']) == -received and
          sat(payer['fee']) == -fee, '钱包流水与收款输出或手续费不符')
    print(f"RECEIPT wallet=alice txid={payer['txid']} blockhash={payer['blockhash']} confirmations={payer['confirmations']} amount_sat={sat(payer['amount'])} fee_sat={sat(payer['fee'])}")
    print(f"RECEIPT wallet=bob txid={payee['txid']} blockhash={payee['blockhash']} confirmations={depth} category={detail['category']} vout={detail['vout']} address={detail['address']} amount_sat={received}")
    after_a = sat(rpc('getbalances', wallet='alice')['mine']['trusted'])
    after_b = sat(rpc('getbalances', wallet='bob')['mine']['trusted'])
    print(f'BALANCES alice_before_sat={before_a} alice_after_sat={after_a} bob_before_sat={before_b} bob_after_sat={after_b}')
    debit, credit = before_a - after_a, after_b - before_b
    check(credit == received and debit == credit + fee, '两端余额变化与流水不符')
    order_check('agreed', received, ORDER_DUE_SAT, depth)

    tip, = rpc('generatetoaddress', 1, miner)
    _, payee = wallet_views(rpc, txid, blockhash, tip)
    height, depth = payee['lastprocessedblock']['height'], payee['confirmations']
    check(height == 103 and depth == 2, '同一付款在后续链尖的深度不匹配')
    print(f'DEPTH height={height} confirmations={depth}')
    order_check('agreed', received, ORDER_DUE_SAT, depth)
    order_check('counterfactual', received, ORDER_DUE_SAT + 1, depth)
    return f'PASS bob_credit_sat={credit} alice_debit_sat={debit} difference_sat={debit - credit}'


if __name__ == '__main__':
    if len(sys.argv) != 1:
        sys.exit('本实验不接受参数。')
    try:
        print(run(lab))  # 节点已关闭，临时钱包已清理。
    except KeyboardInterrupt:
        sys.exit('已中断实验。')
    except (OSError, ValueError) as error:
        sys.exit(f'实验失败：{error}')
