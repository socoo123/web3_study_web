"""花费两个原生 SegWit 输出；只连接 regtest.run 启动的一次性节点。"""
import argparse
from hashlib import sha256

from regtest import btc, check, run, sat


WALLET = 'script-desk'
FEE_SAT = 500


def reward(rpc, kind, encoding, expected, core_type):
    address = rpc('getnewaddress', '', encoding, wallet=WALLET)
    info = rpc('validateaddress', address)
    check(info['isvalid'] and info['iswitness'], '没有得到本链上的有效见证地址')
    script = bytes.fromhex(info['scriptPubKey'])
    opcode, length = script[:2]
    version = {0x00: 0, 0x51: 1}.get(opcode)  # 本课只接受 OP_0、OP_1
    program = script[2:]
    check((version, length) == expected and len(program) == length, '输出不符合指定模板')
    check(info['witness_version'] == version and info['witness_program'] == program.hex(),
          '脚本与地址解码结果不一致')
    print(f'ADDRESS kind={kind} address={address} scriptPubKey={script.hex()} '
          f'version={version} program_bytes={length} encoding={encoding}')

    typo = address[:-1] + ('p' if address[-1] == 'q' else 'q')
    valid = rpc('validateaddress', typo)['isvalid']
    check(not valid, '单字符抄写错误未检出')
    print(f'COPY kind={kind} candidate={typo} isvalid={valid}')

    blockhash = rpc('generatetoaddress', 1, address)[0]
    coinbase = rpc('getblock', blockhash, 2)['tx'][0]
    matches = [out for out in coinbase['vout'] if out['scriptPubKey']['hex'] == script.hex()]
    check(len(matches) == 1 and matches[0]['scriptPubKey']['type'] == core_type, '奖励输出不匹配')
    out = matches[0]
    prev = {'txid': coinbase['txid'], 'vout': out['n']}
    value_sat = sat(out['value'])
    print(f"PREV kind={kind} outpoint={prev['txid']}:{prev['vout']} type={core_type} value_sat={value_sat}")
    return prev, value_sat


def wire_id(raw):
    # SHA256d；RPC 用逆字节序显示这 32 字节。
    return sha256(sha256(bytes.fromhex(raw)).digest()).digest()[::-1].hex()


def signed_receipt(rpc, kind, raw, prev, sighash):
    result = rpc('signrawtransactionwithwallet', raw, [], sighash, wallet=WALLET)
    check(result['complete'], '钱包未完成签名')
    signed = result['hex']
    tx = rpc('decoderawtransaction', signed)
    vin, = tx['vin']
    check(vin['txid'] == prev['txid'] and vin['vout'] == prev['vout'] and not vin['scriptSig']['hex'],
          '输入没有指向指定的原生见证输出')
    stack = [bytes.fromhex(item) for item in vin['txinwitness']]
    if kind == 'P2WPKH':
        sig, pubkey = stack
        check(sig[0] == 0x30 and sig[-1] == 1 and len(pubkey) == 33 and pubkey[0] in (2, 3),
              '不是本钱包生成的 ECDSA ALL 签名与压缩公钥')
    else:
        sig, = stack  # 本钱包的 key path，没有 annex
        check(len(sig) == 64 if sighash == 'DEFAULT' else len(sig) == 65 and sig[-1] == 1,
              'Taproot key path 签名长度或类型不符合预期')
    print(f"WITNESS kind={kind} sighash={sighash} stack_bytes={','.join(str(len(i)) for i in stack)} "
          f"items={','.join(vin['txinwitness'])}")

    # 这两种 native 输入签名前后 scriptSig 均为空，原始未签交易正是去见证序列化。
    base, total = len(raw) // 2, len(signed) // 2
    weight = 3 * base + total
    check(tx['txid'] == wire_id(raw) and tx['hash'] == wire_id(signed) and tx['txid'] != tx['hash'],
          '重算的交易标识与节点不一致')
    check(tx['size'] == total and tx['weight'] == weight and tx['vsize'] == (weight + 3) // 4,
          '交易大小与权重不一致')
    verdict = rpc('testmempoolaccept', [signed])[0]
    check(verdict.get('allowed'), f'本地内存池预检未通过：{verdict}')
    check(verdict['wtxid'] == tx['hash'] and sat(verdict['fees']['base']) == FEE_SAT, '预检费用或见证标识不符')
    print(f"RECEIPT kind={kind} sighash={sighash} txid={tx['txid']} wtxid={tx['hash']} "
          f"base_B={base} total_B={total} weight_WU={weight} vsize_vB={tx['vsize']} "
          f"fee_sat={FEE_SAT} allowed={verdict['allowed']}")
    return signed, tx['txid'], tx['hash']


def lab(rpc, explicit_all):
    rpc('createwallet', WALLET)
    wpkh = reward(rpc, 'P2WPKH', 'bech32', (0, 20), 'witness_v0_keyhash')
    tr = reward(rpc, 'P2TR', 'bech32m', (1, 32), 'witness_v1_taproot')
    miner = rpc('getnewaddress', '', 'bech32', wallet=WALLET)
    rpc('generatetoaddress', 100, miner)  # 前两块的奖励均已成熟
    destination = rpc('getnewaddress', '', 'bech32', wallet=WALLET)
    submitted = {}
    for kind, (prev, value_sat) in [('P2WPKH', wpkh), ('P2TR', tr)]:
        raw = rpc('createrawtransaction', [prev], [{destination: btc(value_sat - FEE_SAT)}])
        signed, txid, wtxid = signed_receipt(rpc, kind, raw, prev, 'DEFAULT' if kind == 'P2TR' else 'ALL')
        if kind == 'P2TR' and explicit_all:
            original_txid, original_wtxid = txid, wtxid
            signed, txid, wtxid = signed_receipt(rpc, kind, raw, prev, 'ALL')
            check(txid == original_txid and wtxid != original_wtxid, '仅改变见证后的交易标识不符')
            print('COMPARE same_base_txid=True same_wtxid=False submit=ALL')
        check(rpc('sendrawtransaction', signed) == txid, '提交的交易标识不符')
        submitted[txid] = wtxid

    blockhash = rpc('generatetoaddress', 1, miner)[0]
    block = rpc('getblock', blockhash, 2)
    included = {}
    for tx in block['tx'][1:]:
        vin, = tx['vin']
        included[tx['txid']] = tx['hash']
        print(f"IN_BLOCK prev={vin['txid']}:{vin['vout']} txid={tx['txid']} wtxid={tx['hash']}")
    check(included == submitted, '块内两笔花费的 txid/wtxid 和提交记录不一致')
    print(f"BLOCK height={block['height']} blockhash={blockhash} spends={len(included)} id_pairs_match=True")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--explicit-all', action='store_true', help='同一笔 Taproot 草稿另签 ALL；只提交 ALL')
    args = parser.parse_args()
    run(lambda rpc: lab(rpc, args.explicit_all))
