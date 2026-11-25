"""Run `python3 tools/build.py` after changing course Markdown, templates, site.css or site.js (Python-Markdown 3.x)."""
from hashlib import sha256
from html import escape
from pathlib import Path
import re

import markdown
from markdown.extensions.toc import slugify_unicode
from markdown.treeprocessors import Treeprocessor

ROOT = Path(__file__).resolve().parents[1]
SITE = '链上开发手册'
VOLUMES = (
    ('m01', 'M01 · 账本、钱包与密码学', ('ledger', 'crypto', 'wallet', 'networks')),
    ('m02', 'M02 · 比特币：从 UTXO 到收款凭证', ('confirmations', 'bitcoin', 'scripts', 'psbt')),
    ('m03', 'M03 · 以太坊：账户、Gas 与回执', ('accounts', 'nonce', 'evm', 'receipts')),
    ('m04', 'M04 · Solidity：托管与合约测试', ('abi', 'escrow', 'invariants', 'deployment')),
    ('m05', 'M05 · Java：把链上事实变成业务流水', ('rpc', 'indexing', 'reorg', 'reconciliation')),
    ('m06', 'M06 · 钱包接入、代币与 DeFi', ('siwe', 'allowance', 'swap', 'health')),
    ('m07', 'M07 · L2、智能账户与跨层状态〔选修〕', ('rollup', 'l2-fees', 'userop', 'withdrawal')),
)
LESSONS = tuple(slug for _, _, slugs in VOLUMES for slug in slugs)
ASSET_URLS = {
    name: f'assets/{name}?v={sha256((ROOT / "assets" / name).read_bytes()).hexdigest()[:12]}'
    for name in ('site.css', 'site.js')
}
# Opening specimens use the same facts as the lesson, not live transaction data.
SPECIMENS = {
    'PLAN': ('这 40 课怎么读', '第一遍', '看例子', '→', '想动手时', '做实验', '先判断这张记录能说明什么，不用安装软件'),
    'ledger': ('这张订单的付款凭条 · 18 号', '谁付的', '小陈', '→', '谁收的', 'B 店', '这笔付了 1 张券，订单要收 2 张'),
    'crypto': ('第 17 号订单', '签字时写的是', '125 聪', '≠', '后来收到的是', '126 聪', '聪是比特币的小单位；这里不用换算'),
    'wallet': ('第二张收款单', '原来地址的末尾', '…erkf9g', '≠', '换机器后看到的末尾', '…306fyu', '这里只摘最后六位；核对时要比完整地址'),
    'networks': ('这次该用哪本练习账？', '约好用的编号', '31337', '≠', '另一本的编号', '31338', '两个都是练习用的网络'),
    'confirmations': ('Bob 的放货单', '块高 102', '1 次确认', '→', '链尖 103', '2 次确认', '同一笔 1.25 BTC；订单门槛为 2 次确认'),
    'bitcoin': ('regtest 付款单', '付款方', 'Alice', '→', '收款方', 'Bob', '付款金额：1.25 BTC'),
    'scripts': ('同一个钱包的两笔奖励', '第一笔', '50 BTC', '=', '第二笔', '50 BTC', '金额相同，花钱时要交的证明不同；光看地址不能替别人签字'),
    'psbt': ('待审付款单', '商户应收 / sat', '60,000', '≠', '草案付款 / sat', '59,999', '找零多了 1 sat；费用仍为 420 sat'),
    'accounts': ('A-09 · 到账前后', 'B 发出过几笔', '0 笔', '→', '到账后发出过几笔', '0 笔', 'B 收到 125 wei（以太币的最小单位）；收一笔不算发一笔'),
    'nonce': ('P-10 · 同一账户排队付款', '只数已记账的', '下个号 0', '≠', '连排队的一起数', '下个号 1', '找回原来那笔 7,000 wei 的退款；不要因为没等到答复就另开一单'),
    'evm': ('0.01 ETH 付款的费用单', '费用上限 / gwei', '90,000', '≠', '实付 / gwei', '42,000', '两项都是总金额；Bob 应收的 0.01 测试 ETH 没有变'),
    'receipts': ('商户订单 R-12', '提交时拿到', '交易编号', '≠', '现在查回执', '还没有', '应收 0.003 测试 ETH；现在答不出是否付成，不让买家再付一次'),
    'abi': ('给金额登记簿填一个数', '送进去的指令', '36 字节', '→', '模拟返回的数', '32 字节', '多出的 4 字节用来选操作；这张指令没有附带转账'),
    'escrow': ('M-14 · 结算后、领取前', 'B 应领 / wei', '12,500', '≠', 'B 已领 / wei', '0', '钱仍在托管合约；不要再付一笔'),
    'invariants': ('41 wei · 再次领取前后', '首次领取后实收', '41 wei', '=', '重试后累计实收', '41 wei', '第二次领取被拒；把两行累计实收相加会多算一笔'),
    'deployment': ('31337 · 核对旧部署清单', '清单指向的块', '1', '≠', '新空链的高度', '0', '链号相同，但新节点没有这笔部署的回执'),
    'rpc': ('R-17 · 同一笔锁款', '原件金额末四位', '0993', '≠', '报表金额末四位', '0992', '前面的数位都相同；报表把整数转为浮点数，少了 1 wei'),
    'indexing': ('无人订阅时的扫描书签', '停扫时的块高', '1', '→', '补扫后的块高', '4', '补了 3 个块，只有 2 条业务日志；最后一块是空块'),
    'reorg': ('同一笔 37 wei 的托管', '旧支收款方应领', '37 wei', '→', '新支收款方应领', '0 wei', '付款方在新支领走 37 wei；旧结算回执保留，但不再计数'),
    'reconciliation': ('托管应领核对单', '订单要求 / wei', '126', '≠', '结算事件 / wei', '125', '相差 1 wei，不记账；回调再来一次也不能补齐差额'),
    'siwe': ('L-21 · 签字前换了账户', '登录单上写的是', 'A', '≠', '钱包现在显示', 'B', '网络没换，但登录的人换了；要给 B 另开一张登录单'),
    'allowance': ('LAB6 · 一张扣款授权单', 'B 最多可扣', '2.5 枚', '≠', 'B 已经收到', '0 枚', '允许扣款不等于扣过款；还要查实际扣款的回执和双方余额'),
    'swap': ('同一储备 · 两张报价单', '输入 10 A18', '1.9743', '>', '输入 100 A18', '1.8132', '单位：B6 / A18，均价四舍五入到小数点后四位；两次询价都没有成交'),
    'health': ('这次估值还能用吗？', '约定价格最多能用', '300 秒', '<', '距离上次更新', '301 秒', '这次不能报价；不能把旧价格当零，也不能抄上一次的结果'),
    'rollup': ('OP Sepolia 的一笔练习转账', '在第二层执行', '已记账', '≠', '这次记录能否再变', '还没最终定下', '这是当时的观察：已经找到批次 3,631,439，最终确认的位置还没到这笔交易'),
    'l2-fees': ('Base Sepolia · 块 22,000,000', 'L2 执行 / gwei', '116.809', '+', 'L1 数据 / gwei', '6.328', '分项四舍五入到 0.001 gwei；入账时按回执的整数 wei 相加'),
    'userop': ('27 号工单 · 本次不准盖章', '递单交易', '成功', '≠', '工单盖章', '失败', '代付方仍被扣费；谁花了钱，和事情有没有办成，要分别核对'),
    'withdrawal': ('0.3 测试 ETH · 领取前一块', '现在试算能否领取', '可以', '≠', '查到实际付款了吗', '没有', '试算没有发交易；下一块才有对应这笔提款的付款记录'),
    'solana-payment': ('S-30 · 原付款单的有效期已过', '已提交的 A 单', '有回执', '≠', '扣住未发的 B 单', '未付款', '两单各拟付 0.00125 SOL；过期不会撤销 A，也不让 B 自动成交'),
    'registry': ('R-31 · A 申请把登记号改为 3109', '选自己的表，结果是', '3109', '≠', '错选 B 表，B 仍是', '7202', '两张表由同一程序管理，但甲不能凭自己的签字改动乙的表'),
    'spl-delivery': ('S-32 · 同一种代币的收发账', '仓库发出', '1.250001 枚', '→', '收货方实收', '1.250001 枚', '两边都数到 1,250,001 个最小单位；转账手续费在另一笔账里'),
    'preimage': ('同一份证明交给同一个核验人', '照原登记值核对', '通过', '≠', '只换登记值', '拒绝', '它能证明这项声明成立，不能拿来认定交件人的真实身份'),
    'operations': ('OPS-39 · 节点又能答话了', '账本最新一页', '第 4 块', '≠', '备份只读到', '第 1 块', '还差三块没补读；重新连上不代表可以恢复通知'),
    'hackathon': ('DESK-38 · 同一笔款，换个验收条件', '本轮实际确认', '2 次', '<', '评委现在要求', '3 次', '结算记在第 3 块，只查到第 4 块；再等一块，不要再付一次'),
}


def page(title, prefix, main, source_href):
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><title>{escape(title)} · 链上开发手册</title>
<link rel="stylesheet" href="{prefix}{ASSET_URLS['site.css']}"><script src="{prefix}{ASSET_URLS['site.js']}" defer></script></head>
<body><a class="skip" href="#main">跳至正文</a><header class="mast"><div class="mast-inner">
<a class="brand" href="{prefix}index.html"><span class="mark" aria-hidden="true"></span>{SITE}</a>
<nav aria-label="全站导航"><a href="{prefix}plan.html">课程计划</a><a href="{prefix}index.html#labs">实验台</a><button type="button" id="theme" hidden>切换主题</button></nav>
</div></header>{main}<footer><span>{SITE}</span><a href="{prefix}index.html">课程首页</a><a href="{source_href}">Markdown 原稿</a></footer></body></html>'''


def anchor(text, separator):
    module = re.match(r'^M(\d\d) · ', text)
    return 'm' + module[1] if module else slugify_unicode(text, separator)


class LabelTables(Treeprocessor):
    """Keep each cell's column heading available in the narrow-screen layout."""
    def run(self, root):
        for table in root.iter('table'):
            headers = [''.join(th.itertext()) for th in table.findall('./thead/tr/th')]
            if len(headers) >= 3:
                table.set('class', 'stackable')
                for row in table.findall('./tbody/tr'):
                    for cell, heading in zip(row, headers):
                        cell.set('data-label', heading)


def specimen(slug):
    title, left_label, left, relation, right_label, right, note = SPECIMENS[slug]
    return f'''<figure class="specimen"><figcaption>{title}</figcaption><dl>
<div><dt>{left_label}</dt><dd>{left}</dd></div>
<div><dt>{right_label}</dt><dd>{right}</dd></div></dl>
<span class="specimen-relation" aria-hidden="true">{escape(relation)}</span><p>{note}</p></figure>'''


def reader(source, target, label):
    md = markdown.Markdown(extensions=['tables', 'fenced_code', 'toc'],
                           extension_configs={'toc': {'toc_depth': '2-2', 'slugify': anchor}})
    md.treeprocessors.register(LabelTables(md), 'label-tables', 1)
    heading, body = source.read_text().split('\n', 1)
    title = heading.removeprefix('# ').strip()
    lead, _, body = body.strip().partition('\n\n')
    if source.stem not in SPECIMENS:
        raise ValueError(f'{source.name} 缺少首屏图示：请在 SPECIMENS 中登记与导语对应的凭据或路线。')
    opening = f'<header class="lesson-opening"><h1 id="page-title">{escape(title)}</h1>{specimen(source.stem)}{markdown.markdown(lead)}</header>'
    article = md.convert(body)
    prefix = '' if target.parent == ROOT else '../'
    toc = ''.join(f'<li><a href="#{escape(t["id"])}">{escape(t["name"])}</a></li>' for t in md.toc_tokens)
    crumb = escape(label)
    links = f'<a href="{prefix}index.html#labs">返回实验台</a><a href="{prefix}plan.html">完整课程计划</a>'
    for volume, volume_title, slugs in VOLUMES:
        if source.stem not in slugs:
            continue
        i = LESSONS.index(source.stem)
        crumb = f'<a href="../plan.html#{volume}">{volume_title}</a> / 第 {i + 1:02} 课'
        previous = (f'<a rel="prev" href="{LESSONS[i - 1]}.html">上一课 · {i:02}</a>'
                    if i else f'<a href="../plan.html#{volume}">本卷目录</a>')
        following = (f'<a rel="next" href="{LESSONS[i + 1]}.html">下一课 · {i + 2:02}</a>'
                     if i + 1 < len(LESSONS) else '<a href="../plan.html#m10">下一主线卷 · M10 计划</a>')
        if source.stem == 'health':
            following = '<a rel="next" href="rollup.html">选修 · 25 Rollup</a><a href="../plan.html#m10">继续主线 · M10 计划</a>'
        links = previous + following
        break
    zoom = '''<dialog class="figure-zoom" aria-label="配图放大视图">
<form method="dialog"><a>打开 SVG 原图</a><button autofocus>收起大图</button></form>
<div class="zoom-scroll" tabindex="0" role="region" aria-label="放大的配图，可滚动"><img alt=""></div></dialog>''' if 'class="lesson-figure"' in article else ''
    main = f'''<main id="main" class="reading"><div class="crumb"><a href="{prefix}index.html">手册首页</a> / {crumb}</div>
{opening}<div class="reading-grid"><article aria-labelledby="page-title"><details class="mobile-toc"><summary>本页目录</summary><ol>{toc}</ol></details>{article}
<nav class="end-links" aria-label="阅读导航">{links}</nav></article>
<aside class="rail"><nav aria-label="本页目录"><b>本页目录</b><ol>{toc}</ol></nav></aside></div>{zoom}</main>'''
    target.write_text(page(title, prefix, main, source.name))
    return md.toc_tokens


def volume_list(tokens, optional):
    items = []
    for token in tokens:
        if not re.fullmatch('m[0-9]{2}', token['id']):
            continue
        number, title = token['name'].split(' · ', 1)
        title, elective, _ = title.partition('〔')
        if bool(elective) == optional:
            items.append(f'<li><a href="plan.html#{token["id"]}"><span class="volume-no">{number}</span><span>{escape(title)}</span></a></li>')
    return '<ul class="volumes">' + ''.join(items) + '</ul>'


def build():
    toc = reader(ROOT / 'PLAN.md', ROOT / 'plan.html', '课程计划')
    for source in sorted((ROOT / 'labs').glob('*.md')):
        reader(source, source.with_suffix('.html'), '实操样课')
    home = (ROOT / 'tools/home.html').read_text().replace('<!-- CORE -->', volume_list(toc, False)).replace('<!-- ELECTIVES -->', volume_list(toc, True))
    (ROOT / 'index.html').write_text(page('课程首页', '', home, 'PLAN.md'))


if __name__ == '__main__':
    build()
