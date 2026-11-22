"""第 08 课：仅对本次临时 regtest 的 P2WPKH 工单作签名前核对。"""
import argparse
import sys
from dataclasses import dataclass
from decimal import Decimal

from regtest import btc, check, run, sat


@dataclass(frozen=True)
class Invoice:
    address: str
    script: str
    amount: int
    max_fee: int = 800       # sat
    max_rate: int = 3        # sat/vB


class Refused(ValueError):
    """本工单的签名前策略拒绝；节点故障不归入此类。"""


def require(ok, message):
    if not ok:
        raise Refused(message)


def setup_wallets(rpc):
    for name in ('signer', 'merchant', 'miner'):
        rpc('createwallet', name)
    rpc('createwallet', 'watch', True, True)  # disable_private_keys, blank
    check(not rpc('getwalletinfo', wallet='watch')['private_keys_enabled']
          and rpc('getwalletinfo', wallet='signer')['private_keys_enabled'], '钱包权限不符')
    requests = []
    branches = {}
    for d in rpc('listdescriptors', False, wallet='signer')['descriptors']:
        if d['active'] and d['desc'].startswith('wpkh('):
            info = rpc('getdescriptorinfo', d['desc'])
            check(info['isrange'] and not info['hasprivatekeys'], '只允许公开的范围描述符')
            branches[d['internal']] = d['desc']
            requests.append({'desc': d['desc'], 'active': True, 'internal': d['internal'],
                             'range': [0, 9], 'next_index': 0, 'timestamp': 'now'})
    check(set(branches) == {False, True} and len(requests) == 2, '需要收款与找零两条分支')
    imported = rpc('importdescriptors', requests, wallet='watch')
    check(len(imported) == 2 and all(r['success'] for r in imported), '观察钱包导入失败')
    print('ROLES watch_private_keys=false signer_private_keys=true public_branches=external,internal')
    return branches


def fund(rpc):
    miner = rpc('getnewaddress', '', 'bech32', wallet='miner')
    rpc('generatetoaddress', 101, miner)
    amounts = {rpc('getnewaddress', '', 'bech32', wallet='watch'): btc(n) for n in (70_000, 30_000)}
    funding_txid = rpc('sendmany', '', amounts, 1, '', [], True, None, 'unset', 2, wallet='miner')
    rpc('generatetoaddress', 1, miner)
    coins = [c for c in rpc('listunspent', wallet='watch') if c['txid'] == funding_txid]
    check(sorted(sat(c['amount']) for c in coins) == [30_000, 70_000], '入金未产生两笔约定的 UTXO')
    return miner, [{'txid': c['txid'], 'vout': c['vout']} for c in coins]


def output_pair(output):
    return output['scriptPubKey']['hex'], sat(output['value'])


def tx_fields(tx):
    """允许补见证，不允许把相同的总额重新分配给别的脚本或调换输入。"""
    return (tx['version'], tx['locktime'],
            [(i['txid'], i['vout'], i['sequence']) for i in tx['vin']],
            [output_pair(o) for o in tx['vout']])


def rate_text(fee, vsize):
    return f'{Decimal(fee) / vsize:.4f}'  # 仅供显示；判断上限不用舍入


def review(rpc, psbt, invoice, branches, approved_inputs):
    decoded = rpc('decodepsbt', psbt)
    tx = decoded['tx']
    refs = [(i['txid'], i['vout']) for i in tx['vin']]
    require(len(refs) == len(set(refs)) and set(refs) == approved_inputs, '输入不等于工单指定的前序输出')
    total = 0
    for (txid, n), data in zip(refs, decoded['inputs'], strict=True):
        live = rpc('gettxout', txid, n, True)
        require(live and live['confirmations'] >= 1, f'前序未确认或已花费：{txid}:{n}')
        script, amount = output_pair(live)
        owner = rpc('getaddressinfo', live['scriptPubKey']['address'], wallet='signer')
        require(owner['ismine'] and owner.get('parent_desc') == branches[False], '前序不在签名钱包的入金分支')
        require(data.get('sighash', 'ALL') == 'ALL', '不接受本工单之外的签名范围')
        # 补全器可能给整笔前序交易，也可能给单个见证前序；若两者都有，分别核对。
        prev = data.get('non_witness_utxo')
        witness = data.get('witness_utxo')
        require(prev or witness, 'PSBT 缺少前序数据')
        if prev:
            require(prev['txid'] == txid and n < len(prev['vout']) and
                    output_pair(prev['vout'][n]) == (script, amount), '整笔前序与本地 UTXO 不符')
        if witness:
            require((witness['scriptPubKey']['hex'], sat(witness['amount'])) == (script, amount),
                    'PSBT 的见证前序与本地 UTXO 不符')
        print(f'INPUT prev={txid}:{n} sat={amount} script={script} confirmations={live["confirmations"]}')
        total += amount

    require(len(tx['vout']) == 2, '本工单只准一个收款输出和一个找零输出')
    payments = [o for o in tx['vout'] if o['scriptPubKey']['hex'] == invoice.script]
    require(len(payments) == 1, '收款脚本与独立订单不符')
    payment = payments[0]
    actual = sat(payment['value'])
    require(actual == invoice.amount, f'收款金额不符 expected_sat={invoice.amount} proposed_sat={actual}')
    change = next(o for o in tx['vout'] if o['n'] != payment['n'])
    change_address = change['scriptPubKey'].get('address')
    require(change_address, '找零不是本工单支持的地址脚本')
    owner = rpc('getaddressinfo', change_address, wallet='signer')
    require(owner['ismine'] and owner['ischange'] and owner.get('parent_desc') == branches[True]
            and owner['scriptPubKey'] == change['scriptPubKey']['hex'], '找零未匹配签名钱包的内部描述符')
    change_sat = sat(change['value'])
    fee = total - actual - change_sat
    print(f'OUTPUT merchant_vout={payment["n"]} merchant_sat={actual} script={invoice.script}')
    print(f'CHANGE vout={change["n"]} sat={change_sat} script={owner["scriptPubKey"]} signer_internal=true')
    require(0 < fee <= invoice.max_fee, f'绝对费用越界 fee_sat={fee} cap_sat={invoice.max_fee}')
    analysis = rpc('analyzepsbt', psbt)
    vsize = analysis.get('estimated_vsize', 0)
    require(vsize > 0 and 'fee' in analysis and sat(analysis['fee']) == fee, '未能核实估算大小或费用')
    require(fee <= invoice.max_rate * vsize,
            f'预估费率越界 fee_sat={fee} estimated_vsize={vsize} cap_sat_vb={invoice.max_rate}')
    print(f'PREVIEW fee_sat={fee} estimated_vsize={vsize} estimated_sat_vb={rate_text(fee, vsize)}')
    return tx_fields(tx), total, payment['n']


def lab(rpc, args):
    branches = setup_wallets(rpc)
    miner, inputs = fund(rpc)
    # 独立工单来自商户收款端，不从待签 PSBT 的输出反推预期值。
    address = rpc('getnewaddress', '', 'bech32', wallet='merchant')
    invoice = Invoice(address, rpc('getaddressinfo', address, wallet='merchant')['scriptPubKey'], args.order_sat)
    print(f'ORDER chain=regtest address={address} script={invoice.script} sat={invoice.amount} '
          f'max_fee_sat={invoice.max_fee} max_sat_vb={invoice.max_rate}')
    change = rpc('getrawchangeaddress', 'bech32', wallet='watch')
    offered = invoice.amount - int(args.short_pay)
    outputs = [{invoice.address: btc(offered)}, {change: btc(100_000 - offered - args.fee_sat)}]
    if args.change_first:
        outputs.reverse()
    draft = rpc('createpsbt', inputs, outputs)
    updated = rpc('walletprocesspsbt', draft, False, 'ALL', True, False, wallet='watch')['psbt']
    try:
        fields, input_sat, merchant_vout = review(rpc, updated, invoice, branches,
                                                   {(i['txid'], i['vout']) for i in inputs})
    except Refused as e:
        check(not rpc('getrawmempool'), '拒绝路径不应有待确认付款')
        return 3, f'STOP {e} payment_sign_requested=false broadcast=false mempool=0'

    attempted = rpc('walletprocesspsbt', updated, True, 'ALL', True, False, wallet='watch')
    check(not attempted['complete'] and not rpc('finalizepsbt', attempted['psbt'])['complete'],
          '观察端不应得到完整交易')
    print('WATCH sign_requested=true complete=false can_extract=false')
    signed = rpc('walletprocesspsbt', updated, True, 'ALL', True, False, wallet='signer')['psbt']
    sig_inputs = rpc('decodepsbt', signed)['inputs']
    check(all(i.get('partial_signatures') and not i.get('final_scriptwitness') for i in sig_inputs),
          '每个输入应有签名，但尚未最终化')
    finished = rpc('finalizepsbt', signed)
    check(finished['complete'], '最终化仍缺签名')
    final = rpc('decoderawtransaction', finished['hex'])
    check(tx_fields(final) == fields and all(i.get('txinwitness') for i in final['vin']), '最终交易偏离已审意图或缺见证')
    fee = input_sat - sum(sat(o['value']) for o in final['vout'])
    check(0 < fee <= invoice.max_fee and fee <= invoice.max_rate * final['vsize'], '实付费率或费用越界，禁止广播')
    print(f'FINAL matched=true signed_inputs={len(sig_inputs)} fee_sat={fee} vsize={final["vsize"]} '
          f'actual_sat_vb={rate_text(fee, final["vsize"])}')
    txid = rpc('sendrawtransaction', finished['hex'])
    check(txid == final['txid'] and txid in rpc('getrawmempool'), '本地节点未接收最终交易')
    print(f'MEMPOOL txid={txid} confirmations=0')
    blockhash = rpc('generatetoaddress', 1, miner)[0]
    block = rpc('getblock', blockhash)
    payer = rpc('gettransaction', txid, wallet='signer')
    receiver = rpc('gettransaction', txid, wallet='merchant')
    check(txid in block['tx'] and blockhash == payer['blockhash'] == receiver['blockhash']
          and block['height'] == payer['blockheight'] == receiver['blockheight']
          and payer['confirmations'] == receiver['confirmations'] == 1, '区块与两端回执不一致')
    check(sat(receiver['amount']) == invoice.amount and any(
          d['category'] == 'receive' and d['vout'] == merchant_vout and d.get('address') == invoice.address
          and sat(d['amount']) == invoice.amount for d in receiver['details']), '商户流水未匹配工单')
    print(f'BLOCK height={block["height"]} hash={blockhash} includes={txid} payer_conf=1 merchant_conf=1')
    return 0, f'PASS receipt={txid}:{merchant_vout} received_sat={invoice.amount} fee_sat={fee}'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--order-sat', type=int, default=60_000, help='独立工单金额，1000..98000 sat')
    p.add_argument('--fee-sat', type=int, default=420, help='拟付绝对费用，1..1000 sat；策略上限仍为 800')
    p.add_argument('--short-pay', action='store_true', help='草案少付 1 sat 并归入找零，工单不变')
    p.add_argument('--change-first', action='store_true', help='把找零排在 vout=0，订单不变')
    args = p.parse_args()
    if not (1000 <= args.order_sat <= 98_000 and 1 <= args.fee_sat <= 1000):
        p.error('工单金额或拟付费用超出实验输入范围')
    code, message = run(lambda rpc: lab(rpc, args))
    print(message)
    return code


if __name__ == '__main__':
    sys.exit(main())
