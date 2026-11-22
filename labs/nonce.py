"""One payer, two local orders, and a lost reply. Run from the repository root."""
import argparse
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from anvil_lab import anvil, RpcError


CHAIN = 31337
TIP = 1_000_000_000  # wei/gas
CAP = 4_000_000_000  # wei/gas
GAS = 21_000


def check(ok, message):
    if not ok:
        raise RuntimeError(message)


def sign(rpc, payer, merchant, nonce, amount):
    raw = rpc("eth_signTransaction", {
        "type": "0x2", "chainId": hex(CHAIN), "from": payer, "to": merchant,
        "nonce": hex(nonce), "value": hex(amount), "gas": hex(GAS),
        "maxPriorityFeePerGas": hex(TIP), "maxFeePerGas": hex(CAP),
        "data": "0x", "accessList": [],
    })
    check(raw.startswith("0x02"), "signer did not return a Type 2 envelope")
    return raw, rpc("web3_sha3", raw)


def uint_bytes(n):
    return n.to_bytes((n.bit_length() + 7) // 8, "big")


def rlp(item):
    if isinstance(item, int):
        item = uint_bytes(item)
    if isinstance(item, list):
        base, payload = 0xc0, b"".join(rlp(part) for part in item)
    else:
        if len(item) == 1 and item[0] < 128:
            return item
        base, payload = 0x80, item
    n = len(payload)
    if n <= 55:
        return bytes([base + n]) + payload
    length = uint_bytes(n)
    return bytes([base + 55 + len(length)]) + length + payload


def verify_author(rpc, tx, raw, payer, merchant, nonce, amount):
    fields = [CHAIN, nonce, TIP, CAP, GAS, bytes.fromhex(merchant[2:]), amount, b"", []]
    parity = int(tx["yParity"] if "yParity" in tx else tx["v"], 16)
    r, s = int(tx["r"], 16), int(tx["s"], 16)
    check(parity in (0, 1), "not a Type 2 recovery parity")
    check("0x02" + rlp(fields + [parity, r, s]).hex() == raw, "signed fields differ from order")
    digest = rpc("web3_sha3", "0x02" + rlp(fields).hex())
    # The ECRECOVER precompile consumes four 32-byte words, not an RLP list.
    words = digest + f"{27 + parity:064x}{r:064x}{s:064x}"
    address_word = rpc("eth_call", {"to": "0x" + "01".zfill(40), "data": words}, "latest")
    check(address_word == "0x" + payer[2:].lower().zfill(64)
          and tx["from"].lower() == payer.lower(), "unexpected signer")
    print(f"SIGN signing_digest={digest} tx_hash={tx['hash']} parity={parity} recovered={payer}")


def count(rpc, payer, tag):
    return int(rpc("eth_getTransactionCount", payer, tag), 16)


def lab(rpc, journal, amount, new_nonce):
    check(int(rpc("eth_chainId"), 16) == CHAIN, "wrong chain before signing")
    payer, merchant = rpc("eth_accounts")
    rpc("evm_setAutomine", False)
    before = int(rpc("eth_getBalance", merchant, "0x0"), 16)
    # Force the read-read-write interleaving; there is no scheduling lottery.
    np = count(rpc, payer, "pending")
    nq = count(rpc, payer, "pending")
    check(np == nq == count(rpc, payer, "latest") == 0, "expected a fresh payer")
    print(f"READ chain={CHAIN} payer={payer} to={merchant} P-10.nonce={np} Q-10.nonce={nq}")
    raw_p, hp = sign(rpc, payer, merchant, np, amount)
    raw_q, hq = sign(rpc, payer, merchant, nq, amount + 2_000)
    check(hp != hq, "different signed orders must have different hashes here")
    with closing(sqlite3.connect(journal)) as db, db:
        db.execute("CREATE TABLE originals (order_id TEXT PRIMARY KEY, hash TEXT NOT NULL, raw TEXT NOT NULL)")
        db.execute("INSERT INTO originals VALUES (?, ?, ?)", ("P-10", hp, raw_p))
    print(f"SAVED order=P-10 nonce={np} amount_wei={amount} hash={hp}")
    # Really submit. Deliberately do not use the reply as input to recovery.
    try:
        rpc("eth_sendRawTransaction", raw_p)
    except OSError:
        print(f"SUBMIT transport_error=true original={hp} action=look_up_original")
    with closing(sqlite3.connect(journal)) as db:
        saved_hash, saved_raw = db.execute("SELECT hash, raw FROM originals WHERE order_id=?", ("P-10",)).fetchone()
    try:
        tx = rpc("eth_getTransactionByHash", saved_hash)
        receipt = rpc("eth_getTransactionReceipt", saved_hash)
    except OSError as exc:
        raise RuntimeError(f"UNKNOWN original={saved_hash} lookup unavailable; do not allocate a nonce") from exc
    if tx is None and receipt is None:
        raise RuntimeError(f"UNKNOWN original={saved_hash} not seen here; do not allocate a nonce")
    check(tx is not None and tx["hash"] == saved_hash and tx.get("blockNumber") is None
          and receipt is None, "expected a known pending transaction, not a receipt")
    latest, pending = count(rpc, payer, "latest"), count(rpc, payer, "pending")
    check((latest, pending) == (0, 1), "unexpected nonce view")
    print(f"LOOKUP original={saved_hash} receipt=null latest={latest} pending={pending}")
    verify_author(rpc, tx, saved_raw, payer, merchant, np, amount)

    try:
        rpc("eth_sendRawTransaction", raw_q)
    except RpcError:
        pass  # Never decide the winner from provider-specific error wording.
    else:
        raise RuntimeError("unexpected admission of the equal-fee competitor")
    check(rpc("eth_getTransactionByHash", hq) is None, "Q-10 unexpectedly visible")
    print(f"CONFLICT order=Q-10 nonce={nq} amount_wei={amount + 2_000} hash={hq} admitted=false")

    expected = [saved_hash]
    if new_nonce:
        # Intentionally wrong business policy, on disposable test accounts only.
        raw2, h2 = sign(rpc, payer, merchant, pending, amount)
        check(h2 != saved_hash and rpc("eth_sendRawTransaction", raw2) == h2, "new hash mismatch")
        expected.append(h2)
        print(f"RETRY order=P-10 mode=new_nonce nonce={pending} hash={h2}")
    else:
        try:
            again = rpc("eth_sendRawTransaction", saved_raw)
        except RpcError:
            reply = "rpc_error"
        else:
            check(again == saved_hash, "same bytes returned a different hash")
            reply = "same_hash"
        print(f"RETRY order=P-10 mode=same_bytes nonce={np} hash={saved_hash} reply={reply}")

    rpc("evm_mine")
    block = rpc("eth_getBlockByNumber", "0x1", False)
    check(block is not None and block["transactions"] == expected, "unexpected block contents/order")
    for h in expected:
        rec = rpc("eth_getTransactionReceipt", h)
        check(rec is not None and int(rec["status"], 16) == 1 and rec["transactionHash"] == h
              and rec["blockHash"] == block["hash"], "missing successful receipt in block 1")
        print(f"MINED height=1 block={block['hash']} hash={h} status=1")
    delta = int(rpc("eth_getBalance", merchant, "0x1"), 16) - before
    latest, pending = count(rpc, payer, "latest"), count(rpc, payer, "pending")
    check(latest == pending == len(expected) and delta == len(expected) * amount
          and rpc("eth_getTransactionReceipt", hq) is None, "unreconciled outcome")
    verdict = "DOUBLE_PAID" if new_nonce else "PAID_ONCE"
    print(f"RESULT order=P-10 receipts={len(expected)} merchant_delta_wei={delta} "
          f"latest={latest} pending={pending} verdict={verdict}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--new-nonce", action="store_true", help="demonstrate the double-payment mistake")
    parser.add_argument("--amount-wei", type=int, default=7_000, help="P-10 amount; Q-10 is 2,000 wei more")
    args = parser.parse_args()
    if not 1 <= args.amount_wei <= 10**15:
        parser.error("--amount-wei must be between 1 and 10^15")
    with TemporaryDirectory() as directory, anvil(18550) as rpc:
        lab(rpc, Path(directory) / "originals.db", args.amount_wei, args.new_nonce)


if __name__ == "__main__":
    main()
