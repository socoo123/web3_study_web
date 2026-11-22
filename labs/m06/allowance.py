"""Build a read-only receipt for two local LabToken allowances (no wallet or web server)."""
import argparse
from html import escape
import json
from pathlib import Path
import re
import tempfile

from chain import anvil, call, check_event, deploy, send, units


# All input/output conversions are base 10. Reject excess places instead of rounding.
def payment(text, decimals):
    whole, dot, fraction = text.partition('.')
    if (not re.fullmatch(r'[0-9]+', whole) or (dot and not re.fullmatch(r'[0-9]+', fraction))
            or len(fraction) > decimals):
        raise ValueError(f'需要非负十进制金额，最多 {decimals} 位小数：{text}')
    raw = int(whole + fraction.ljust(decimals, '0'))
    if not 0 < raw <= 25 * 10**(decimals - 1):
        raise ValueError('本次额度内扣款必须大于 0 且不超过 2.5 枚')
    return raw


def settle(rpc, owner, spender, symbol, expected_decimals, debit):
    supply = 10 * 10**expected_decimals
    token = deploy(rpc, owner, 'LabToken', 'constructor(string,uint8,uint256)',
                   symbol, expected_decimals, supply)
    decimals = call(rpc, token, 'decimals()')
    if decimals != expected_decimals:
        raise RuntimeError('部署读回的小数位不符，不授权')
    cap = 25 * 10**(decimals - 1)
    balance_after = (supply - debit, debit, cap - debit)

    def state(block, expected):
        actual = (call(rpc, token, 'balanceOf(address)', owner, block=block),
                  call(rpc, token, 'balanceOf(address)', spender, block=block),
                  call(rpc, token, 'allowance(address,address)', owner, spender, block=block))
        if actual != expected:
            raise RuntimeError(f'{symbol}@{block} 余额/额度不符：{actual} != {expected}')
        return {key: str(n) for key, n in zip(('ownerRaw', 'recipientRaw', 'remainingRaw'), actual)}

    initial_block = rpc('eth_getBlockByNumber', 'latest', False)
    initial = state(initial_block['number'], (supply, 0, 0))
    asset = {'symbol': symbol, 'token': token, 'decimals': decimals, 'capRaw': str(cap),
             'initial': {**initial, 'blockNumber': initial_block['number'], 'blockHash': initial_block['hash']},
             'steps': {}}
    print(f'{symbol} token={token} decimals={decimals} cap={units(cap, decimals)}')
    # Each tuple specifies the ACTUAL msg.sender, method and args, not just a desired event.
    for name, sender, sig, args, event, expected in (
        ('approve', owner, 'approve(address,uint256)', (spender, cap), 'Approval', (supply, 0, cap)),
        ('within', spender, 'transferFrom(address,address,uint256)', (owner, spender, debit), 'Transfer', balance_after),
        ('over', spender, 'transferFrom(address,address,uint256)', (owner, spender, cap - debit + 1), None, balance_after),
    ):
        receipt = send(rpc, sender, token, sig, *args, success=event is not None)
        if receipt['from'].lower() != sender.lower() or receipt['to'].lower() != token.lower():
            raise RuntimeError('交易调用者或目标合约不符')
        if event:
            if len(receipt['logs']) != 1:
                raise RuntimeError('本课代币的这次调用应只有一条日志')
            check_event(receipt['logs'], token, f'{event}(address,address,uint256)', [owner, spender], [args[-1]])
        elif receipt['logs'] or int(receipt['gasUsed'], 16) <= 0:
            raise RuntimeError('应取得已耗 gas 且未留下日志的失败回执')
        after = state(receipt['blockNumber'], expected)
        asset['steps'][name] = {'inputRaw': str(args[-1]), 'event': event, 'after': after, 'receipt': receipt}
        print(f"  {name} tx={receipt['transactionHash']} status={receipt['status']} "
              f"recipient={units(int(after['recipientRaw']), decimals)} "
              f"remaining={units(int(after['remainingRaw']), decimals)}")
    return asset


def voucher(report):
    parts = ['''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>第 22 课 · 本次授权凭单</title>
<style>:root{color-scheme:light dark}body{max-width:54rem;margin:2rem auto;padding:0 1rem;font:1rem/1.7 system-ui,sans-serif;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}section{border-top:1px solid;padding-block:1rem}dl{margin:0}dd{margin:0 0 .6rem}summary{cursor:pointer}li+li{margin-top:1rem}</style>
<main><p>本地教学链 · 实验归档</p><h1>本次授权凭单</h1>
<p>这是回执所在块的记录，不是实时余额；此页不能签名，也不连接钱包。</p>''',
             f'<dl><dt>Chain ID</dt><dd>{report["chainId"]}</dd>',
             f'<dt>Owner（两种币的持有人）</dt><dd>{escape(report["owner"])}</dd>',
             f'<dt>Spender（获准扣款，本例也收款）</dt><dd>{escape(report["spender"])}</dd></dl>']
    labels = {'approve': '设定上限', 'within': '额度内扣款', 'over': '比剩余额度多扣 1 个最小单位'}
    for asset in report['assets']:
        symbol = escape(asset['symbol'])

        def display(raw):
            return f'{units(int(raw), asset["decimals"])} {symbol}（{raw} 最小单位）'

        parts += [f'<section><h2>{symbol}</h2><dl><dt>资产合约</dt><dd>{escape(asset["token"])}</dd>',
                  f'<dt>小数位</dt><dd>{asset["decimals"]}</dd><dt>授权上限</dt><dd>{display(asset["capRaw"])}</dd></dl><ol>']
        for name, step in asset['steps'].items():
            r, after = step['receipt'], step['after']
            result = '成功' if int(r['status'], 16) == 1 else '回滚'
            parts += [f'<li><strong>{labels[name]}：{result}</strong> · {display(step["inputRaw"])}',
                      f'<br>持有人余额 {display(after["ownerRaw"])}；收款人余额 {display(after["recipientRaw"])}；剩余额度 {display(after["remainingRaw"])}。',
                      f'<details><summary>查看交易和区块凭证</summary><dl><dt>交易哈希</dt><dd>{escape(r["transactionHash"])}</dd>',
                      f'<dt>块 {int(r["blockNumber"], 16)} 的哈希</dt><dd>{escape(r["blockHash"])}</dd>',
                      f'<dt>执行状态 / 事件</dt><dd>{escape(r["status"])} / {step["event"] or "没有日志"}</dd></dl></details></li>']
        parts.append('</ol></section>')
    parts.append('<a href="evidence.json">查看原始回执及逐块整数读数（JSON）</a></main></html>')
    return '\n'.join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, help='新目录；省略则自动创建临时归档目录')
    parser.add_argument('--spend6', default='1.234567', help='LAB6 扣款额（枚）')
    parser.add_argument('--spend18', default='1.234567000000000001', help='LAB18 扣款额（枚）')
    parser.add_argument('--hold', action='store_true', help='保留本轮节点供按哈希查单，回车关闭')
    args = parser.parse_args()
    try:
        debits = (payment(args.spend6, 6), payment(args.spend18, 18))
    except ValueError as exc:
        parser.error(str(exc))
    if args.out is None:
        out = Path(tempfile.mkdtemp(prefix='allowance-'))
    else:
        out = args.out.resolve()
        out.mkdir(parents=True, exist_ok=False)  # Never overwrite a previous receipt archive.
    with anvil(18622) as rpc:
        owner, spender = rpc('eth_accounts')
        chain_id = int(rpc('eth_chainId'), 16)
        print(f'chainId={chain_id} owner={owner} spender={spender} (also recipient)')
        assets = [settle(rpc, owner, spender, f'LAB{d}', d, debit) for d, debit in zip((6, 18), debits)]
        report = {'chainId': chain_id, 'owner': owner, 'spender': spender, 'assets': assets}
        (out / 'evidence.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        (out / 'voucher.html').write_text(voucher(report), encoding='utf-8')
        print(f'ARCHIVE={out}\nVOUCHER={(out / "voucher.html").as_uri()}', flush=True)
        if args.hold:
            input('保留 127.0.0.1:18622 供只读查单；回车关闭此轮节点。\n')


if __name__ == '__main__':
    main()
