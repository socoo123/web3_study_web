"""An operator-controlled signer front end for ONLY this disposable loopback Anvil."""
import json
from pathlib import Path
import re
import secrets
import sys
from threading import Lock

from common import DESK, Handler, LABS, button, fields, serve, text
sys.path[:0] = [str(LABS / 'm04'), str(LABS)]
from handoff import rpc, selector, verify
from anvil_lab import send_mined

WORK = Path(sys.argv[1])
ORDER, QUOTE = sys.argv[2:4]
MANIFEST = json.loads((WORK / 'release/manifest.json').read_text())
STATES = ('待锁款', '已锁款，尚未结算', '已结算，受益人有应领', '已退款')
ACTIONS = {'lock': '锁款', 'settle': '结算'}
mutex = Lock()
pending = None  # (one-time token, method, exact transaction, reviewed head hash)


def prepare(method, units, live):
    expected_state = 0 if method == 'lock' else 1
    if live['state'] != expected_state:
        raise ValueError('合约状态已改变；本步不能发送。')
    if method == 'lock' and (not re.fullmatch(r'[1-9][0-9]{0,18}', units) or int(units) > 10**18):
        raise ValueError('锁入金额必须是 1 到 10^18 的十进制整数 wei，不接受小数或科学计数法。')
    tx = {'from': live['payer'], 'to': live['contractAddress'], 'data': selector(rpc, method + '()'),
          'value': hex(int(units) if method == 'lock' else 0), 'gasPrice': rpc('eth_gasPrice'),
          'nonce': rpc('eth_getTransactionCount', live['payer'], 'pending')}
    # A fixed, visible ceiling. Anvil estimates before the user approves the exact transaction.
    estimate = int(rpc('eth_estimateGas', tx), 16)
    tx['gas'] = hex((estimate * 12 + 9) // 10)
    return tx


class Payer(Handler):
    def get(self):
        if self.path not in ('/', '/rejected', '/mined', '/sent-lock', '/sent-settle'):
            return self.send_error(404)
        live = verify(MANIFEST)
        state = live['state']
        banner = ''
        if self.path == '/rejected':
            banner = '<p class="notice">已拒签。本次预览已作废，没有调用发送交易接口。</p>'
        elif self.path == '/mined':
            banner = '<p class="notice">本地空块已生成。返回对账台补扫；这一步不会替你核销。</p>'
        elif self.path.startswith('/sent-'):
            method = self.path[6:]
            receipt = json.loads((WORK / f'payer-{method}.json').read_text())
            banner = '<p class="notice">已取得本次成功回执。</p>' + fields(('交易哈希', receipt['transactionHash']), ('回执块高', int(receipt['blockNumber'], 16)))
        summary = fields(('订单号', ORDER), ('商户预先约定', QUOTE + ' wei'), ('链号 / 读到的块高', f'31337 / {live["readBlockNumber"]}'),
                         ('付款人', live['payer']), ('托管合约', live['contractAddress']), ('受益人', live['payee']),
                         ('锁款 / 结算截止时间（Unix 秒）', live['deadline']),
                         ('受益人当前应领', live['payeeCreditWei'] + ' wei'))
        if state == 0:
            controls = f'''<form method="post" action="/preview-lock"><label for="wei">实际锁入金额（wei）</label>
<input id="wei" name="wei" type="text" inputmode="numeric" required maxlength="19" value="{text(QUOTE)}">
<button>预览锁款</button></form>'''
        elif state == 1:
            controls = '<p>结算将把这笔锁款登记给清单中的受益人；本次不再附款。</p>' + button('/preview-settle', '预览结算')
        else:
            controls = '<p>本部署不接受第二笔锁款。领取到钱包是另一项业务，本台不提供领取入口。</p>'
        self.document('付款人确认台', banner + f'<p>仅供自有 Anvil 临时账户。付款由你发起，对账台不能代签。</p><h2>{STATES[state]}</h2>' + summary + controls +
                      f'<section><h2>确认数实验</h2><p>这是本地节点控制，不是付款操作。每次只增加一个空块。</p>{button("/mine", "推进一个本地空块")}<p><a href="{DESK}/">返回收款对账台</a></p></section>')

    def post(self, form):
        global pending
        with mutex:
            if self.path in ('/preview-lock', '/preview-settle'):
                method = self.path[9:]
                live = verify(MANIFEST)
                tx = prepare(method, form.get('wei', ''), live)
                token = secrets.token_urlsafe(24)
                pending = (token, method, tx, live['readBlockHash'])
                label = ACTIONS[method]
                units = str(int(tx['value'], 16))
                summary = fields(('订单 / 链', f'{ORDER} / 31337'), ('发起人', tx['from']), ('目标合约', tx['to']), ('受益人', live['payee']),
                                 ('调用方法 / calldata', f'{method}() / {tx["data"]}'), ('交易附款', units + ' wei'),
                                 ('商户约定', QUOTE + ' wei'), ('当前托管余额', live['escrowBalanceWei'] + ' wei'),
                                 ('锁款 / 结算截止时间（Unix 秒）', live['deadline']),
                                 ('nonce', int(tx['nonce'], 16)), ('费用上界（gas 上限 × gas 单价）', f'{int(tx["gas"], 16)} × {int(tx["gasPrice"], 16)} = {int(tx["gas"], 16) * int(tx["gasPrice"], 16)} wei'))
                warning = '<p class="notice">金额与商户约定不符；继续可演练成功交易为什么仍会被拒单。</p>' if method == 'lock' and units != QUOTE else ''
                self.document(f'复核{label}请求', '<p>尚未广播。确认只授权下列一笔交易；拒签会销毁本次请求。</p>' + warning + summary +
                              '<div class="actions">' + button('/reject', '拒签，不发送', {'token': token}) + button('/confirm', '确认发送' + label, {'token': token}) + '</div>')
                return
            if self.path == '/mine':
                verify(MANIFEST)
                pending = None
                rpc('evm_mine')
                return self.redirect('/mined')
            if self.path not in ('/reject', '/confirm'):
                return self.send_error(404)
            if pending is None or not secrets.compare_digest(pending[0], form.get('token', '')):
                raise ValueError('请求已作废或已使用；先查当前状态，不要重复提交。')
            _, method, tx, head = pending
            pending = None
            if self.path == '/reject':
                return self.redirect('/rejected')
            live = verify(MANIFEST)
            if live['readBlockHash'] != head or rpc('eth_getTransactionCount', tx['from'], 'pending') != tx['nonce']:
                raise ValueError('链头或账户 nonce 已变，请重新预览。未广播。')
            receipt = send_mined(rpc, tx)  # A timeout is NOT permission to send a second time.
            (WORK / f'payer-{method}.json').write_text(json.dumps(receipt, indent=2) + '\n')
            self.redirect('/sent-' + method)


if __name__ == '__main__':
    verify(MANIFEST)
    serve(18039, Payer)
