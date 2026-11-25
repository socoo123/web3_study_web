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
    'PLAN': ('前四课怎么读', '第一遍', '看例子', '→', '想动手时', '做实验', '先用纸笔查一笔账，不用安装软件'),
    'ledger': ('这张订单的付款凭条 · 18 号', '谁付的', '小陈', '→', '谁收的', 'B 店', '这笔付了 1 张券，订单要收 2 张'),
    'crypto': ('第 17 号订单', '签字时写的是', '125 聪', '≠', '后来收到的是', '126 聪', '聪是比特币的小单位；这里不用换算'),
    'wallet': ('第二张收款单', '原来地址的末尾', '…erkf9g', '≠', '换机器后看到的末尾', '…306fyu', '这里只摘最后六位；核对时要比完整地址'),
    'networks': ('这次该用哪本练习账？', '约好用的编号', '31337', '≠', '另一本的编号', '31338', '两个都是练习用的网络'),
    'confirmations': ('Bob 的放货单', '块高 102', '1 次确认', '→', '链尖 103', '2 次确认', '同一笔 1.25 BTC；订单门槛为 2 次确认'),
    'bitcoin': ('regtest 付款单', '付款方', 'Alice', '→', '收款方', 'Bob', '付款金额：1.25 BTC'),
    'scripts': ('两笔 50 BTC 奖励', '脚本以 00 14 开头', '20 字节', '≠', '脚本以 51 20 开头', '32 字节', '比较后续见证程序的长度；两个地址来自同一个钱包'),
    'psbt': ('待审付款单', '商户应收 / sat', '60,000', '≠', '草案付款 / sat', '59,999', '找零多了 1 sat；费用仍为 420 sat'),
    'accounts': ('测试订单 A-09 · 收款人 B', '块 0 的 nonce', '0', '→', '块 1 的 nonce', '0', '余额增加了 125 wei；B 没有发出交易'),
    'nonce': ('退款单 P-10 · 待打包', 'latest 序号', '0', '≠', 'pending 序号', '1', '同一付款账户；要查 7,000 wei 的原单，不给重试分配新号'),
    'evm': ('0.01 ETH 付款的费用单', '费用上限 / gwei', '90,000', '≠', '实付 / gwei', '42,000', '两项都是总金额；Bob 应收的 0.01 测试 ETH 没有变'),
    'receipts': ('商户订单 R-12', '提交应答', '已给哈希', '≠', '执行回执', 'null', '应收 0.003 测试 ETH；先查原交易，不让买家再付一次'),
    'abi': ('金额登记单 · set(uint256)', '调用数据', '36 字节', '→', '返回数据', '32 字节', '多出的 4 字节选择函数；这笔交易附带 0 wei'),
    'escrow': ('M-14 · 结算后、领取前', 'B 应领 / wei', '12,500', '≠', 'B 已领 / wei', '0', '钱仍在托管合约；不要再付一笔'),
    'invariants': ('41 wei · 再次领取前后', '首次领取后实收', '41 wei', '=', '重试后累计实收', '41 wei', '第二次领取被拒；把两行累计实收相加会多算一笔'),
    'deployment': ('31337 · 核对旧部署清单', '清单指向的块', '1', '≠', '新空链的高度', '0', '链号相同，但新节点没有这笔部署的回执'),
    'rpc': ('R-17 · 一笔锁款的两个读数', '原始金额 / wei', '2⁵³ + 1', '≠', '转为 double / wei', '2⁵³', '同一份回执，若金额经过 double 就会少 1 wei'),
    'indexing': ('无人订阅时的扫描书签', '停扫时的块高', '1', '→', '补扫后的块高', '4', '补了 3 个块，只有 2 条业务日志；最后一块是空块'),
    'reorg': ('同一笔 37 wei 的托管', '旧支收款方应领', '37 wei', '→', '新支收款方应领', '0 wei', '付款方在新支领走 37 wei；旧结算回执保留，但不再计数'),
    'reconciliation': ('托管应领核对单', '订单要求 / wei', '126', '≠', '结算事件 / wei', '125', '相差 1 wei，不记账；回调再来一次也不能补齐差额'),
    'siwe': ('L-21 · 等待签名时换账户', '挑战里的账户', 'A', '≠', '钱包现在显示', 'B', '链号仍是 31337；A 的登录证明不能给 B 建会话，须重新申请挑战'),
    'allowance': ('LAB6 · A 给 B 设限后', 'B 可扣 / LAB6', '2.5', '≠', 'B 已收 / LAB6', '0', '授权改的是额度；要看有没有扣款，再查 transferFrom 的回执和两端余额'),
    'swap': ('同一储备 · 两张报价单', '输入 10 A18', '1.9743', '>', '输入 100 A18', '1.8132', '单位：B6 / A18，均价四舍五入到小数点后四位；两次询价都没有成交'),
    'health': ('同一仓位 · 抵押物价格的年龄', '允许的上限', '300 秒', '<', '本次读到', '301 秒', '停报健康度；不能把过期价格补成零，也不能沿用上一笔的 1.2'),
    'rollup': ('OP Sepolia · 批次 3,631,439', '回执所在块', '已执行', '≠', '当时的最终性', '未最终化', '沿 44 条父哈希可连到 safe 头；finalized 头还在这笔交易之前'),
    'l2-fees': ('Base Sepolia · 块 22,000,000', 'L2 执行 / gwei', '116.809', '+', 'L1 数据 / gwei', '6.328', '分项四舍五入到 0.001 gwei；入账时按回执的整数 wei 相加'),
    'userop': ('27 号工单 · 业务被冻结', '外层交易状态', '1', '≠', '操作成功？', 'false', '没有盖章，代付存款仍被扣费；存款连预付额也不够时则不提交'),
    'withdrawal': ('0.3 测试 ETH · 领取前一块', 'L1 领取模拟', '成功', '≠', '标准桥付款凭据', '尚无', '模拟没有发交易；下一块才有与这笔消息相符的标准桥付款事件'),
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
