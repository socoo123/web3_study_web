"""Read one hash-pinned teaching position and reproduce RiskView's estimate with integers."""
import argparse
import subprocess
from dataclasses import dataclass

from chain import anvil, deploy, units


STATES = ('READY', 'NO_DEBT', 'MISSING', 'BAD_ANSWER', 'BAD_TIME', 'STALE')
SIDES = ('none', 'collateral', 'debt')


@dataclass(frozen=True)
class Quote:
    published: int
    raw: int
    digits: int
    updated: int


@dataclass(frozen=True)
class Policy:
    col_digits: int
    debt_digits: int
    quote_digits: int
    ltv_bps: int
    lt_bps: int
    max_age: int


def words(rpc, address, selector, anchor, count):
    # Solely for these four known getters: every output component occupies one static ABI word.
    data = rpc('eth_call', {'to': address, 'data': selector}, anchor)
    if not data.startswith('0x') or len(data) != 2 + count * 64:
        raise ValueError(f'unexpected {count}-word ABI result: {data}')
    return tuple(int(data[i:i + 64], 16) for i in range(2, len(data), 64))


def recompute(col_raw, debt_raw, policy, quotes, now):
    if debt_raw == 0:
        return 'NO_DEBT', 'none', None
    for side, q in zip(SIDES[1:], quotes, strict=True):
        if not q.published:
            return 'MISSING', side, None
        if q.raw <= 0:
            return 'BAD_ANSWER', side, None
        if not 0 < q.updated <= now:
            return 'BAD_TIME', side, None
        if now - q.updated > policy.max_age:
            return 'STALE', side, None

    col, note = quotes
    scale = 10 ** policy.quote_digits
    c = col_raw * col.raw * scale // 10 ** (policy.col_digits + col.digits)
    d, remainder = divmod(debt_raw * note.raw * scale, 10 ** (policy.debt_digits + note.digits))
    d += int(remainder != 0)
    adjusted = c * policy.lt_bps // 10_000
    headroom = max(0, c * policy.ltv_bps // 10_000 - d)
    return 'READY', 'none', (c, d, adjusted, adjusted * 10**18 // d, headroom)


def result_line(label, result):
    state, side, metrics = result
    fields = 'metrics=absent' if metrics is None else ' '.join(
        f'{key}={v}' for key, v in zip(('collateralQ8', 'debtQ8', 'adjustedQ8', 'hfWad', 'headroomQ8'), metrics, strict=True))
    print(f'{label} state={state} side={side} {fields}')


def run(args):
    with anvil(18624) as rpc:
        sender = rpc('eth_accounts')[0]
        view = deploy(rpc, sender, 'RiskView', 'constructor(uint96,uint96,uint64,uint32,uint8)',
                      args.coll_raw, args.debt_raw, args.coll_price_raw, args.coll_age, SIDES.index(args.missing))
        block = rpc('eth_getBlockByNumber', 'latest', False)
        now = int(block['timestamp'], 16)
        anchor = {'blockHash': block['hash'], 'requireCanonical': True}
        print(f'SNAPSHOT chainId={int(rpc("eth_chainId"), 16)} view={view} '
              f'height={int(block["number"], 16)} hash={block["hash"]} timestamp={now}')

        def selector(sig):
            return subprocess.check_output(['cast', 'sig', sig], text=True).strip()

        col_raw, debt_raw, col_feed, debt_feed = words(rpc, view, selector('position()'), anchor, 4)
        p = Policy(*words(rpc, view, selector('policy()'), anchor, 6))
        print(f'POSITION colRaw={col_raw} colDigits={p.col_digits} debtRaw={debt_raw} debtDigits={p.debt_digits}')
        print(f'POLICY quoteDigits={p.quote_digits} ltvBps={p.ltv_bps} ltBps={p.lt_bps} maxAgeSeconds={p.max_age}')
        prices = []
        quote_selector = selector('quote()')
        for side, addr in zip(SIDES[1:], (col_feed, debt_feed), strict=True):
            address = f'0x{addr:040x}'
            q = Quote(*words(rpc, address, quote_selector, anchor, 4))
            prices.append(q)
            print(f'FEED side={side} address={address} present={q.published} priceDigits={q.digits} '
                  f'answerRaw={q.raw if q.published else "absent"} updatedAt={q.updated if q.published else "absent"} '
                  f'ageSeconds={now - q.updated if q.published else "absent"}')

        state, side, *payload = words(rpc, view, selector('inspect()'), anchor, 7)
        onchain = (STATES[state], SIDES[side], tuple(payload) if state == 0 else None)
        offline = recompute(col_raw, debt_raw, p, prices, now)
        result_line('GETTER', onchain)
        result_line('OFFLINE', offline)
        if onchain != offline:
            raise RuntimeError('STOP: chain result differs from independent arithmetic')

        status, side_name, metrics = offline
        if status == 'NO_DEBT':
            print('RESULT NO_DEBT hf=not_applicable headroom=not_evaluated executableQuote=false')
            return 0
        if metrics is None:
            print(f'RESULT HOLD_{status} side={side_name} hf=unavailable headroom=unavailable executableQuote=false')
            return 3
        c, d, adjusted, hf, room = metrics
        boundary = 'BELOW' if adjusted < d else 'AT' if adjusted == d else 'ABOVE'
        print(f'RESULT ESTIMATE_ONLY collateralQ={units(c, p.quote_digits)} debtQ={units(d, p.quote_digits)} '
              f'hf={units(hf, 18)} boundary={boundary} headroomQ={units(room, p.quote_digits)} executableQuote=false')
        return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--coll-raw', type=int, default=2_500_000_000_000_000_000, help='COL smallest units (18 digits)')
    parser.add_argument('--debt-raw', type=int, default=200_000_000, help='NOTE smallest units (6 digits)')
    parser.add_argument('--coll-price-raw', type=int, default=16_000_000_000, help='Q / COL (8 digits)')
    parser.add_argument('--coll-age', type=int, default=30, help='COL feed age in seconds, 0..86400')
    parser.add_argument('--missing', choices=SIDES, default='none', help='feed with no observation')
    args = parser.parse_args()
    if not (0 <= args.coll_raw < 2**96 and 0 <= args.debt_raw < 2**96 and 0 <= args.coll_price_raw < 2**64
            and 0 <= args.coll_age <= 86400):
        parser.error('amounts must fit uint96, price must fit uint64, age must be 0..86400 seconds')
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
