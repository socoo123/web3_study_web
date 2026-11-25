"""Review a saved local delivery; never opens an RPC connection or signs."""
import argparse
import base64
import json
from pathlib import Path
import struct
import sys

from solders.pubkey import Pubkey
from solders.system_program import ID as SYSTEM
from solders.token import ID as TOKEN
from solders.transaction import VersionedTransaction

ATA_PROGRAM = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
DECIMALS = 6


def ata(wallet, mint):
    return Pubkey.find_program_address([bytes(wallet), bytes(TOKEN), bytes(mint)], ATA_PROGRAM)[0]


def require(ok, name):
    if not ok:
        raise ValueError(f"insufficient or inconsistent evidence: {name}")


def binary(pair):
    value, encoding = pair
    require(encoding == "base64", "base64 encoding")
    return base64.b64decode(value, validate=True)


def state(snapshot, r):
    accounts = snapshot["value"]
    require(len(accounts) == 3 and all(a and a["owner"] == str(TOKEN) and not a["executable"]
                                       for a in accounts), "runtime program owner")
    mint, src, dst = [binary(a["data"]) for a in accounts]
    require(len(mint) == 82 and (mint[44], mint[45]) == (DECIMALS, 1), "initialized classic mint")
    require(int.from_bytes(mint[:4], "little") == 1 and str(Pubkey.from_bytes(mint[4:36])) == r["mintAuthority"],
            "mint authority")
    require(int.from_bytes(mint[46:50], "little") == 0, "absent freeze authority")
    amounts = []
    for data, owner in ((src, r["sourceOwner"]), (dst, r["destinationOwner"])):
        require(len(data) == 165 and data[108] == 1, "initialized classic token account")
        require(str(Pubkey.from_bytes(data[:32])) == r["mint"] and str(Pubkey.from_bytes(data[32:64])) == owner,
                "token account mint and internal owner")
        amounts.append(int.from_bytes(data[64:72], "little"))
    return (int.from_bytes(mint[36:44], "little"), *amounts)


def token_balances(rows, keys, r):
    by_address = {}
    for row in rows:
        address = keys[row["accountIndex"]]
        require(address not in by_address and row["programId"] == str(TOKEN) and row["mint"] == r["mint"],
                "transaction token balance identity")
        amount = row["uiTokenAmount"]
        require(amount["decimals"] == DECIMALS, "transaction token balance decimals")
        by_address[address] = (row["owner"], int(amount["amount"]))
    src, dst = by_address[r["sourceAta"]], by_address[r["destinationAta"]]
    require((src[0], dst[0]) == (r["sourceOwner"], r["destinationOwner"]), "transaction token owners")
    return src[1], dst[1]


def review(e):
    r, order = e["roles"], e["order"]
    issued, sent, due = (int(order[k]) for k in ("issueRaw", "sendRaw", "dueRaw"))
    require(0 < sent <= issued < 2**64 and 0 < due < 2**64, "order amounts")
    require(e["commitment"] == "confirmed" and e["programs"] == {"token": str(TOKEN), "associatedToken": str(ATA_PROGRAM)},
            "program selection / commitment")
    require(len(set(r.values())) == len(r), "distinct roles in this exercise")
    mint = Pubkey.from_string(r["mint"])
    for side in ("source", "destination"):
        require(str(ata(Pubkey.from_string(r[side + "Owner"]), mint)) == r[side + "Ata"], side + " ATA seeds")
    require(e["accountOrder"] == [r["mint"], r["sourceAta"], r["destinationAta"]], "RPC snapshot order")
    print(f"LEDGER genesis={e['genesisHash']} mint={mint} decimals={DECIMALS} freezeAuthority=None")

    expected_states = {"accounts": (0, 0, 0), "issue": (issued, issued, 0),
                       "rejected": (issued, issued, 0), "delivery": (issued, issued - sent, sent)}
    snapshots, receipts = e["snapshots"], e["receipts"]
    observed = {}
    for step, want in expected_states.items():
        snap = snapshots[step]
        require(snap["context"]["slot"] >= receipts[step]["slot"], step + " snapshot too old")
        actual = state(snap, r)
        require(actual == want, step + " supply/source/destination")
        observed[step] = actual
        print(f"STATE {step} slot={snap['context']['slot']} supplyRaw={actual[0]} sourceRaw={actual[1]} destinationRaw={actual[2]}")
    require([a["data"] for a in snapshots["issue"]["value"]] == [a["data"] for a in snapshots["rejected"]["value"]],
            "all three account payloads unchanged after rejection")

    signer_roles = {"mint": ["mint"], "accounts": [], "issue": ["mintAuthority"],
                    "rejected": ["sourceOwner"], "delivery": ["sourceOwner"]}
    for step, extra in signer_roles.items():
        rec = receipts[step]
        tx = VersionedTransaction.from_bytes(binary(rec["transaction"]))
        message, meta = tx.message, rec["meta"]
        keys = list(map(str, message.account_keys))
        signers = keys[:message.header.num_required_signatures]
        require(keys[0] == r["payer"] and set(signers) == {r[k] for k in ["payer", *extra]} and
                len(tx.signatures) == len(signers) and all(tx.verify_with_results()), step + " signatures")
        programs = [keys[ix.program_id_index] for ix in message.instructions]
        require(programs == {"mint": [str(SYSTEM), str(TOKEN)], "accounts": [str(ATA_PROGRAM)] * 2}.get(step, [str(TOKEN)]),
                step + " invoked programs")
        err = {"InstructionError": [0, {"Custom": 18}]} if step == "rejected" else None
        require(meta["err"] == err and meta["logMessages"], step + " execution result")
        fee = meta["fee"]
        # Creation moves storage lamports into the new accounts; only the rest is the transaction fee.
        created = {"mint": [r["mint"]], "accounts": [r["sourceAta"], r["destinationAta"]]}.get(step, [])
        pre, post = meta["preBalances"], meta["postBalances"]
        storage = sum(post[keys.index(a)] - pre[keys.index(a)] for a in created)
        require(pre[0] - post[0] == storage + fee, step + " lamport ledger")
        print(f"TX {step} slot={rec['slot']} signature={tx.signatures[0]} feeLamports={fee} storageLamports={storage} err={meta['err']}")
        if step in ("rejected", "delivery"):
            ix, = message.instructions
            require([keys[i] for i in ix.accounts] == [r["sourceAta"], r["mint"], r["destinationAta"], r["sourceOwner"]],
                    step + " TransferChecked accounts")
            require(struct.unpack("<BQB", ix.data) == (12, sent, DECIMALS - (step == "rejected")),
                    step + " signed opcode, u64 amount and decimals")
            require(token_balances(meta["preTokenBalances"], keys, r) == (issued, 0) and
                    token_balances(meta["postTokenBalances"], keys, r) == observed[step][1:],
                    step + " transaction-scoped token deltas")
    received = observed["delivery"][2] - observed["rejected"][2]
    status = "MATCH_LOCAL" if received == due else "HOLD_AMOUNT"
    print(f"ORDER {status} dueRaw={due} receivedRaw={received} differenceRaw={due - received}")
    return 0 if received == due else 3


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    sys.exit(review(json.loads(args.evidence.read_text(encoding="utf-8"))))
