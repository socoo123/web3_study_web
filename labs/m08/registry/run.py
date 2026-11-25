"""Register two local users; archive the confirmed receipts and paired PDA reads."""
import argparse
import base64
import hashlib
import json
import struct
import sys
from pathlib import Path

from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import ID as SYSTEM_PROGRAM, TransferParams, transfer

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from localnet import Validator

PROGRAM = Pubkey.from_string("841hPEnHjRQ7bn4tm6Lk6whxMtt5dCfbJL2Hf5QA6XKv")
ENTRY = struct.Struct("<8s32sQB")
INITIAL = {"A": 3101, "B": 7202}


def discriminator(label):
    return hashlib.sha256(label.encode("ascii")).digest()[:8]


def instruction(name, authority, address, ticket):
    is_init = name == "register"
    accounts = [AccountMeta(authority, True, is_init), AccountMeta(address, False, True)]
    if is_init:
        accounts.append(AccountMeta(SYSTEM_PROGRAM, False, False))
    data = discriminator(f"global:{name}") + ticket.to_bytes(8, "little")
    return Instruction(PROGRAM, data, accounts)


def save(out, filename, obj):
    (out / filename).write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def receipt(net, out, name, instructions, signers=(), *, rejected=False):
    tx = net.send(instructions, list(signers), skip_preflight=rejected)
    save(out, f"{name}.json", tx)
    signature = tx["transaction"]["signatures"][0]
    meta = tx["meta"]
    print(f"{name} slot={tx['slot']} signature={signature} err={meta['err']}")
    if rejected:
        need(meta["err"] == {"InstructionError": [0, {"Custom": 2006}]}, "not ConstraintSeeds")
        need(any("ConstraintSeeds" in line for line in meta["logMessages"]), "missing Anchor error log")
        need(tx["transaction"]["message"]["accountKeys"][0] == str(net.payer.pubkey()), "unexpected fee payer")
        need(meta["preBalances"][0] - meta["postBalances"][0] == meta["fee"] > 0, "fee mismatch")
    else:
        need(meta["err"] is None, f"{name} failed: {meta['err']}")
    return tx


def read_pair(net, out, stage, users, pdas, expected, min_slot):
    labels = list(users)
    result = net.rpc("getMultipleAccounts", [
        [str(pdas[k][0]) for k in labels],
        {"encoding": "base64", "commitment": "confirmed", "minContextSlot": min_slot},
    ])
    save(out, f"{stage}.json", result)
    for k, account in zip(labels, result["value"], strict=True):
        need(account is not None and account["owner"] == str(PROGRAM) and not account["executable"], f"{k}: owner or type mismatch")
        encoded, encoding = account["data"]
        need(encoding == "base64", "unexpected RPC encoding")
        fields = ENTRY.unpack(base64.b64decode(encoded, validate=True))
        want = (discriminator("account:Entry"), bytes(users[k].pubkey()), expected[k], pdas[k][1])
        need(fields == want, f"{k}: unexpected entry at {stage}")
    print(f"{stage} slot={result['context']['slot']} A={expected['A']} B={expected['B']}")
    return result["value"]


def run(out, so, actor, ticket):
    so_digest = hashlib.sha256(so.read_bytes()).hexdigest()
    out.mkdir()  # One fresh evidence directory per ledger; never mix signatures.
    users = {label: Keypair() for label in INITIAL}
    pdas = {k: Pubkey.find_program_address([b"entry", bytes(u.pubkey())], PROGRAM) for k, u in users.items()}
    need(pdas["A"][0] != pdas["B"][0], "expected two distinct PDAs")
    with Validator(programs=[(PROGRAM, so)]) as net:
        save(out, "manifest.json", {
            "genesisHash": net.rpc("getGenesisHash", []), "version": net.rpc("getVersion", []),
            "programId": str(PROGRAM), "soSha256": so_digest,
            "lockSha256": hashlib.sha256((HERE / "Cargo.lock").read_bytes()).hexdigest(),
            "feePayer": str(net.payer.pubkey()), "commitment": "confirmed", "actor": actor,
            "requestedTicket": str(ticket), "snapshotOrder": list(users),
            "users": {k: {"authority": str(u.pubkey()), "entry": str(pdas[k][0]), "bump": pdas[k][1]}
                      for k, u in users.items()},
        })
        # Leave each system wallet rent-exempt even after it funds its 49-byte entry.
        fund = sum(net.rpc("getMinimumBalanceForRentExemption", [n]) for n in (0, ENTRY.size))
        receipt(net, out, "fund", [transfer(TransferParams(from_pubkey=net.payer.pubkey(),
                to_pubkey=u.pubkey(), lamports=fund)) for u in users.values()])
        for label, u in users.items():
            ix = instruction("register", u.pubkey(), pdas[label][0], INITIAL[label])
            tx = receipt(net, out, f"register-{label}", [ix], [u])
            need(f"Program {SYSTEM_PROGRAM} invoke [2]" in tx["meta"]["logMessages"], "missing init CPI")
        read_pair(net, out, "registered", users, pdas, INITIAL, tx["slot"])

        u = users[actor]
        ix = instruction("revise", u.pubkey(), pdas[actor][0], ticket)
        tx = receipt(net, out, "revise", [ix], [u])
        expected = {**INITIAL, actor: ticket}
        before = read_pair(net, out, "before-refusal", users, pdas, expected, tx["slot"])

        other = "B" if actor == "A" else "A"
        ix = instruction("revise", u.pubkey(), pdas[other][0], ticket)
        tx = receipt(net, out, "refused", [ix], [u], rejected=True)
        after = read_pair(net, out, "after-refusal", users, pdas, expected, tx["slot"])
        need(before == after, "PDA account records changed")
        print(f"REFUSED unchanged=2 feeLamports={tx['meta']['fee']} evidence={out}")


def u64(text):
    value = int(text)
    if not 0 <= value < 1 << 64:
        raise argparse.ArgumentTypeError("ticket outside u64")
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="new directory under an existing parent")
    parser.add_argument("--so", type=Path, default=HERE / "target/deploy/course_registry.so")
    parser.add_argument("--actor", choices=INITIAL, default="A")
    parser.add_argument("--ticket", type=u64, default=3109)
    args = parser.parse_args()
    run(args.out, args.so.resolve(), args.actor, args.ticket)
