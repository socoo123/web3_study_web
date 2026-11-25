"""Read from the M05 order API; only M05 decides whether a callback may book."""
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from threading import Lock

from common import Handler, HOST, LABS, PAYER, button, fields, serve, text
sys.path.insert(0, str(LABS / 'm04'))
from handoff import rpc

ORDER = sys.argv[1]
MANIFEST = json.loads(Path(os.environ['M05_MANIFEST']).read_text())
M05 = LABS / 'm05'
scan_lock = Lock()
last_run = None  # Display-only transcript of the latest scan; never a cached order decision.
REASONS = {
    'WAIT_SETTLED': '还没有本轮规范支的结算事件。', 'HOLD_LAG': '索引尚未跟到当前链头，先补扫。',
    'HOLD_AMOUNT': '结算与订单的整数金额不一致，不能核销。', 'HOLD_DEPTH': '金额已对平，但本地确认数还不够。',
    'READY_TO_BOOK': '证据已对平。这是只读查询，还没有入账。', 'BOOKED_AT_HEAD': '这份结算支持本单的托管应领，不代表钱包到账。',
    'HOLD_REORG': '游标与节点不是同一页账，暂停并核对分支。', 'HOLD_ORPHAN': '原流水的链证据已变，禁止再次记账或交付。',
    'HOLD_RELEASE': '部署锚点不匹配。', 'HOLD_PAYEE': '受益人与清单不符。', 'HOLD_ASSET': '资产不符，不可比较面值。',
    'HOLD_AMBIGUOUS': '出现多条候选结算，不能猜一条。', 'HOLD_NO_CURSOR': '尚无可信游标。', 'RETIRED': '试单已退役。',
}
# Temporary waiting for confirmations or catch-up is not a permanent financial discrepancy.
WAITING = {'WAIT_SETTLED', 'HOLD_DEPTH', 'HOLD_LAG', 'READY_TO_BOOK', 'BOOKED_AT_HEAD'}


def order(callback=False):
    api = HTTPConnection(HOST, 18020, timeout=12)
    try:
        route = '/orders/' + ORDER
        if callback:
            api.request('POST', route + '/callbacks/desk-38', '{}', {'Content-Type': 'application/json'})
        else:
            api.request('GET', route)
        response = api.getresponse()
        if response.status != 200:
            raise OSError(f'订单服务 HTTP {response.status}；无法判定当前链证据。')
        report = json.load(response)
        i = report['intent']
        release = i['release']
        if (i['id'] != ORDER or release['chainId'] != MANIFEST['chainId'] or
                release['deployHash'] != MANIFEST['deploymentBlockHash'].lower() or
                release['contractAddress'] != MANIFEST['contractAddress'].lower()):
            raise OSError('订单 API 不属于本次部署；停止显示或放行。')
        return report
    finally:
        api.close()


def counts():
    query = '''\\pset tuples_only on
\\pset format unaligned
SELECT json_build_object('bookings',(SELECT count(*) FROM order_booking),
                         'outbox',(SELECT count(*) FROM order_outbox),
                         'hints',(SELECT count(*) FROM callback_hint));'''
    output = subprocess.check_output(['bash', M05 / 'db.sh', 'sql'], input=query, text=True, timeout=15)
    return json.loads(output.strip().splitlines()[-1])


def locator(e):
    return f'/receipt/{e["blockHash"]}/{e["txHash"]}/{e["logIndex"]}'


def evidence(e):
    if not e:
        return '<p>尚无可展示的结算凭据；不能把空值记成零。</p>'
    return fields(('事件 / 金额', f'{e["kind"]} / {e["amountWei"]} wei'), ('合约', e['address']), ('受益人', e['actor']),
                  ('块高 / 日志索引', f'{e["height"]} / {e["logIndex"]}'), ('块哈希', e['blockHash']), ('交易哈希', e['txHash'])) + f'<p><a href="{text(locator(e))}">打开这笔结算的原始回执 JSON</a></p>'


class Desk(Handler):
    def show(self, r, run=None):
        i, d, n = r['intent'], r['decision'], counts()
        summary = fields(('商户单号', i['id']), ('约定资产 / 应收', f'{i["asset"]} / {i["expectedUnits"]} wei'),
                         ('规范结算（wei）', (r.get('observed') or {}).get('amountWei')), ('应收 − 实见（wei）', r.get('differenceWei')),
                         ('头高 / 游标', f'{r.get("headHeight", "—")} / {r.get("cursorHeight", "—")}'),
                         ('当前确认 / 要求', f'{r.get("confirmations", "—")} / {i["minDepth"]}'),
                         ('本轮专库 · 流水 / outbox', f'{n["bookings"]} / {n["outbox"]}'))
        observed = r.get('observed')
        old = r.get('bookingEvidence')
        history = '<h3>历史入账证据（不等于当前放行）</h3>' + evidence(old) if old and old != observed else ''
        audit = ''
        if run:
            scan, new_hint, decision = run
            audit = f'<section><h2>本次后端执行</h2><p>最近一次扫描与回调：{text(decision)}；提示键 desk-38：{"首次记录" if new_hint else "已存在，重新核对"}。上方订单为此刻重新读取的结果。</p><pre>{text(scan)}</pre></section>'
        self.document('收款对账台', '<p class="state"><strong>' + text(d) + '</strong><br>' + text(REASONS.get(d, '未识别的判定，转人工处理。')) + '</p>' +
                      summary + f'<p><a href="{PAYER}/">前往独立付款人确认台</a></p><div class="actions">' +
                      button('/sync', '补扫并核对') + button('/replay', '重放本轮并核对') + '</div><nav><a href="/">仅刷新订单</a><a href="/queue">打开人工核对队列</a></nav>' +
                      '<section><h2>从订单回到回执</h2>' + evidence(observed) + history + '<p><a href="/order.json">当前订单 JSON</a>　<a href="/counts.json">本轮专库计数 JSON</a></p></section>' + audit)

    def get(self):
        if self.path == '/counts.json':
            return self.json(counts())
        if self.path not in ('/', '/result', '/queue', '/order.json') and not self.path.startswith('/receipt/'):
            return self.send_error(404)
        r = order()
        if self.path in ('/', '/result'):
            return self.show(r, last_run if self.path == '/result' else None)
        if self.path == '/order.json':
            return self.json(r)
        if self.path == '/queue':
            d = r['decision']
            if d in WAITING:
                body = f'<p>当前 0 张差错单。本单为 {text(d)}；等待结算、等待深度或积压本身不是金额差错。</p>'
            else:
                i, e = r['intent'], r.get('observed')
                n = counts()
                body = f'<p class="state"><strong>1 张待复核 · {text(i["id"])}</strong><br>{text(d)}：{text(REASONS.get(d, "未识别状态"))}</p>' + fields(
                    ('订单应收', i['expectedUnits'] + ' wei'), ('链上结算（wei）', (e or {}).get('amountWei')), ('应收 − 实见（wei）', r.get('differenceWei')),
                    ('流水 / outbox', f'{n["bookings"]} / {n["outbox"]}')) + evidence(e or r.get('bookingEvidence')) + '<p>留存本单与回执，复核后联系发起人；此处不提供强制入账、改价或退款按钮。</p>'
            return self.document('人工核对队列', body + '<p>范围：本次部署的订单，按最新可核证据筛选，不是工单历史。</p><a href="/">返回订单</a>')
        for e in (r.get('observed'), r.get('bookingEvidence')):
            if e and self.path == locator(e):
                raw = rpc('eth_getTransactionReceipt', e['txHash'])
                if not raw or raw['transactionHash'] != e['txHash'] or raw['blockHash'] != e['blockHash'] or not any(
                        int(log['logIndex'], 16) == e['logIndex'] and log['address'].lower() == e['address'] for log in raw['logs']):
                    raise ValueError('节点现在无法提供与订单证据匹配的原回执；不要拿别的块或日志顶替。')
                return self.json(raw)
        self.send_error(404, 'Not an evidence locator for the current order')

    def post(self, form):
        if self.path not in ('/sync', '/replay') or form:
            return self.send_error(404)
        with scan_lock:
            # Verify the local order service belongs to this release before asking it to write.
            order()
            args = ['Recover'] if self.path == '/sync' else ['Scan', str(MANIFEST['deploymentBlockNumber'])]
            scan = subprocess.check_output(['bash', M05 / 'run.sh', *args], text=True, timeout=45)
            report = order(callback=True)
            global last_run
            last_run = (scan.strip(), report['newHint'], report['decision'])
            self.redirect('/result')


if __name__ == '__main__':
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', ORDER):
        sys.exit('invalid order id')
    serve(18038, Desk)
